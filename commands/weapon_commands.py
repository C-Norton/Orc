"""Commands for searching and importing weapons from the Open5e API.

Workflow::

    /weapon search <query> [ruleset]  — search the Open5e v2 SRD, display
                                        results with one Add button per weapon
    (click button)                    — imports the weapon to the active character

Results are displayed in an ephemeral message with interactive buttons.  Each
button lives for ``WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS`` seconds (5 minutes);
after that discord.py disables the view and the weapon data is garbage-collected.
No manual session dict is required — the ``WeaponSearchView`` owns the data
for its lifetime and is cleaned up automatically on timeout.
"""

from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands

from database import SessionLocal
from enums.ruleset_edition import RulesetEdition
from models import Attack, Character
from utils.db_helpers import get_active_character, get_or_create_user_server
from utils.limits import MAX_ATTACKS_PER_CHARACTER
from utils.dev_notifications import notify_command_error
from utils.logging_config import get_logger
from utils.strings import Strings
from utils.weapon_utils import (
    WeaponHitModifier,
    calculate_weapon_hit_modifier,
    extract_two_handed_damage,
    fetch_weapons,
    format_weapon_result_line,
    get_property_names,
)

logger = get_logger(__name__)

WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS: int = 300


# ---------------------------------------------------------------------------
# Weapon import helpers
# ---------------------------------------------------------------------------


def _import_weapon_to_character(
    weapon_data: dict, character: "Character", db
) -> tuple[bool, WeaponHitModifier]:
    """Insert or update an Attack record for *weapon_data* on *character*.

    Returns ``(is_new, hit_modifier_result)`` where ``is_new`` is ``True``
    when a new Attack was created and ``False`` when an existing one was
    updated.  The caller is responsible for calling ``db.commit()``.
    """
    weapon_name = weapon_data.get("name", "Unknown")
    damage_dice = weapon_data.get("damage_dice", "1d4")
    damage_type_object = weapon_data.get("damage_type") or {}
    damage_type_name = damage_type_object.get("name", "")
    is_simple = weapon_data.get("is_simple", True)
    weapon_category = "Simple" if is_simple else "Martial"
    range_normal_float = weapon_data.get("range", 0) or 0
    properties = weapon_data.get("properties", [])
    property_names = get_property_names(properties)
    two_handed_damage = extract_two_handed_damage(properties)
    properties_json = json.dumps(property_names) if property_names else None

    hit_modifier_result = calculate_weapon_hit_modifier(
        character, properties, range_normal_float
    )

    existing_attack = (
        db.query(Attack).filter_by(character_id=character.id, name=weapon_name).first()
    )

    if existing_attack:
        existing_attack.hit_modifier = hit_modifier_result.total
        existing_attack.damage_formula = damage_dice
        existing_attack.damage_type = damage_type_name
        existing_attack.weapon_category = weapon_category
        existing_attack.two_handed_damage = two_handed_damage
        existing_attack.properties_json = properties_json
        existing_attack.is_imported = True
        return False, hit_modifier_result

    db.add(
        Attack(
            character_id=character.id,
            name=weapon_name,
            hit_modifier=hit_modifier_result.total,
            damage_formula=damage_dice,
            damage_type=damage_type_name,
            weapon_category=weapon_category,
            two_handed_damage=two_handed_damage,
            properties_json=properties_json,
            is_imported=True,
        )
    )
    return True, hit_modifier_result


