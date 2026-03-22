import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from database import SessionLocal
from dice_roller import (
    evaluate_expression,
    get_named_tokens,
    has_named_tokens,
    parse_expression_tokens,
    roll_dice,
)
from enums.death_save_nat20_mode import DeathSaveNat20Mode
from models import Character, PartySettings
from utils.constants import SKILL_TO_STAT, STAT_NAMES
from utils.db_helpers import get_active_character, get_or_create_user_server
from utils.death_save_logic import character_is_dying, process_death_save
from utils.dnd_logic import perform_roll
from utils.dev_notifications import notify_command_error
from utils.logging_config import get_logger
from utils.strings import Strings
import random
logger = get_logger(__name__)


_DEATH_SAVE_NOTATION = "death save"

_RECOGNIZED_NAMED_TOKENS: frozenset = frozenset(
    {s.lower() for s in SKILL_TO_STAT}
    | set(STAT_NAMES)
    | {"initiative", "init"}
)


def _needs_character(notation: str) -> bool:
    """Return True if the notation requires an active character to resolve."""
    clean = notation.lower().strip()

    if clean == _DEATH_SAVE_NOTATION:
        return True

    # Simple named checks (skill / save / stat / initiative)
    if clean in ("initiative", "init"):
        return True
    if "save" in clean:
        stat_part = clean.replace("save", "").replace("_", "").strip()
        if stat_part in STAT_NAMES:
            return True
    if next((s for s in SKILL_TO_STAT if s.lower() == clean), None):
        return True
    if clean in STAT_NAMES:
        return True

    # Complex expression: only recognized named tokens require a character.
    # Unrecognized tokens (e.g. "foobar") are invalid input, not missing-character.
    tokens = parse_expression_tokens(notation)
    named = get_named_tokens(tokens)
    return bool(named) and all(token in _RECOGNIZED_NAMED_TOKENS for token in named)


async def _notify_gmroll_gms(
    client: discord.Client,
    char: Character,
    gm_message: str,
) -> None:
    """DM each GM of every party the character belongs to.

    Each party-GM pairing generates one DM regardless of whether the same user
    is a GM in multiple parties — the GM sees every party context separately.
    All DM failures are caught, logged, and silently ignored so they never block
    the player's response or prevent other GMs from receiving their notification.

    Args:
        client: The Discord client used to fetch users.
        char: The active character whose party memberships determine recipients.
        gm_message: The text to send to each GM.
    """
    party_count = len(char.parties)
    logger.info(
        f"_notify_gmroll_gms: character '{char.name}' belongs to "
        f"{party_count} {'party' if party_count == 1 else 'parties'}"
    )
    for party in char.parties:
        gm_ids = [gm.discord_id for gm in party.gms]
        logger.info(
            f"_notify_gmroll_gms: party '{party.name}' has "
            f"{len(gm_ids)} GM(s): {gm_ids or '(none)'}"
        )
        for gm in party.gms:
            try:
                discord_user = await client.fetch_user(int(gm.discord_id))
                await discord_user.send(gm_message)
                logger.debug(
                    f"/gmroll DM sent to GM {gm.discord_id} "
                    f"(party '{party.name}', char '{char.name}')"
                )
            except Exception as exc:
                logger.warning(
                    f"Could not DM GM {gm.discord_id} for /gmroll "
                    f"(party '{party.name}'): {type(exc).__name__}: {exc}"
                )


def _get_nat20_mode(db, character: Character) -> DeathSaveNat20Mode:
    """Return the party's nat-20 death save mode, defaulting to REGAIN_HP."""
    for party in character.parties:
        settings = db.query(PartySettings).filter_by(party_id=party.id).first()
        if settings is not None:
            return settings.death_save_nat20_mode
    return DeathSaveNat20Mode.REGAIN_HP


