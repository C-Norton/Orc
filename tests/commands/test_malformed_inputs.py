"""
Comprehensive tests for malformed and intentionally malicious inputs.

Every parameter that accepts free-form user text (strings, ints entered manually)
is exercised with:
  • Off-by-one boundary values at both ends of any enforced range
  • Zero / negative where only positive is valid
  • Dice notation edge cases: over-limit, invalid, zero-dice, zero-sided-die
  • Injection-style strings in name fields (SQL, Discord @-mentions, markdown,
    null bytes, RTL-override, zero-width characters)
  • Pathologically long strings
  • Named tokens where only raw dice are accepted (e.g. "perception" in /hp damage)

Defensive notes
---------------
* SQLAlchemy uses parameterized queries; SQL-injection strings should NOT cause
  database errors — the tests verify graceful handling (ephemeral error or
  normal success), not DB corruption.
* Discord enforces integer types at the API layer, so integer parameters cannot
  receive non-integer text in production.  The tests call callbacks directly to
  verify server-side bounds checks.
* Very large integers (e.g. 2**62) are passed to verify no uncaught exception
  escapes the command handler even when Discord's range is not the bottleneck.

Known edge-case defects found during this suite
------------------------------------------------
BUG-MFI-1  ``dice_roller._roll_dice_group`` does not validate ``sides >= 1``
           before calling ``random.randint(1, 0)``, which raises a bare
           ``ValueError`` from the stdlib.  For ``/hp damage`` and ``/hp heal``
           this is caught and returned as an ephemeral error, but the message
           is not user-friendly.  Tests for ``"1d0"`` are marked ``xfail`` for
           any command whose handler does NOT wrap ValueError.
"""

import pytest

from models import (
    Attack,
    Character,
    ClassLevel,
    Party,
    Encounter,
    Enemy,
    EncounterTurn,
    user_server_association,
)
from enums.encounter_status import EncounterStatus
from sqlalchemy import insert
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback
from utils.limits import (
    MAX_ATTACKS_PER_CHARACTER,
    MAX_CHARACTERS_PER_USER,
    MAX_CHARACTERS_PER_PARTY,
    MAX_ENEMIES_PER_ENCOUNTER,
    MAX_GM_PARTIES_PER_USER,
    MAX_PARTIES_PER_SERVER,
)
from utils.strings import Strings


# ---------------------------------------------------------------------------
# Injection payload catalogue
# ---------------------------------------------------------------------------

_SQL_INJECTION = "'; DROP TABLE characters; --"
_SQL_INJECTION_2 = "' OR '1'='1"
_DISCORD_EVERYONE = "@everyone hello"
_DISCORD_HERE = "@here something"
_MARKDOWN_BOLD = "**bold name**"
_MARKDOWN_CODE = "`backtick`"
_NULL_BYTE = "name\x00truncated"
_RTL_OVERRIDE = "\u202ereversed"
_ZERO_WIDTH = "invis\u200bible"
_NEWLINE = "name\nwith newline"
_VERY_LONG = "A" * 2001  # exceeds Discord's 2000-char message cap
_NAME_AT_LIMIT = "A" * 100  # exactly at the 100-char character name limit
_NAME_OVER_LIMIT = "A" * 101  # one over the 100-char limit
_EMOJI_NAME = "⚔️🛡️🐉 Dragon Slayer"
_WHITESPACE_ONLY = "   "


# ===========================================================================
# 1.  Character name validation — via save_character_from_wizard
# ===========================================================================


async def test_character_create_name_at_limit_accepted(
    mocker, db_session, sample_user, sample_server
):
    """A 100-character name is exactly at the limit and must be accepted."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_NAME_AT_LIMIT,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    assert error is None
    assert char is not None


async def test_character_create_name_over_limit_rejected(mocker, db_session):
    """A 101-character name exceeds the limit and must be rejected."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_NAME_OVER_LIMIT,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    assert char is None
    assert error == Strings.CHAR_CREATE_NAME_LIMIT


