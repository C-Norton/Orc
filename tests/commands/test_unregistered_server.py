"""
Edge case tests for commands invoked by a brand-new user on a brand-new server.

Commands use ``get_or_create_user_server``, which auto-registers both the User
and Server rows on first use.  Commands that require an active character or party
return ephemeral errors when none exist, but they never crash due to a missing
server or user row.

Sections
--------
1. Helper unit tests     — ``resolve_user_server`` / ``get_active_*`` with None inputs
2. /character commands   — ``create`` succeeds; all others fail gracefully (no character)
3. /hp commands          — all fail gracefully (no character)
4. /roll commands        — raw-dice succeeds; named rolls fail gracefully (no character)
5. /attack commands      — all fail gracefully (no character)
6. /party commands       — create succeeds; commands requiring a party fail gracefully
7. /encounter commands   — all fail gracefully (no party/character)
8. /inspiration commands — all fail gracefully (no character)
"""

import pytest

from models import Server
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback
from utils.db_helpers import (
    get_active_character,
    get_active_party,
    get_or_create_user_server,
    resolve_user_server,
)
from utils.strings import Strings


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Guild ID that is intentionally absent from the ``servers`` table.
_UNKNOWN_GUILD_ID = 999


def _unknown_server_interaction(mocker):
    """Return a mock interaction whose guild_id maps to no Server row."""
    return make_interaction(mocker, guild_id=_UNKNOWN_GUILD_ID)


# ===========================================================================
# 1.  Helper unit tests
# ===========================================================================


def test_resolve_user_server_returns_none_server_when_guild_unregistered(
    db_session, sample_user, mocker
):
    """``resolve_user_server`` returns ``None`` for the server component when
    the guild is not in the servers table.  The user row may exist independently."""
    interaction = _unknown_server_interaction(mocker)
    user, server = resolve_user_server(db_session, interaction)
    assert server is None


def test_resolve_user_server_returns_none_for_both_when_guild_and_user_unregistered(
    db_session, mocker
):
    """Both ``user`` and ``server`` are ``None`` when the interaction comes from
    a brand-new Discord user on an unregistered server."""
    interaction = make_interaction(mocker, user_id=9001, guild_id=_UNKNOWN_GUILD_ID)
    user, server = resolve_user_server(db_session, interaction)
    assert user is None
    assert server is None


def test_get_active_character_returns_none_when_server_is_none(db_session, sample_user):
    """``get_active_character`` returns ``None`` immediately when ``server`` is
    ``None``, avoiding a spurious DB query."""
    result = get_active_character(db_session, sample_user, None)
    assert result is None


def test_get_active_character_returns_none_when_user_is_none(db_session, sample_server):
    """``get_active_character`` returns ``None`` immediately when ``user`` is
    ``None``."""
    result = get_active_character(db_session, None, sample_server)
    assert result is None


def test_get_active_character_returns_none_when_both_none(db_session):
    """``get_active_character`` returns ``None`` when both arguments are
    ``None``."""
    result = get_active_character(db_session, None, None)
    assert result is None


def test_get_active_party_returns_none_when_server_is_none(db_session, sample_user):
    """``get_active_party`` returns ``None`` immediately when ``server`` is
    ``None``."""
    result = get_active_party(db_session, sample_user, None)
    assert result is None


def test_get_active_party_returns_none_when_user_is_none(db_session, sample_server):
    """``get_active_party`` returns ``None`` immediately when ``user`` is
    ``None``."""
    result = get_active_party(db_session, None, sample_server)
    assert result is None


def test_get_active_party_returns_none_when_both_none(db_session):
    """``get_active_party`` returns ``None`` when both arguments are ``None``."""
    result = get_active_party(db_session, None, None)
    assert result is None


# ---------------------------------------------------------------------------
# get_or_create_user_server
# ---------------------------------------------------------------------------


def test_get_or_create_creates_user_and_server_on_first_call(db_session, mocker):
    """Both User and Server rows are created when neither exists yet."""
    interaction = make_interaction(mocker, user_id=8001, guild_id=8002)
    user, server = get_or_create_user_server(db_session, interaction)
    assert user is not None
    assert user.discord_id == "8001"
    assert server is not None
    assert server.discord_id == "8002"