async def _handle_death_save(
    interaction: discord.Interaction,
    character: Character,
    db,
) -> None:
    """Process a death saving throw for a dying character."""
    if not character_is_dying(character):
        await interaction.response.send_message(
            Strings.DEATH_SAVE_NOT_DYING.format(char_name=character.name),
            ephemeral=True,
        )
        return

    nat20_mode = _get_nat20_mode(db, character)
    _rolls, _modifier, roll = roll_dice("1d20")

    result = process_death_save(
        roll=roll,
        nat20_mode=nat20_mode,
        current_successes=character.death_save_successes,
        current_failures=character.death_save_failures,
    )

    # Persist updated state
    if result.is_nat20_heal:
        character.current_hp = 1
        character.death_save_successes = 0
        character.death_save_failures = 0
    else:
        character.death_save_successes = result.successes_after
        character.death_save_failures = result.failures_after

    db.commit()

    # Build response message
    lines: List[str] = []

    if result.roll == 1 and not result.is_nat20_heal:
        lines.append(Strings.DEATH_SAVE_NAT1_DOUBLE)
    elif result.roll == 20 and nat20_mode == DeathSaveNat20Mode.REGAIN_HP:
        lines.append(Strings.DEATH_SAVE_NAT20_HEAL.format(char_name=character.name))
    elif result.roll == 20 and nat20_mode == DeathSaveNat20Mode.DOUBLE_SUCCESS:
        lines.append(Strings.DEATH_SAVE_NAT20_DOUBLE)
    elif result.is_success:
        lines.append(
            Strings.DEATH_SAVE_RESULT_SUCCESS.format(
                roll=roll,
                successes=result.successes_after,
                failures=result.failures_after,
            )
        )
    else:
        lines.append(
            Strings.DEATH_SAVE_RESULT_FAILURE.format(
                roll=roll,
                successes=result.successes_after,
                failures=result.failures_after,
            )
        )

    if result.is_stabilized:
        lines.append(Strings.DEATH_SAVE_STABILIZED.format(char_name=character.name))
    elif result.is_slain:
        lines.append(Strings.DEATH_SAVE_SLAIN.format(char_name=character.name))

    await interaction.response.send_message("\n".join(lines))

    if result.is_slain:
        # Public announcement so the whole table sees it
        await interaction.followup.send(
            Strings.DEATH_SAVE_SLAIN.format(char_name=character.name)
        )

    logger.info(
        f"/roll death save for {character.name}: roll={roll} "
        f"success={result.is_success} failure={result.is_failure} "
        f"stabilized={result.is_stabilized} slain={result.is_slain}"
    )