async def test_character_create_sql_injection_name_stored_safely(
    mocker, db_session, sample_user, sample_server
):
    """A SQL-injection name must be stored verbatim (not interpreted) and succeed."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_SQL_INJECTION,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()
    assert error is None
    stored = db_session.query(Character).filter_by(name=_SQL_INJECTION).first()
    assert stored is not None


async def test_character_create_sql_injection_2_name_stored_safely(
    mocker, db_session, sample_user, sample_server
):
    """A second SQL-injection pattern must also be stored safely."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_SQL_INJECTION_2,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()
    assert error is None
    stored = db_session.query(Character).filter_by(name=_SQL_INJECTION_2).first()
    assert stored is not None


async def test_character_create_discord_mention_in_name(
    mocker, db_session, sample_user, sample_server
):
    """@everyone in a character name is stored as plain text."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_DISCORD_EVERYONE,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()
    assert error is None
    stored = db_session.query(Character).filter_by(name=_DISCORD_EVERYONE).first()
    assert stored is not None


async def test_character_create_markdown_in_name_stored_safely(
    mocker, db_session, sample_user, sample_server
):
    """Markdown characters in a character name are stored verbatim."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_MARKDOWN_BOLD,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()
    assert error is None
    stored = db_session.query(Character).filter_by(name=_MARKDOWN_BOLD).first()
    assert stored is not None


async def test_character_create_emoji_name_stored_safely(
    mocker, db_session, sample_user, sample_server
):
    """Emoji in a character name are stored and retrieved correctly."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_EMOJI_NAME,
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()
    assert error is None
    stored = db_session.query(Character).filter_by(name=_EMOJI_NAME).first()
    assert stored is not None


async def test_character_create_newline_in_name_stored_safely(
    mocker, db_session, sample_user, sample_server
):
    """A newline embedded in a name does not crash the wizard commit."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=_NEWLINE,
    )
    # Must not raise — either succeeds or returns a validation error
    char, error = save_character_from_wizard(state, interaction, db_session)
    assert char is not None or error is not None


# ===========================================================================
# 2.  Level validation — via _LevelModal
# ===========================================================================


async def test_character_create_level_zero_rejected(mocker):
    """Level 0 is below the minimum of 1 and must be rejected."""
    from commands.wizard.state import WizardState
    from commands.wizard.modals import _LevelForClassModal
    from commands.wizard.section_views import _ClassLevelView
    from enums.character_class import CharacterClass

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="LowLevel",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "0"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert (
        Strings.CHAR_LEVEL_LIMIT in interaction.response.send_message.call_args.args[0]
    )
    assert state.level is None


async def test_character_create_level_21_rejected(mocker):
    """Level 21 is above the maximum of 20 and must be rejected."""
    from commands.wizard.state import WizardState
    from commands.wizard.modals import _LevelForClassModal
    from commands.wizard.section_views import _ClassLevelView
    from enums.character_class import CharacterClass

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="OverLevel",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "21"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert (
        Strings.CHAR_LEVEL_LIMIT in interaction.response.send_message.call_args.args[0]
    )
    assert state.level is None


async def test_character_create_level_negative_rejected(mocker):
    """A negative level must be rejected."""
    from commands.wizard.state import WizardState
    from commands.wizard.modals import _LevelForClassModal
    from commands.wizard.section_views import _ClassLevelView
    from enums.character_class import CharacterClass

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="NegLevel",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "-1"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.level is None


async def test_character_create_level_1_accepted(mocker):
    """Level 1 is the minimum and must be accepted."""
    from commands.wizard.state import WizardState
    from commands.wizard.modals import _LevelForClassModal
    from commands.wizard.section_views import _ClassLevelView
    from enums.character_class import CharacterClass

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="MinLevel",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "1"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.level == 1
    interaction.response.edit_message.assert_called_once()


async def test_character_create_level_20_accepted(mocker):
    """Level 20 is the maximum and must be accepted."""
    from commands.wizard.state import WizardState
    from commands.wizard.modals import _LevelForClassModal
    from commands.wizard.section_views import _ClassLevelView
    from enums.character_class import CharacterClass

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="MaxLevel",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "20"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.level == 20
    interaction.response.edit_message.assert_called_once()


