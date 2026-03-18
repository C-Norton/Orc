import pytest
from models import Character
from tests.commands.conftest import get_callback

# HOW THE FIXTURES CONNECT
# ─────────────────────────────────────────────────────────────────────────────
# health_bot   – a discord.ext.commands.Bot wired to a throw-away in-memory
#                SQLite DB. The fixture (in tests/commands/conftest.py) replaces
#                the real `SessionLocal` inside health_commands with a factory
#                that creates sessions against the test DB, then calls
#                register_health_commands(bot) so the slash commands exist.
#
# session_factory – a SQLAlchemy sessionmaker bound to the same in-memory DB.
#                All sessions (test fixtures and command handlers) share one
#                underlying connection via StaticPool, so a commit in one session
#                is immediately visible in another.
#
# db_session   – a single open session used by test setup to seed or mutate rows
#                before the command runs.
#
# sample_character – inserts "Aldric" (user_id="111", guild_id="222",
#                is_active=True) via db_session. HP fields default to -1.
#                Tests that need HP pre-set must assign values and call
#                db_session.commit().
#
# interaction  – a PytestMock(spec=discord.Interaction) with user.id=111 and
#                guild_id=222 matching sample_user/sample_server. Its
#                interaction.response is an AsyncMock, so awaiting send_message()
#                works without a real Discord connection and call args are
#                inspectable afterward.
# ─────────────────────────────────────────────────────────────────────────────


async def test_set_hp_success(health_bot, sample_character, interaction, session_factory):
    # get_callback walks bot.tree and returns the raw async function behind the
    # slash command, letting us call it directly without Discord's dispatch.
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=40)

    # The command opened and closed its own session internally. Open a fresh
    # session to verify what was actually persisted — don't reuse db_session,
    # which still holds a stale in-memory view of the row.
    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 40
    assert char.current_hp == 40  # /set_max_hp should initialize current_hp to max_hp
    verify.close()


async def test_set_hp_no_character(health_bot, sample_user, sample_server, interaction):
    # sample_user and sample_server exist but there is no character, so the
    # command must send an ephemeral (private) error message.
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=30)

    # interaction.response.send_message is an AsyncMock; call_args.kwargs holds
    # the keyword arguments from the most recent call. ephemeral=True makes the
    # response visible only to the caller in Discord.
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_hp_zero(health_bot, sample_character, interaction, session_factory):
    # Setting max hp to 0 or negative should be rejected
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=30)
    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 30
    assert char.current_hp == 30
    verify.close()

    await cb(interaction, max_hp=0)
    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 30
    assert char.current_hp == 30
    verify.close()

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_hp_negative(health_bot, sample_character, interaction, session_factory):
    cb = get_callback(health_bot, "hp", "set_max")
    await cb(interaction, max_hp=30)
    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 30
    assert char.current_hp == 30
    verify.close()

    await cb(interaction, max_hp=-1)
    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 30
    assert char.current_hp == 30
    verify.close()

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_damage_reduces_hp(health_bot, sample_character, db_session, interaction, session_factory):
    # sample_character has no HP set yet (max_hp=-1). Assign values and commit
    # BEFORE calling the command. The command opens a brand-new session, so any
    # changes that only exist in db_session's local cache won't be visible unless
    # they've been flushed to the shared connection via commit().
    sample_character.max_hp = 30
    sample_character.current_hp = 30
    sample_character.temp_hp = 0
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="10")

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.current_hp == 20
    verify.close()


async def test_damage_burns_temp_hp_first(health_bot, sample_character, db_session, interaction, session_factory):
    sample_character.max_hp = 30
    sample_character.current_hp = 30
    sample_character.temp_hp = 5
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="3")  # 3 damage < 5 temp HP, so current HP is untouched

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.current_hp == 30  # untouched
    assert char.temp_hp == 2
    verify.close()


async def test_damage_can_go_below_zero(health_bot, sample_character, db_session, interaction, session_factory):
    # HP is allowed to go negative. If current_hp drops to -max_hp or below,
    # the character dies from the massive damage rule (non-ephemeral message).
    sample_character.max_hp = 10
    sample_character.current_hp = 5
    sample_character.temp_hp = 0
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="100")  # 5 - 100 = -95, which is <= -10 (massive damage)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.current_hp == -95  # HP goes negative
    verify.close()

    # Massive damage death message must be non-ephemeral so the whole table sees it
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_damage_requires_hp_set(health_bot, sample_character, interaction):
    # sample_character has max_hp=-1, current_hp=-1 by default (HP not yet
    # initialized via /set_max_hp). The command should send an ephemeral error.
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# /heal ------------------------------------------------------------------

async def test_heal_restores_hp(health_bot, sample_character, db_session, interaction, session_factory):
    sample_character.max_hp = 30
    sample_character.current_hp = 15
    sample_character.temp_hp = 0
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="10")

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.current_hp == 25
    verify.close()


async def test_heal_capped_at_max(health_bot, sample_character, db_session, interaction, session_factory):
    sample_character.max_hp = 30
    sample_character.current_hp = 28
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="10")  # would overshoot to 38 — must cap at 30

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.current_hp == 30
    verify.close()


# /add_temp_hp -----------------------------------------------------------

async def test_temp_hp_set(health_bot, sample_character, db_session, interaction, session_factory):
    sample_character.max_hp = 30
    sample_character.current_hp = 30
    sample_character.temp_hp = 0
    db_session.commit()

    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=8)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.temp_hp == 8
    verify.close()


async def test_temp_hp_does_not_stack(health_bot, sample_character, db_session, interaction, session_factory):
    # D&D 5e rule: temp HP replaces rather than adds. If the new value is lower,
    # keep the existing amount.
    sample_character.max_hp = 30
    sample_character.current_hp = 30
    sample_character.temp_hp = 10
    db_session.commit()

    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=5)  # lower than existing — should stay at 10

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.temp_hp == 10
    verify.close()


# /hp --------------------------------------------------------------------

async def test_hp_view_sends_message(health_bot, sample_character, db_session, interaction):
    sample_character.max_hp = 30
    sample_character.current_hp = 22
    sample_character.temp_hp = 5
    db_session.commit()

    cb = get_callback(health_bot, "hp", "status")
    await cb(interaction)

    # call_args.args[0] is the first positional argument to send_message — the
    # message string. Assert key values appear rather than the exact wording so
    # minor phrasing changes don't break this test.
    msg = interaction.response.send_message.call_args.args[0]
    assert "Aldric" in msg
    assert "22" in msg
    assert "30" in msg


async def test_hp_view_no_character(health_bot, sample_user, sample_server, interaction):
    # No sample_character fixture — user exists but has no active character.
    cb = get_callback(health_bot, "hp", "status")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