def test_get_or_create_returns_existing_rows_on_second_call(db_session, mocker):
    """A second call with the same IDs returns the existing rows, not duplicates."""
    interaction = make_interaction(mocker, user_id=8001, guild_id=8002)
    user1, server1 = get_or_create_user_server(db_session, interaction)
    user2, server2 = get_or_create_user_server(db_session, interaction)
    assert user1.id == user2.id
    assert server1.id == server2.id


def test_get_or_create_never_returns_none(db_session, mocker):
    """Neither return value is ever None, even for a brand-new user and server."""
    interaction = make_interaction(mocker, user_id=9999, guild_id=9998)
    user, server = get_or_create_user_server(db_session, interaction)
    assert user is not None
    assert server is not None


def test_get_or_create_uses_guild_name_for_new_server(db_session, mocker):
    """The Server row is created with the guild name from the interaction."""
    interaction = make_interaction(mocker, guild_id=7001, guild_name="Brave New World")
    _, server = get_or_create_user_server(db_session, interaction)
    assert server.name == "Brave New World"


def test_get_or_create_creates_user_server_association(db_session, mocker):
    """The user-server association row is created so get_active_party works."""
    interaction = make_interaction(mocker, user_id=6001, guild_id=6002)
    user, server = get_or_create_user_server(db_session, interaction)
    db_session.refresh(user)
    assert server in user.servers


def test_get_or_create_with_existing_user_new_server(db_session, sample_user, mocker):
    """When the user already exists but the server is new, only the server is created."""
    interaction = make_interaction(mocker, user_id=111, guild_id=5001)
    user, server = get_or_create_user_server(db_session, interaction)
    assert user.id == sample_user.id
    assert server.discord_id == "5001"


def test_get_or_create_with_new_user_existing_server(db_session, sample_server, mocker):
    """When the server already exists but the user is new, only the user is created."""
    interaction = make_interaction(mocker, user_id=4001, guild_id=222)
    user, server = get_or_create_user_server(db_session, interaction)
    assert user.discord_id == "4001"
    assert server.id == sample_server.id


def test_get_or_create_idempotent_association(
    db_session, sample_user, sample_server, mocker
):
    """Calling get_or_create twice does not create duplicate association rows."""
    interaction = make_interaction(mocker, user_id=111, guild_id=222)
    get_or_create_user_server(db_session, interaction)
    get_or_create_user_server(db_session, interaction)
    db_session.refresh(sample_user)
    assert sample_user.servers.count(sample_server) == 1


# ===========================================================================
# 2.  /character commands
# ===========================================================================


async def test_character_create_auto_registers_unregistered_server(mocker, db_session):
    """``save_character_from_wizard`` bootstraps both User and Server rows
    when neither exists yet (new server + new user)."""
    from commands.wizard.state import WizardState, save_character_from_wizard
    from models import Server

    interaction = _unknown_server_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id=str(_UNKNOWN_GUILD_ID),
        guild_name="Unknown Server",
        name="Newbie",
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    server = (
        db_session.query(Server).filter_by(discord_id=str(_UNKNOWN_GUILD_ID)).first()
    )
    assert server is not None


async def test_character_create_in_unregistered_server_succeeds(mocker, db_session):
    """``save_character_from_wizard`` creates the character normally on a server
    that has never been registered."""
    from commands.wizard.state import WizardState, save_character_from_wizard

    interaction = _unknown_server_interaction(mocker)
    state = WizardState(
        user_discord_id="111",
        guild_discord_id=str(_UNKNOWN_GUILD_ID),
        guild_name="Unknown Server",
        name="Newbie",
    )
    char, error = save_character_from_wizard(state, interaction, db_session)
    assert error is None
    assert char is not None
    assert char.is_active is True


async def test_character_list_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character list`` returns a graceful ephemeral response when the server
    has never been registered (no characters exist on it)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "list")
    await cb(interaction)

    # Either ephemeral error or an empty-list message — never a crash
    called_kwargs = interaction.response.send_message.call_args.kwargs
    msg = (
        interaction.response.send_message.call_args.args[0]
        if interaction.response.send_message.call_args.args
        else ""
    )
    assert called_kwargs.get("ephemeral") is True or "no characters" in msg.lower()