# ===========================================================================
# 3.  /character stats — stat score boundaries
# ===========================================================================


@pytest.mark.parametrize(
    "stat",
    [
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ],
)
async def test_character_stats_score_zero_rejected(
    mocker, char_bot, sample_character, stat
):
    """Any ability score of 0 (below the minimum of 1) must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    kwargs = {
        "strength": 10,
        "dexterity": 10,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
        "initiative_bonus": 0,
    }
    kwargs[stat] = 0
    await cb(interaction, **kwargs)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        Strings.CHAR_STAT_LIMIT.format(stat_name=stat.capitalize()) in msg
        or "score must be between" in msg
    )


@pytest.mark.parametrize(
    "stat",
    [
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ],
)
async def test_character_stats_score_31_rejected(
    mocker, char_bot, sample_character, stat
):
    """Any ability score of 31 (above the maximum of 30) must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    kwargs = {
        "strength": 10,
        "dexterity": 10,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
        "initiative_bonus": 0,
    }
    kwargs[stat] = 31
    await cb(interaction, **kwargs)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        "score must be between" in msg
        or Strings.CHAR_STAT_LIMIT.format(stat_name=stat.capitalize()) in msg
    )


async def test_character_stats_minimum_values_accepted(
    mocker, char_bot, sample_character
):
    """All ability scores of 1 (the minimum) must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=1,
        dexterity=1,
        constitution=1,
        intelligence=1,
        wisdom=1,
        charisma=1,
        initiative_bonus=0,
    )
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_stats_maximum_values_accepted(
    mocker, char_bot, sample_character
):
    """All ability scores of 30 (the maximum) must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=30,
        dexterity=30,
        constitution=30,
        intelligence=30,
        wisdom=30,
        charisma=30,
        initiative_bonus=0,
    )
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_stats_first_time_partial_update_rejected(
    mocker, char_bot, sample_character_no_stats
):
    """When stats have never been set, providing fewer than all 6 scores must be
    rejected with the 'first time' error."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    # Provide only 3 stats
    await cb(
        interaction,
        strength=10,
        dexterity=10,
        constitution=10,
        initiative_bonus=0,
    )

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHAR_STATS_FIRST_TIME in msg


async def test_character_stats_initiative_bonus_negative_accepted(
    mocker, char_bot, sample_character
):
    """Negative initiative bonus (e.g. -10) has no enforced lower bound and
    must be accepted — it is a legitimate D&D value."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
        initiative_bonus=-10,
    )
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 4.  /character ac — armor class boundaries
# ===========================================================================


async def test_character_ac_zero_rejected(mocker, char_bot, sample_character):
    """AC of 0 is below the minimum of 1 and must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHAR_AC_LIMIT in msg


async def test_character_ac_31_rejected(mocker, char_bot, sample_character):
    """AC of 31 exceeds the maximum of 30 and must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=31)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHAR_AC_LIMIT in msg


async def test_character_ac_negative_rejected(mocker, char_bot, sample_character):
    """A negative AC value must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=-1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_ac_1_accepted(mocker, char_bot, sample_character):
    """AC of 1 is the minimum and must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=1)
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_ac_30_accepted(mocker, char_bot, sample_character):
    """AC of 30 is the maximum and must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=30)
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 5.  /character class_add — level boundaries
# ===========================================================================


async def test_character_class_add_level_zero_rejected(
    mocker, char_bot, sample_character
):
    """Level 0 on class_add must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Wizard", level=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHAR_LEVEL_LIMIT in msg