def register_roll_commands(bot: commands.Bot) -> None:

    @bot.tree.command(name="gmroll", description="Roll dice privately to the GM(s).")
    @app_commands.describe(
        notation=(
            "Dice, skill, stat, or save(e.g. 'perception', 'str save', '1d20+5')"
        ),
        advantage="Roll with advantage or disadvantage",
    )
    @app_commands.choices(
        advantage=[
            app_commands.Choice(name="Advantage", value="advantage"),
            app_commands.Choice(name="Disadvantage", value="disadvantage"),
        ]
    )
    async def gmroll(
        interaction: discord.Interaction, notation: str, advantage: str = None
    ) -> None:
        """Roll dice privately — the player sees the result ephemerally and all
        GMs of every party the active character belongs to receive a DM.

        Pure dice notation (e.g. ``1d20``) does not require an active character
        for the roll itself, but the bot still looks up the active character
        afterwards so GMs can be notified if the character is in any parties.

        Selects a random tip and displays it along side the result message
        """
        logger.debug(
            f"Command /gmroll called by {interaction.user} (ID: {interaction.user.id}) "
            f"in guild {interaction.guild_id} — notation={notation!r} advantage={advantage}"
        )
        db = SessionLocal()
        try:
            char = None

            if _needs_character(notation):
                user, server = get_or_create_user_server(db, interaction)
                char = get_active_character(db, user, server)
                logger.debug(
                    f"Character lookup: {'found: ' + char.name if char else 'not found'}"
                )
                if not char:
                    await interaction.response.send_message(
                        Strings.CHARACTER_NOT_FOUND, ephemeral=True
                    )
                    return

                response = await perform_roll(char, notation, db, advantage=advantage)

            else:
                # Pure dice / number expression — no character required for the roll.
                tokens = parse_expression_tokens(notation)
                result = evaluate_expression(tokens, advantage=advantage)
                response = Strings.ROLL_RESULT_DICE_EXPR.format(
                    notation=notation,
                    breakdown=result.breakdown(),
                    total=result.total,
                    tip=random.choice(Strings.TIPS)
                )
                # Still attempt to resolve the active character so GMs can be
                # notified even when the notation itself didn't need one.
                try:
                    user, server = get_or_create_user_server(db, interaction)
                    char = get_active_character(db, user, server)
                    logger.info(
                        f"/gmroll pure-dice character lookup for user {interaction.user.id}: "
                        f"{'found: ' + char.name if char else 'not found — no GM notifications will be sent'}"
                    )
                except Exception as exc:
                    logger.warning(
                        f"/gmroll pure-dice character lookup failed "
                        f"({type(exc).__name__}: {exc}) — no GM notifications will be sent"
                    )
                    char = None

            # Player always gets an ephemeral response.
            await interaction.response.send_message(response, ephemeral=True)
            logger.info(f"/gmroll completed for user {interaction.user.id}")

            # DM every GM across all parties the character belongs to.
            if not char:
                logger.info(
                    f"/gmroll: no active character for user {interaction.user.id} "
                    f"— skipping GM notifications"
                )
            elif not char.parties:
                logger.info(
                    f"/gmroll: character '{char.name}' has no party memberships "
                    f"— skipping GM notifications"
                )
            else:
                gm_message = Strings.GMROLL_GM_MESSAGE.format(
                    char_name=char.name,
                    notation=notation,
                    result=response,
                    tip=random.choice(Strings.TIPS),
                )
                await _notify_gmroll_gms(interaction.client, char, gm_message)

        except ValueError as exc:
            logger.warning(f"ValueError in /gmroll (notation={notation!r}): {exc}")
            await interaction.response.send_message(f"❌ Error: {exc}", ephemeral=True)
        except Exception as exc:
            logger.error(
                f"Unexpected error in /gmroll (notation={notation!r}): {exc}",
                exc_info=True,
            )
            await notify_command_error(interaction, exc)
        finally:
            db.close()
    @bot.tree.command(
        name="roll",
        description="Roll dice, a skill check, a save, or a complex expression.",
    )
    @app_commands.describe(
        notation=(
            "Dice, skill, stat, or save(e.g. 'perception', 'str save', '1d20+5')"
        ),
        advantage="Roll with advantage or disadvantage",
    )
    @app_commands.choices(
        advantage=[
            app_commands.Choice(name="Advantage", value="advantage"),
            app_commands.Choice(name="Disadvantage", value="disadvantage"),
        ]
    )
    async def roll(
        interaction: discord.Interaction,
        notation: str,
        advantage: str = None,
    ) -> None:

        """"
        Rolls dice, a skill check, a save, or a complex expression.
        Outputs result to the channel.
        Selects a random tip and displays it along side the result message
        """

        logger.debug(
            f"Command /roll called by {interaction.user} (ID: {interaction.user.id}) "
            f"in guild {interaction.guild_id} — notation={notation!r} advantage={advantage}"
        )
        db = SessionLocal()
        try:
            if _needs_character(notation):
                user, server = get_or_create_user_server(db, interaction)
                char = get_active_character(db, user, server)
                logger.debug(
                    f"Character lookup: {'found: ' + char.name if char else 'not found'}"
                )
                if not char:
                    await interaction.response.send_message(
                        Strings.CHARACTER_NOT_FOUND, ephemeral=True
                    )
                    return

                if notation.lower().strip() == _DEATH_SAVE_NOTATION:
                    await _handle_death_save(interaction, char, db)
                    return

                response = await perform_roll(char, notation, db, advantage=advantage)
                await interaction.response.send_message(response)
                logger.info(
                    f"/roll (character) completed for user {interaction.user.id}"
                )

            else:
                # Pure dice / number expression — no character needed
                tokens = parse_expression_tokens(notation)
                result = evaluate_expression(tokens, advantage=advantage)
                response = Strings.ROLL_RESULT_DICE_EXPR.format(
                    notation=notation,
                    breakdown=result.breakdown(),
                    total=result.total,
                    tip=random.choice(Strings.TIPS),
                )
                await interaction.response.send_message(response)
                logger.info(f"/roll (dice) completed for user {interaction.user.id}")

        except ValueError as e:
            logger.warning(f"ValueError in /roll (notation={notation!r}): {e}")
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
        except Exception as e:
            logger.error(
                f"Unexpected error in /roll (notation={notation!r}): {e}", exc_info=True
            )
            await notify_command_error(interaction, e)
        finally:
            db.close()

    @roll.autocomplete("notation")
    async def roll_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        suggestions = []
        skills = sorted(SKILL_TO_STAT.keys())
        suggestions.extend(skills)
        suggestions.append("Initiative")
        stats = [
            "Strength",
            "Dexterity",
            "Constitution",
            "Intelligence",
            "Wisdom",
            "Charisma",
        ]
        suggestions.extend(stats)
        suggestions.extend(["Str", "Dex", "Con", "Int", "Wis", "Cha"])
        for stat in stats:
            suggestions.append(f"{stat} Save")
        for stat in ["Str", "Dex", "Con", "Int", "Wis", "Cha"]:
            suggestions.append(f"{stat} Save")

        # Include "death save" only when the active character is at 0 HP
        death_save_db = SessionLocal()
        try:
            user, server = get_or_create_user_server(death_save_db, interaction)
            if user and server:
                char = get_active_character(death_save_db, user, server)
                if char and character_is_dying(char):
                    suggestions.insert(0, "death save")
        finally:
            death_save_db.close()

        filtered = [
            app_commands.Choice(name=s, value=s)
            for s in suggestions
            if current.lower() in s.lower()
        ]
        filtered.sort(
            key=lambda c: (not c.name.lower().startswith(current.lower()), c.name)
        )
        return filtered[:25]
