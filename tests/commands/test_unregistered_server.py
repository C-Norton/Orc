"""
Edge case tests for commands invoked in a server that is not registered in the
``servers`` table.

When the bot is added to a new Discord server the ``Server`` row is created
only when a user first calls ``/character create``.  Until that happens, every
other command must fail gracefully with an ephemeral error rather than crashing.

Sections
--------
1. Helper unit tests     — ``resolve_user_server`` / ``get_active_*`` with None server
2. /character commands   — ``create`` auto-registers; all others reject gracefully
3. /hp commands          — all reject gracefully
4. /roll commands        — raw-dice succeeds; named rolls reject gracefully
5. /attack commands      — all reject gracefully
6. /party commands       — create rejects; view/active/delete may crash (documented bugs)
7. /encounter commands   — all reject gracefully
8. /inspiration commands — all reject gracefully

Known defects
-------------
BUG-URS-1  ``/party active <name>`` accesses ``server.id`` before checking for
           ``None``, raising ``AttributeError`` on an unregistered server.
BUG-URS-2  ``/party active`` (view mode, no name given) accesses ``server.id``
           before a ``None`` check.
BUG-URS-3  ``/party view <name>`` accesses ``server.id`` without a ``None`` check.
BUG-URS-4  ``/party delete <name>`` accesses ``server.id`` without a ``None`` check.
BUG-URS-5  ``/party character_add`` accesses ``server.id`` without a ``None`` check.
BUG-URS-6  ``/party character_remove`` accesses ``server.id`` without a ``None`` check.
"""

import pytest

from tests.conftest import make_interaction
from tests.commands.conftest import get_callback
from utils.db_helpers import get_active_character, get_active_party, resolve_user_server
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


# ===========================================================================
# 2.  /character commands
# ===========================================================================


async def test_character_create_auto_registers_unregistered_server(
    mocker, char_bot, session_factory
):
    """``/character create`` is the bootstrap command — it must create both the
    User and Server rows when neither exists yet."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "create")
    await cb(interaction, name="Newbie", character_class="Wizard", level=1)

    from models import Server

    verify = session_factory()
    server = verify.query(Server).filter_by(discord_id=str(_UNKNOWN_GUILD_ID)).first()
    assert server is not None
    verify.close()


async def test_character_create_in_unregistered_server_succeeds(mocker, char_bot):
    """``/character create`` does not send an ephemeral error when the server is
    unregistered — it bootstraps and creates the character normally."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(char_bot, "character", "create")
    await cb(interaction, name="Newbie", character_class="Fighter", level=1)

    # Success response should NOT be ephemeral
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


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
    await cb(
        interaction,
        strength=True,
        dexterity=False,
        constitution=False,
        intelligence=False,
        wisdom=False,
        charisma=False,
    )

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


async def test_party_create_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party create`` returns an ephemeral 'user or server not initialized'
    error when the server is unregistered.  Party creation requires both records
    to exist."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Wanderers", characters_list="")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.ERROR_USER_SERVER_NOT_INIT in msg


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


@pytest.mark.xfail(
    reason=(
        "BUG-URS-5: /party character_add accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_character_add_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party character_add`` should return an ephemeral error when the server is
    unregistered, but currently crashes with AttributeError."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="Wanderers", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.xfail(
    reason=(
        "BUG-URS-6: /party character_remove accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_character_remove_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party character_remove`` should return an ephemeral error when the server is
    unregistered, but currently crashes with AttributeError."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name="Wanderers", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.xfail(
    reason=(
        "BUG-URS-1: /party active <name> accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_active_set_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party active <name>`` should return an ephemeral error when the server
    is unregistered, but currently crashes with AttributeError."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name="Wanderers")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.xfail(
    reason=(
        "BUG-URS-2: /party active (view) accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_active_view_in_unregistered_server_returns_ephemeral(
    mocker, party_bot
):
    """``/party active`` (no name — view mode) should return an ephemeral error
    when the server is unregistered, but currently crashes with AttributeError."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name=None)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.xfail(
    reason=(
        "BUG-URS-3: /party view accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_view_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party view`` should return an ephemeral error when the server is
    unregistered, but currently crashes with AttributeError."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name="Wanderers")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.xfail(
    reason=(
        "BUG-URS-4: /party delete accesses server.id before checking for "
        "None, raising AttributeError on an unregistered server."
    ),
    strict=True,
)
async def test_party_delete_in_unregistered_server_returns_ephemeral(mocker, party_bot):
    """``/party delete`` should return an ephemeral error when the server is
    unregistered, but currently crashes with AttributeError."""
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

    mocker.patch("commands.inspiration_commands.SessionLocal", new=session_factory)
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


async def test_inspiration_remove_self_in_unregistered_server_returns_ephemeral(
    mocker, inspiration_bot
):
    """``/inspiration remove`` returns an ephemeral 'no character' error when the
    server is unregistered."""
    interaction = _unknown_server_interaction(mocker)
    cb = get_callback(inspiration_bot, "inspiration", "remove")
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