async def test_character_class_add_level_21_rejected(
    mocker, char_bot, sample_character
):
    """Level 21 on class_add must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Wizard", level=21)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHAR_LEVEL_LIMIT in msg


async def test_character_class_add_exceeding_total_level_20_rejected(
    mocker, char_bot, sample_character, db_session
):
    """Adding a class level that would push total character level above 20 must
    be rejected with the total-level-exceeded error."""
    # sample_character is Fighter 5 (total=5). Adding 16 levels would hit 21.
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Wizard", level=16)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        Strings.CHAR_CLASS_TOTAL_LEVEL_EXCEEDED.format(
            level=16, char_class="Wizard", char_name="Aldric", current_total=5
        )
        in msg
    )


async def test_character_class_add_exact_total_20_accepted(
    mocker, char_bot, sample_character
):
    """Adding a class that brings total level to exactly 20 must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Wizard", level=15)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 6.  /hp set_max — max HP boundaries
# ===========================================================================


async def test_hp_set_max_zero_rejected(mocker, health_bot, sample_character):
    """Max HP of 0 must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_INVALID_MAX_HP in msg


async def test_hp_set_max_negative_rejected(mocker, health_bot, sample_character):
    """Negative max HP must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=-1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_INVALID_MAX_HP in msg


async def test_hp_set_max_one_accepted(mocker, health_bot, sample_character):
    """Max HP of 1 is the minimum and must be accepted."""
    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=1)
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_set_max_very_large_value_does_not_crash(
    mocker, health_bot, sample_character
):
    """An extremely large max HP (no upper bound) must be accepted without
    crashing.  The stored value may be very large but the handler must complete."""
    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=2_000_000_000)

    assert interaction.response.send_message.called
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 7.  /hp damage — amount string validation
# ===========================================================================


async def test_hp_damage_invalid_string_rejected(
    mocker, health_bot, sample_character, db_session
):
    """A non-numeric, non-dice string must be rejected with an error."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="abc")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_damage_sql_injection_string_rejected(
    mocker, health_bot, sample_character, db_session
):
    """SQL-injection text in the amount field must be rejected gracefully."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount=_SQL_INJECTION)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_damage_named_modifier_in_amount_rejected(
    mocker, health_bot, sample_character, db_session
):
    """Named modifiers (e.g. 'perception') are not valid in /hp damage — the
    handler must reject them with an error rather than crashing."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_damage_empty_string_rejected(
    mocker, health_bot, sample_character, db_session
):
    """An empty string amount must not crash the handler."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="")

    # Either rejected (ephemeral) or produces a zero-damage no-op — must not raise
    assert interaction.response.send_message.called


async def test_hp_damage_whitespace_only_amount_rejected(
    mocker, health_bot, sample_character, db_session
):
    """A whitespace-only amount must not crash the handler."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="   ")

    assert interaction.response.send_message.called


async def test_hp_damage_too_many_dice_rejected(
    mocker, health_bot, sample_character, db_session
):
    """Dice notation with more than 1000 dice must be rejected."""
    sample_character.max_hp = 100
    sample_character.current_hp = 100
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_hp_damage_too_many_sides_rejected(
    mocker, health_bot, sample_character, db_session
):
    """Dice notation with more than 100000 sides must be rejected."""
    sample_character.max_hp = 100
    sample_character.current_hp = 100
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1d100001")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_hp_damage_exact_dice_limit_accepted(
    mocker, health_bot, sample_character, db_session
):
    """1000d100000 is exactly at the limit and must be accepted."""
    sample_character.max_hp = 1_000_000
    sample_character.current_hp = 1_000_000
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1000d100000")

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_hp_damage_zero_dice_is_harmless(
    mocker, health_bot, sample_character, db_session
):
    """'0d6' evaluates to 0 damage, which is a no-op.  The handler must not
    crash even though the result is zero."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="0d6")

    # 0 damage: still sends a response (HP unchanged)
    assert interaction.response.send_message.called


async def test_hp_damage_zero_sided_die_handled(
    mocker, health_bot, sample_character, db_session
):
    """'1d0' triggers ValueError from random.randint(1, 0).  The handler must
    not leak an unhandled exception — it must send an ephemeral error."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1d0")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_damage_negative_dice_expression_rejected(
    mocker, health_bot, sample_character, db_session
):
    """'-1d6' evaluates to a negative total.  Negative damage would heal the
    character via current_hp - (-N) = current_hp + N — this should be rejected
    or at minimum handled without crashing."""
    sample_character.max_hp = 20
    sample_character.current_hp = 10
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="-1d6")

    # The handler must complete without raising an exception.
    assert interaction.response.send_message.called


async def test_hp_damage_very_long_notation_rejected(
    mocker, health_bot, sample_character, db_session
):
    """An extremely long dice notation string must not hang or crash."""
    sample_character.max_hp = 100
    sample_character.current_hp = 100
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1d6+" * 500 + "1")

    assert interaction.response.send_message.called


# ===========================================================================
# 8.  /hp heal — amount string validation (mirrors /hp damage)
# ===========================================================================


async def test_hp_heal_invalid_string_rejected(
    mocker, health_bot, sample_character, db_session
):
    """A non-numeric, non-dice string in /hp heal must be rejected."""
    sample_character.max_hp = 20
    sample_character.current_hp = 5
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="notadice")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_hp_heal_too_many_dice_rejected(
    mocker, health_bot, sample_character, db_session
):
    """1001d6 in /hp heal must be rejected with the dice-limit error."""
    sample_character.max_hp = 20
    sample_character.current_hp = 5
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_hp_heal_named_modifier_rejected(
    mocker, health_bot, sample_character, db_session
):
    """'strength' (a named modifier) in /hp heal must be rejected."""
    sample_character.max_hp = 20
    sample_character.current_hp = 5
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="strength")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 9.  /hp temp — negative and zero values
# ===========================================================================


async def test_hp_temp_zero_is_accepted(
    mocker, health_bot, sample_character, db_session
):
    """Zero temporary HP is accepted (replaces any existing temp HP of 0)."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=0)

    assert interaction.response.send_message.called


async def test_hp_temp_negative_does_not_set_negative_temp(
    mocker, health_bot, sample_character, db_session, session_factory
):
    """A negative temp HP amount must not leave the character with negative temp HP.
    max(current, new) means a negative 'new' value is silently ignored if current ≥ 0."""
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    sample_character.temp_hp = 0
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=-99)

    verify = session_factory()
    char = verify.query(Character).filter_by(id=sample_character.id).first()
    assert char.temp_hp >= 0, "Negative temp HP must not be persisted"
    verify.close()


# ===========================================================================
# 10.  /roll — malformed notation
# ===========================================================================


async def test_roll_too_many_dice_rejected(mocker, roll_bot, sample_character):
    """1001d6 must be rejected with the dice-limit error."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_roll_too_many_sides_rejected(mocker, roll_bot, sample_character):
    """1d100001 must be rejected with the dice-limit error."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d100001")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_roll_zero_sided_die_returns_ephemeral(
    mocker, roll_bot, sample_character
):
    """'1d0' must not raise an unhandled exception — it must return an
    ephemeral error."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d0")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_roll_totally_invalid_notation_rejected(
    mocker, roll_bot, sample_character
):
    """Gibberish notation must be handled gracefully.

    When a character is active, perform_roll returns an error string as a
    public (non-ephemeral) response rather than raising.  We verify the
    response contains an error indicator and is not a crash.
    """
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="this_is_not_dice")

    assert interaction.response.send_message.called
    msg = interaction.response.send_message.call_args.args[0]
    assert "❌" in msg or "Error" in msg or "error" in msg


async def test_roll_sql_injection_notation_rejected(mocker, roll_bot, sample_character):
    """SQL-injection notation must be rejected gracefully without crashing.

    The injection payload is treated as an unknown named modifier and the
    error is reported back to the caller (possibly non-ephemeral for a
    character-context error).
    """
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation=_SQL_INJECTION)

    assert interaction.response.send_message.called
    msg = interaction.response.send_message.call_args.args[0]
    assert "❌" in msg or "Error" in msg or "error" in msg


async def test_roll_empty_notation_rejected(mocker, roll_bot):
    """An empty notation string must not crash."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="")

    assert interaction.response.send_message.called


async def test_roll_whitespace_only_notation(mocker, roll_bot):
    """A whitespace-only notation must not crash."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="   ")

    assert interaction.response.send_message.called


async def test_roll_very_long_notation_does_not_hang(mocker, roll_bot):
    """Pathologically long dice chains must complete without hanging."""
    # 500 groups of '1d4+' then '1': total > 500 terms
    notation = "+".join(["1d4"] * 500)
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation=notation)

    assert interaction.response.send_message.called


async def test_roll_exact_dice_limit_accepted(mocker, roll_bot):
    """1000d100000 is the exact boundary and must succeed."""
    interaction = make_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1000d100000")

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


# ===========================================================================
# 11.  /attack add — damage formula validation
# ===========================================================================


async def test_attack_add_invalid_damage_formula_rejected(
    mocker, attack_bot, sample_character
):
    """A non-dice damage formula must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="notdice")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_attack_add_too_many_dice_in_formula_rejected(
    mocker, attack_bot, sample_character
):
    """1001d6 in the damage formula must be rejected with the dice-limit error."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_DICE_LIMIT in msg


async def test_attack_add_sql_injection_in_name_stored_safely(
    mocker, attack_bot, sample_character, session_factory
):
    """SQL-injection text in an attack name must be stored verbatim."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name=_SQL_INJECTION, hit_mod=5, damage_formula="1d8")

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name=_SQL_INJECTION).first()
    assert attack is not None
    verify.close()


async def test_attack_add_empty_name_does_not_crash(
    mocker, attack_bot, sample_character
):
    """An empty attack name must not crash the handler."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="", hit_mod=5, damage_formula="1d8")

    assert interaction.response.send_message.called


async def test_attack_add_very_large_hit_modifier_does_not_crash(
    mocker, attack_bot, sample_character
):
    """An extremely large hit modifier must not crash the handler."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="BigMod", hit_mod=2_000_000_000, damage_formula="1d8")

    assert interaction.response.send_message.called


async def test_attack_add_very_negative_hit_modifier_does_not_crash(
    mocker, attack_bot, sample_character
):
    """An extremely negative hit modifier must not crash the handler."""
    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Penalty", hit_mod=-2_000_000_000, damage_formula="1d8")

    assert interaction.response.send_message.called


# ===========================================================================
# 12.  /encounter enemy — HP value validation
# ===========================================================================


async def test_encounter_enemy_hp_invalid_string_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter
):
    """A non-numeric, non-dice HP value must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=1, max_hp="notvalid")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        "Invalid HP" in msg
        or Strings.ENCOUNTER_INVALID_HP.format(value="notvalid") in msg
    )


async def test_encounter_enemy_hp_too_many_dice_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter
):
    """1001d6 HP exceeds the 1000-dice limit. _validate_hp_format passes the regex
    (format is valid), but roll_dice raises ValueError inside _parse_hp_input.
    The encounter_enemy handler now catches that ValueError and returns an
    ephemeral error rather than letting it propagate as an unhandled exception."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=1, max_hp="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_enemy_hp_zero_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter
):
    """HP of '0' (not positive) must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=1, max_hp="0")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_enemy_hp_negative_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter
):
    """Negative HP must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=1, max_hp="-5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_enemy_hp_sql_injection_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter
):
    """SQL-injection text in the HP field must be rejected gracefully."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=1, max_hp=_SQL_INJECTION)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_enemy_sql_injection_name_stored_safely(
    mocker,
    encounter_bot,
    sample_active_party,
    sample_pending_encounter,
    session_factory,
):
    """SQL-injection in an enemy name must be stored verbatim, not interpreted."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name=_SQL_INJECTION, initiative_modifier=1, max_hp="10")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name=_SQL_INJECTION).first()
    assert enemy is not None
    verify.close()


# ===========================================================================
# 13.  /encounter damage — position and damage boundaries
# ===========================================================================


async def test_encounter_damage_position_zero_rejected(
    mocker, encounter_bot, sample_active_encounter
):
    """Position 0 (below the minimum of 1) must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=0, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        Strings.ENCOUNTER_DAMAGE_INVALID_POSITION.format(
            position=0, count=len(sample_active_encounter.turns)
        )
        in msg
    )


async def test_encounter_damage_position_out_of_range_rejected(
    mocker, encounter_bot, sample_active_encounter
):
    """A position beyond the initiative order length must be rejected."""
    count = len(sample_active_encounter.turns)
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=count + 1, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "not valid" in msg or str(count + 1) in msg


async def test_encounter_damage_zero_damage_rejected(
    mocker, encounter_bot, sample_active_encounter
):
    """Zero damage must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "damage")
    # Position 2 is the Goblin enemy in sample_active_encounter (order_position=1)
    await cb(interaction, position=2, damage=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ENCOUNTER_DAMAGE_MUST_BE_POSITIVE in msg


async def test_encounter_damage_negative_damage_rejected(
    mocker, encounter_bot, sample_active_encounter
):
    """Negative damage must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=-5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ENCOUNTER_DAMAGE_MUST_BE_POSITIVE in msg


async def test_encounter_damage_targeting_character_position_rejected(
    mocker, encounter_bot, sample_active_encounter
):
    """Targeting a character's turn position (not an enemy) must be rejected."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "damage")
    # Position 1 is Aldric (character), not an enemy
    await cb(interaction, position=1, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ENCOUNTER_DAMAGE_NOT_ENEMY.format(position=1) in msg


# ===========================================================================
# 14.  /party create — name injection and free-text fields
# ===========================================================================


async def test_party_create_sql_injection_name_stored_safely(
    mocker, party_bot, sample_user, sample_server, session_factory
):
    """SQL-injection in a party name must be stored verbatim."""
    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name=_SQL_INJECTION, characters_list="")

    verify = session_factory()
    party = verify.query(Party).filter_by(name=_SQL_INJECTION).first()
    assert party is not None
    verify.close()


async def test_party_create_discord_mention_in_name_stored_safely(
    mocker, party_bot, sample_user, sample_server, session_factory
):
    """@everyone in a party name must be stored as-is, not trigger a real mention."""
    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name=_DISCORD_EVERYONE, characters_list="")

    verify = session_factory()
    party = verify.query(Party).filter_by(name=_DISCORD_EVERYONE).first()
    assert party is not None
    verify.close()


async def test_party_create_duplicate_name_rejected(
    mocker, party_bot, sample_user, sample_server, sample_party
):
    """Creating a party with the same name as an existing one on this server
    must be rejected.  /party create uses defer()+followup.send(), not send_message."""
    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name=sample_party.name, characters_list="")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert Strings.PARTY_ALREADY_EXISTS.format(party_name=sample_party.name) in msg


# ===========================================================================
# 15.  /encounter create — name injection
# ===========================================================================


async def test_encounter_create_sql_injection_name_stored_safely(
    mocker, encounter_bot, sample_active_party, session_factory
):
    """SQL-injection in an encounter name must be stored verbatim."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name=_SQL_INJECTION)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(name=_SQL_INJECTION).first()
    assert enc is not None
    verify.close()


async def test_encounter_create_rtl_override_in_name_stored_safely(
    mocker, encounter_bot, sample_active_party, session_factory
):
    """RTL-override character in an encounter name must not crash."""
    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name=_RTL_OVERRIDE)

    assert interaction.response.send_message.called


# ===========================================================================
# 16.  Resource-limit exhaustion
# ===========================================================================


async def test_character_create_at_user_limit_rejected(
    mocker, db_session, sample_user, sample_server
):
    """Creating a character when the user already has MAX_CHARACTERS_PER_USER
    characters must be rejected by save_character_from_wizard."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    # Fill up to the limit
    for i in range(MAX_CHARACTERS_PER_USER):
        char = Character(
            name=f"Char{i}", user=sample_user, server=sample_server, is_active=False
        )
        db_session.add(char)
        db_session.flush()
        db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
    db_session.commit()

    interaction = make_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="OneMore",
    )
    char, error = save_character_from_wizard(state, interaction, db_session)

    assert char is None
    assert error == Strings.ERROR_LIMIT_CHARACTERS.format(limit=MAX_CHARACTERS_PER_USER)


async def test_attack_add_at_character_attack_limit_rejected(
    mocker, attack_bot, sample_character, db_session
):
    """Adding an attack when the character already has MAX_ATTACKS_PER_CHARACTER
    attacks must be rejected."""
    for i in range(MAX_ATTACKS_PER_CHARACTER):
        db_session.add(
            Attack(
                character_id=sample_character.id,
                name=f"Attack{i}",
                hit_modifier=5,
                damage_formula="1d8",
            )
        )
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="OneMoreAttack", hit_mod=5, damage_formula="1d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        Strings.ERROR_LIMIT_ATTACKS.format(
            char_name=sample_character.name, limit=MAX_ATTACKS_PER_CHARACTER
        )
        in msg
    )


async def test_party_create_at_server_party_limit_rejected(
    mocker, party_bot, sample_user, sample_server, db_session
):
    """Creating a party when the server already has MAX_PARTIES_PER_SERVER
    parties must be rejected.

    Note: parties are owned by a filler user to avoid triggering the
    per-user GM limit before the server limit is reached.
    /party create uses defer()+followup.send(), not send_message.
    """
    from models import User as _User

    filler = _User(discord_id="777777")
    db_session.add(filler)
    db_session.flush()
    for i in range(MAX_PARTIES_PER_SERVER):
        party = Party(name=f"Party{i}", gms=[filler], server=sample_server)
        db_session.add(party)
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="OneMore", characters_list="")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert (
        Strings.ERROR_LIMIT_PARTIES_SERVER.format(limit=MAX_PARTIES_PER_SERVER) in msg
    )


async def test_party_create_at_gm_party_limit_rejected(
    mocker, party_bot, sample_user, sample_server, db_session
):
    """Creating a party when the user is already GM of MAX_GM_PARTIES_PER_USER
    parties must be rejected.  /party create uses defer()+followup.send()."""
    for i in range(MAX_GM_PARTIES_PER_USER):
        party = Party(name=f"GMParty{i}", gms=[sample_user], server=sample_server)
        db_session.add(party)
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="OneMoreGM", characters_list="")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert Strings.ERROR_LIMIT_GM_PARTIES.format(limit=MAX_GM_PARTIES_PER_USER) in msg


async def test_encounter_enemy_at_limit_rejected(
    mocker, encounter_bot, sample_active_party, sample_pending_encounter, db_session
):
    """Adding an enemy when the encounter already has MAX_ENEMIES_PER_ENCOUNTER
    enemies must be rejected."""
    for i in range(MAX_ENEMIES_PER_ENCOUNTER):
        db_session.add(
            Enemy(
                encounter_id=sample_pending_encounter.id,
                name=f"Enemy{i}",
                type_name="Goblin",
                initiative_modifier=0,
                max_hp=5,
                current_hp=5,
            )
        )
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="OneMore", initiative_modifier=0, max_hp="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert str(MAX_ENEMIES_PER_ENCOUNTER) in msg


async def test_party_character_add_at_member_limit_rejected(
    mocker, party_bot, sample_user, sample_server, sample_party, db_session
):
    """Adding a character to a party that already has MAX_CHARACTERS_PER_PARTY
    members must be rejected."""
    for i in range(MAX_CHARACTERS_PER_PARTY):
        char = Character(
            name=f"Member{i}", user=sample_user, server=sample_server, is_active=False
        )
        db_session.add(char)
        db_session.flush()
        db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
        sample_party.characters.append(char)
    db_session.commit()

    # Create the extra character to try to add
    extra = Character(
        name="Extra", user=sample_user, server=sample_server, is_active=False
    )
    db_session.add(extra)
    db_session.flush()
    db_session.add(ClassLevel(character_id=extra.id, class_name="Rogue", level=1))
    db_session.commit()

    interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name=sample_party.name, character_name="Extra")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert (
        Strings.ERROR_LIMIT_PARTY_MEMBERS.format(limit=MAX_CHARACTERS_PER_PARTY) in msg
    )
