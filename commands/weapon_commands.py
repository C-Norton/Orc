"""Commands for searching and importing weapons from the Open5e API.

Workflow::

    /weapon search <query>  — search the Open5e v2 2024 SRD, cache results
    /weapon add <number>    — import a weapon from the cached results

Session storage is an in-memory dict keyed by ``(user_id, guild_id)`` with a
5-minute TTL.  Results are lost on bot restart; users simply re-run the search.
"""

from __future__ import annotations

import json
import time

import discord
from discord import app_commands
from discord.ext import commands

from database import SessionLocal
from models import Attack, Character
from utils.db_helpers import get_active_character, resolve_user_server
from utils.limits import MAX_ATTACKS_PER_CHARACTER
from utils.logging_config import get_logger
from utils.strings import Strings
from utils.weapon_utils import (
    calculate_weapon_hit_modifier,
    extract_two_handed_damage,
    fetch_weapons,
    format_weapon_result_line,
    get_property_names,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------

# Keyed by (user_id, guild_id) → (weapon_list, expiry_timestamp)
_weapon_search_sessions: dict[tuple[str, str], tuple[list[dict], float]] = {}
SESSION_TTL_SECONDS: int = 300


def _get_session(user_id: str, guild_id: str) -> list[dict] | None:
    """Return cached weapon search results if present and not yet expired."""
    session_key = (user_id, guild_id)
    entry = _weapon_search_sessions.get(session_key)
    if entry is None:
        return None
    weapon_list, expiry_timestamp = entry
    if time.time() > expiry_timestamp:
        del _weapon_search_sessions[session_key]
        return None
    return weapon_list


def _store_session(user_id: str, guild_id: str, weapon_list: list[dict]) -> None:
    """Cache weapon search results for the given user/guild pair."""
    _weapon_search_sessions[(user_id, guild_id)] = (
        weapon_list,
        time.time() + SESSION_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def register_weapon_commands(bot: commands.Bot) -> None:
    """Register the ``/weapon`` command group (``search``, ``add``)."""
    weapon_group = app_commands.Group(
        name="weapon",
        description="Search for and import weapons from the 2024 SRD",
    )

    @weapon_group.command(
        name="search", description="Search for weapons in the 2024 SRD"
    )
    @app_commands.describe(
        query="Weapon name to search for (e.g., longsword, shortbow)"
    )
    async def weapon_search(interaction: discord.Interaction, query: str) -> None:
        """Search Open5e for weapons and show results for the active character.

        Stores up to 5 results in memory for 5 minutes so the user can follow
        up with ``/weapon add <number>`` without re-querying.
        """
        logger.debug(
            f"Command /weapon search called by {interaction.user} "
            f"(ID: {interaction.user.id}) for guild {interaction.guild_id} "
            f"with query: {query!r}"
        )
        await interaction.response.defer(ephemeral=True)
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            character = get_active_character(db, user, server)
            if not character:
                await interaction.followup.send(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            try:
                weapon_list = await fetch_weapons(query)
            except Exception as api_error:
                logger.error(
                    f"/weapon search API error for query {query!r}: {api_error}"
                )
                await interaction.followup.send(
                    Strings.WEAPON_SEARCH_ERROR, ephemeral=True
                )
                return

            if not weapon_list:
                await interaction.followup.send(
                    Strings.WEAPON_SEARCH_NO_RESULTS.format(query=query),
                    ephemeral=True,
                )
                return

            _store_session(
                str(interaction.user.id), str(interaction.guild_id), weapon_list
            )

            result_lines = [
                format_weapon_result_line(index + 1, weapon)
                for index, weapon in enumerate(weapon_list)
            ]
            results_block = "\n".join(result_lines)
            message = (
                Strings.WEAPON_SEARCH_HEADER.format(query=query)
                + "\n"
                + results_block
                + Strings.WEAPON_SEARCH_FOOTER.format(char_name=character.name)
            )

            await interaction.followup.send(message, ephemeral=True)
            logger.info(
                f"/weapon search completed for user {interaction.user.id}: "
                f"{len(weapon_list)} result(s) for {query!r}"
            )
        finally:
            db.close()

    @weapon_group.command(
        name="add", description="Add a weapon from your last search results"
    )
    @app_commands.describe(number="The number of the weapon to add (1–5)")
    async def weapon_add(interaction: discord.Interaction, number: int) -> None:
        """Import a weapon from the cached search results into the character's attacks.

        Calculates the to-hit modifier automatically from the character's stats.
        If an attack with the same name already exists it is updated in place.
        """
        logger.debug(
            f"Command /weapon add called by {interaction.user} "
            f"(ID: {interaction.user.id}) for guild {interaction.guild_id} "
            f"with number: {number}"
        )
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            character = get_active_character(db, user, server)
            if not character:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            weapon_list = _get_session(
                str(interaction.user.id), str(interaction.guild_id)
            )
            if weapon_list is None:
                await interaction.response.send_message(
                    Strings.WEAPON_SEARCH_SESSION_NOT_FOUND, ephemeral=True
                )
                return

            if number < 1 or number > len(weapon_list):
                await interaction.response.send_message(
                    Strings.WEAPON_ADD_INVALID_INDEX.format(max_index=len(weapon_list)),
                    ephemeral=True,
                )
                return

            weapon_data = weapon_list[number - 1]
            weapon_name = weapon_data.get("name", "Unknown")
            damage_dice = weapon_data.get("damage_dice", "1d4")
            damage_type_object = weapon_data.get("damage_type") or {}
            damage_type_name = damage_type_object.get("name", "")
            is_simple = weapon_data.get("is_simple", True)
            weapon_category = "Simple" if is_simple else "Martial"
            # Range is read only to determine the ability modifier (DEX for ranged
            # weapons) and is not stored — range is irrelevant in theatre-of-the-mind.
            range_normal_float = weapon_data.get("range", 0) or 0
            properties = weapon_data.get("properties", [])
            property_names = get_property_names(properties)
            two_handed_damage = extract_two_handed_damage(properties)

            hit_modifier_result = calculate_weapon_hit_modifier(
                character, properties, range_normal_float
            )

            existing_attack = (
                db.query(Attack)
                .filter_by(character_id=character.id, name=weapon_name)
                .first()
            )

            if not existing_attack:
                attack_count = (
                    db.query(Attack).filter_by(character_id=character.id).count()
                )
                if attack_count >= MAX_ATTACKS_PER_CHARACTER:
                    await interaction.response.send_message(
                        Strings.ERROR_LIMIT_ATTACKS.format(
                            char_name=character.name,
                            limit=MAX_ATTACKS_PER_CHARACTER,
                        ),
                        ephemeral=True,
                    )
                    return

            if existing_attack:
                existing_attack.hit_modifier = hit_modifier_result.total
                existing_attack.damage_formula = damage_dice
                existing_attack.damage_type = damage_type_name
                existing_attack.weapon_category = weapon_category
                existing_attack.two_handed_damage = two_handed_damage
                existing_attack.properties_json = (
                    json.dumps(property_names) if property_names else None
                )
                existing_attack.is_imported = True
                is_new_attack = False
            else:
                new_attack = Attack(
                    character_id=character.id,
                    name=weapon_name,
                    hit_modifier=hit_modifier_result.total,
                    damage_formula=damage_dice,
                    damage_type=damage_type_name,
                    weapon_category=weapon_category,
                    two_handed_damage=two_handed_damage,
                    properties_json=(
                        json.dumps(property_names) if property_names else None
                    ),
                    is_imported=True,
                )
                db.add(new_attack)
                is_new_attack = True

            db.commit()

            header = (
                Strings.WEAPON_ADD_SUCCESS_HEADER
                if is_new_attack
                else Strings.WEAPON_ADD_UPDATED_HEADER
            ).format(name=weapon_name, char_name=character.name)

            hit_line = Strings.WEAPON_ADD_HIT_LINE.format(
                hit_modifier=hit_modifier_result.total,
                breakdown=hit_modifier_result.breakdown,
            )

            versatile_suffix = (
                Strings.WEAPON_ADD_VERSATILE_SUFFIX.format(
                    two_handed_damage=two_handed_damage
                )
                if two_handed_damage
                else ""
            )
            damage_line = (
                Strings.WEAPON_ADD_DAMAGE_LINE.format(
                    damage_dice=damage_dice, damage_type=damage_type_name
                )
                + versatile_suffix
            )

            properties_line = ""
            if property_names:
                properties_line = "\n" + Strings.WEAPON_ADD_PROPERTIES_LINE.format(
                    properties=", ".join(property_names)
                )

            message = (
                f"{header}\n"
                f"{hit_line}\n"
                f"{damage_line}"
                f"{properties_line}"
                f"{Strings.WEAPON_ADD_FOOTER}"
            )

            await interaction.response.send_message(message)
            logger.info(
                f"/weapon add completed for user {interaction.user.id}: "
                f"{'added' if is_new_attack else 'updated'} "
                f"{weapon_name!r} on {character.name!r}"
            )
        finally:
            db.close()

    bot.tree.add_command(weapon_group)