async def test_character_view_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character view`` returns an ephemeral 'no active character' error when
    the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_character_switch_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character switch`` returns an ephemeral error when the server is
    unregistered (no characters can be found to switch to)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "switch")
    await cb(interaction, name="Anyone")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_delete_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character delete`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Anyone")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_character_stats_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character stats`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
        initiative_bonus=0,
    )

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_character_ac_in_unregistered_server_returns_ephemeral(mocker, char_bot):
    """``/character ac`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=15)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_character_skill_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character skill`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "skill")
    await cb(interaction, skill="perception", status="proficient")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_character_saves_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character saves`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "saves")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_character_class_add_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character class_add`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=3)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_character_class_remove_in_unregistered_server_returns_ephemeral(
    mocker, char_bot
):
    """``/character class_remove`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Rogue")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


# ===========================================================================
# 3.  /hp commands
# ===========================================================================


async def test_hp_set_max_in_unregistered_server_returns_ephemeral(mocker, health_bot):
    """``/hp set_max`` returns an ephemeral 'no active character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=20)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_hp_damage_self_in_unregistered_server_returns_ephemeral(
    mocker, health_bot
):
    """``/hp damage`` (self-damage) returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_hp_damage_partymember_in_unregistered_server_returns_ephemeral(
    mocker, health_bot
):
    """``/hp damage <partymember>`` returns an ephemeral 'no active party' error
    when the server is unregistered (no party can exist on it)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5", partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


async def test_hp_heal_self_in_unregistered_server_returns_ephemeral(
    mocker, health_bot
):
    """``/hp heal`` (self-heal) returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_hp_heal_partymember_in_unregistered_server_returns_ephemeral(
    mocker, health_bot
):
    """``/hp heal <partymember>`` returns an ephemeral 'no active party' error
    when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="5", partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


async def test_hp_status_in_unregistered_server_returns_ephemeral(mocker, health_bot):
    """``/hp status`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "status")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_hp_temp_in_unregistered_server_returns_ephemeral(mocker, health_bot):
    """``/hp temp`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=10)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ACTIVE_CHARACTER_NOT_FOUND in msg


async def test_hp_party_temp_in_unregistered_server_returns_ephemeral(
    mocker, health_bot
):
    """``/hp party_temp`` returns an ephemeral 'no active party' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(health_bot, "hp", "party_temp")
    await cb(interaction, amount=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


# ===========================================================================
# 4.  /roll commands
# ===========================================================================


async def test_roll_raw_dice_in_unregistered_server_succeeds(mocker, roll_bot):
    """``/roll 1d20`` does NOT require a character or server — it should succeed
    and return a non-ephemeral result even in an unregistered server."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d20")

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_roll_constant_expression_in_unregistered_server_succeeds(
    mocker, roll_bot
):
    """A pure arithmetic expression requires no character and must succeed even
    in an unregistered server."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d6+3")

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_roll_skill_in_unregistered_server_returns_ephemeral(mocker, roll_bot):
    """``/roll perception`` requires an active character and must return an
    ephemeral error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_roll_saving_throw_in_unregistered_server_returns_ephemeral(
    mocker, roll_bot
):
    """``/roll strength save`` requires an active character and must return an
    ephemeral error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="strength save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_roll_initiative_in_unregistered_server_returns_ephemeral(
    mocker, roll_bot
):
    """``/roll initiative`` requires an active character and must return an
    ephemeral error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="initiative")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_roll_stat_check_in_unregistered_server_returns_ephemeral(
    mocker, roll_bot
):
    """``/roll strength`` (stat check) requires an active character and must
    return an ephemeral error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="strength")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_roll_death_save_in_unregistered_server_returns_ephemeral(
    mocker, roll_bot
):
    """``/roll death save`` requires an active character and must return an
    ephemeral error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


# ===========================================================================
# 5.  /attack commands
# ===========================================================================


async def test_attack_add_in_unregistered_server_returns_ephemeral(mocker, attack_bot):
    """``/attack add`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+3")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_attack_roll_in_unregistered_server_returns_ephemeral(mocker, attack_bot):
    """``/attack roll`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_attack_list_in_unregistered_server_returns_ephemeral(mocker, attack_bot):
    """``/attack list`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(attack_bot, "attack", "list")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


# ===========================================================================
# 6.  /party commands
# ===========================================================================


async def test_party_create_in_unregistered_server_succeeds(mocker, party_bot):
    """``/party create`` auto-registers the server and user on first use, so it
    succeeds even on a brand-new server.  Uses defer()+followup.send()."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Wanderers", characters_list="")

    msg = interaction.followup.send.call_args.args[0]
    assert "wanderers" in msg.lower()