def _build_weapon_add_message(
    weapon_data: dict,
    character: "Character",
    is_new: bool,
    hit_modifier_result: WeaponHitModifier,
) -> str:
    """Build the public confirmation message shown after a weapon is added."""
    weapon_name = weapon_data.get("name", "Unknown")
    damage_dice = weapon_data.get("damage_dice", "1d4")
    damage_type_object = weapon_data.get("damage_type") or {}
    damage_type_name = damage_type_object.get("name", "")
    properties = weapon_data.get("properties", [])
    property_names = get_property_names(properties)
    two_handed_damage = extract_two_handed_damage(properties)

    header = (
        Strings.WEAPON_ADD_SUCCESS_HEADER if is_new else Strings.WEAPON_ADD_UPDATED_HEADER
    ).format(name=weapon_name, char_name=character.name)

    hit_line = Strings.WEAPON_ADD_HIT_LINE.format(
        hit_modifier=hit_modifier_result.total,
        breakdown=hit_modifier_result.breakdown,
    )

    versatile_suffix = (
        Strings.WEAPON_ADD_VERSATILE_SUFFIX.format(two_handed_damage=two_handed_damage)
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

    return f"{header}\n{hit_line}\n{damage_line}{properties_line}{Strings.WEAPON_ADD_FOOTER}"


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------


class WeaponAddButton(discord.ui.Button):
    """A button that imports a single weapon into the user's active character.

    One button is created per weapon result in :class:`WeaponSearchView`.  The
    weapon data is stored on the button and requires no further API call when
    clicked.
    """

    def __init__(self, weapon: dict) -> None:
        super().__init__(
            label=weapon.get("name", "Unknown"),
            style=discord.ButtonStyle.primary,
        )
        self.weapon = weapon

    async def callback(self, interaction: discord.Interaction) -> None:
        """Import the weapon to the active character and confirm publicly."""
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            character = get_active_character(db, user, server)
            if not character:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            weapon_name = self.weapon.get("name", "Unknown")
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

            is_new, hit_modifier_result = _import_weapon_to_character(
                self.weapon, character, db
            )
            db.commit()
            confirmation = _build_weapon_add_message(
                self.weapon, character, is_new, hit_modifier_result
            )
        except Exception as error:
            logger.error(
                f"WeaponAddButton error for {self.weapon.get('name')!r}: {error}"
            )
            await notify_command_error(interaction, error)
            return
        finally:
            db.close()

        self.disabled = True
        self.style = discord.ButtonStyle.success
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send(confirmation)
        logger.info(
            f"WeaponAddButton: {'added' if is_new else 'updated'} "
            f"{weapon_name!r} for user {interaction.user.id}"
        )


class WeaponSearchView(discord.ui.View):
    """Displays weapon search results as a row of clickable Add buttons.

    The view holds the weapon data directly; no external session dict is used.
    ``discord.py`` stores a strong reference to the view in its internal view
    store until the view times out or is stopped, after which the object is
    eligible for garbage collection along with all weapon data it holds.

    On timeout, all buttons are disabled and the search message is edited so
    the user knows the results have expired.
    """

    def __init__(self, weapon_list: list[dict]) -> None:
        super().__init__(timeout=WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS)
        self.message: discord.Message | None = None
        for weapon in weapon_list:
            self.add_item(WeaponAddButton(weapon))

    async def on_timeout(self) -> None:
        """Disable all buttons and update the message to show expiry."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


_RULESET_CHOICE_MAP = {
    "2024": RulesetEdition.RULES_2024,
    "2014": RulesetEdition.RULES_2014,
}


def register_weapon_commands(bot: commands.Bot) -> None:
    """Register the ``/weapon search`` command."""
    weapon_group = app_commands.Group(
        name="weapon",
        description="Search for and import weapons from the SRD",
    )

    @weapon_group.command(
        name="search", description="Search for weapons in the SRD (default: 2024 rules)"
    )
    @app_commands.describe(
        query="Weapon name to search for (e.g., longsword, shortbow)",
        ruleset="Which ruleset edition to search (default: 2024)",
    )
    @app_commands.choices(
        ruleset=[
            app_commands.Choice(name="2024 (default)", value="2024"),
            app_commands.Choice(name="2014", value="2014"),
        ]
    )
    async def weapon_search(
        interaction: discord.Interaction,
        query: str,
        ruleset: str = "2024",
    ) -> None:
        """Search Open5e for weapons and display results as Add buttons.

        Each result gets its own button.  Clicking a button imports that weapon
        directly to the active character — no follow-up command required.
        Buttons expire after 5 minutes and are then disabled automatically.
        """
        ruleset_edition = _RULESET_CHOICE_MAP.get(ruleset, RulesetEdition.RULES_2024)
        logger.debug(
            f"Command /weapon search called by {interaction.user} "
            f"(ID: {interaction.user.id}) for guild {interaction.guild_id} "
            f"with query: {query!r}, ruleset: {ruleset_edition.value!r}"
        )
        await interaction.response.defer(ephemeral=True)
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            character = get_active_character(db, user, server)
            if not character:
                await interaction.followup.send(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            try:
                weapon_list = await fetch_weapons(query, ruleset_edition)
            except Exception as api_error:
                logger.error(
                    f"/weapon search API error for query {query!r}: {api_error}"
                )
                await notify_command_error(interaction, api_error)
                return

            if not weapon_list:
                await interaction.followup.send(
                    Strings.WEAPON_SEARCH_NO_RESULTS.format(
                        query=query, ruleset=ruleset_edition.display_year
                    ),
                    ephemeral=True,
                )
                return

            result_lines = [
                format_weapon_result_line(index + 1, weapon)
                for index, weapon in enumerate(weapon_list)
            ]
            results_block = "\n".join(result_lines)
            message_text = (
                Strings.WEAPON_SEARCH_HEADER.format(
                    query=query, ruleset=ruleset_edition.display_year
                )
                + "\n"
                + results_block
                + Strings.WEAPON_SEARCH_FOOTER.format(char_name=character.name)
            )

            view = WeaponSearchView(weapon_list)
            sent_message = await interaction.followup.send(
                message_text, view=view, ephemeral=True
            )
            # Store the message reference so on_timeout can disable the buttons.
            view.message = sent_message

            logger.info(
                f"/weapon search completed for user {interaction.user.id}: "
                f"{len(weapon_list)} result(s) for {query!r} "
                f"in {ruleset_edition.value!r}"
            )
        finally:
            db.close()

    bot.tree.add_command(weapon_group)