async def test_party_roll_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party roll`` returns an ephemeral error when the server is
    unregistered (no active party can exist)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "roll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_PARTY_SET_ACTIVE_FIRST in msg


async def test_party_roll_as_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party roll_as`` returns an ephemeral error prompting the user to set
    an active party when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "roll_as")
    await cb(interaction, member_name="Aldric", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_PARTY_SET_ACTIVE_FIRST in msg


async def test_party_character_add_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party character_add`` returns an ephemeral error on a brand-new server
    (server auto-registers but no party named 'Wanderers' exists)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="Wanderers", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_character_remove_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party character_remove`` returns an ephemeral error on a brand-new server
    (no party or character exists)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name="Wanderers", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_active_set_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party active <name>`` returns an ephemeral error on a brand-new server
    (server auto-registers but the named party does not exist)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name="Wanderers")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_active_view_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party active`` (no name — view mode) returns an ephemeral 'no active
    party' message on a brand-new server (auto-registers but no party is set)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name=None)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_view_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party view`` returns an ephemeral 'party not found' error when the
    server is unregistered (the named party cannot exist)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name="Wanderers")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_delete_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party delete`` returns an ephemeral error on a brand-new server
    (server auto-registers but the named party does not exist)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "delete")
    await cb(interaction, party_name="Wanderers")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 7.  /encounter commands
# ===========================================================================


async def test_encounter_create_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter create`` returns an ephemeral 'no active party' error when
    the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Goblin Ambush")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


async def test_encounter_start_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter start`` returns an ephemeral 'no active party' error when
    the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


async def test_encounter_next_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter next`` returns an ephemeral 'no active encounter' error when
    the server is unregistered (resolves through _require_active_encounter which
    uses ENCOUNTER_NOT_ACTIVE as the default no-party message)."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ENCOUNTER_NOT_ACTIVE in msg


async def test_encounter_end_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter end`` returns an ephemeral error when the server is
    unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "end")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_view_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter view`` returns an ephemeral 'no active encounter' error when
    the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ENCOUNTER_NOT_ACTIVE in msg


async def test_encounter_enemy_in_unregistered_server_returns_ephemeral(
    mocker, encounter_bot
):
    """``/encounter enemy`` returns an ephemeral 'no active party' error
    when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(
        interaction,
        name="Goblin",
        initiative_modifier=1,
        max_hp="7",
    )

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


# ===========================================================================
# 8.  /inspiration commands
# ===========================================================================


@pytest.fixture
def inspiration_bot(session_factory, mocker):
    """Bot with inspiration commands registered against the in-memory DB."""
    import discord
    from discord.ext import commands
    from commands.inspiration_commands import register_inspiration_commands

    mocker.patch("database.SessionLocal", new=session_factory)
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    register_inspiration_commands(bot)
    yield bot


async def test_inspiration_grant_self_in_unregistered_server_returns_ephemeral(
    mocker, inspiration_bot
):
    """``/inspiration grant`` (self) returns an ephemeral 'no character' error when
    the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_inspiration_grant_partymember_in_unregistered_server_returns_ephemeral(
    mocker, inspiration_bot
):
    """``/inspiration grant <partymember>`` returns an ephemeral 'no active party'
    error when the server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction, partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_NO_ACTIVE_PARTY in msg


async def test_inspiration_use_self_in_unregistered_server_returns_ephemeral(
    mocker, inspiration_bot
):
    """``/inspiration use`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(inspiration_bot, "inspiration", "use")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_inspiration_status_self_in_unregistered_server_returns_ephemeral(
    mocker, inspiration_bot
):
    """``/inspiration status`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg
