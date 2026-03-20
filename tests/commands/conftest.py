import pytest
import discord
from discord.ext import commands
from sqlalchemy import insert

from models import (
    User,
    Server,
    Character,
    Party,
    Encounter,
    Enemy,
    EncounterTurn,
    user_server_association,
)
from enums.encounter_status import EncounterStatus
from tests.conftest import make_interaction  # re-export for convenience


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bot():
    intents = discord.Intents.none()
    return commands.Bot(command_prefix="!", intents=intents)


def get_callback(bot, *path):
    """Return the raw async callback for a (possibly nested) slash command.

    Examples::
        get_callback(bot, "roll")                   # top-level
        get_callback(bot, "character", "create")    # group > subcommand
        get_callback(bot, "attack", "roll")         # group > subcommand
    """
    cmd = bot.tree.get_command(path[0])
    if cmd is None:
        raise KeyError(f"No command {path[0]!r} registered on this bot")
    for part in path[1:]:
        cmd = cmd.get_command(part)
        if cmd is None:
            raise KeyError(f"No subcommand {part!r}")
    return cmd.callback


# ---------------------------------------------------------------------------
# Per-module bot fixtures
# Each fixture patches SessionLocal in the target module for the whole test.
# ---------------------------------------------------------------------------


@pytest.fixture
def health_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.health_commands.SessionLocal", new=session_factory)
    from commands.health_commands import register_health_commands

    register_health_commands(bot)
    yield bot


@pytest.fixture
def char_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.character_commands.SessionLocal", new=session_factory)
    from commands.character_commands import register_character_commands

    register_character_commands(bot)
    yield bot


@pytest.fixture
def attack_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.attack_commands.SessionLocal", new=session_factory)
    from commands.attack_commands import register_attack_commands

    register_attack_commands(bot)
    yield bot


@pytest.fixture
def roll_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.roll_commands.SessionLocal", new=session_factory)
    from commands.roll_commands import register_roll_commands

    register_roll_commands(bot)
    yield bot


@pytest.fixture
def party_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.party_commands.SessionLocal", new=session_factory)
    from commands.party_commands import register_party_commands

    register_party_commands(bot)
    yield bot


@pytest.fixture
def encounter_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.encounter_commands.SessionLocal", new=session_factory)
    from commands.encounter_commands import register_encounter_commands

    register_encounter_commands(bot)
    yield bot


@pytest.fixture
def meta_bot():
    bot = make_bot()
    from commands.meta_commands import register_meta_commands

    register_meta_commands(bot)
    yield bot


@pytest.fixture
def inspiration_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.inspiration_commands.SessionLocal", new=session_factory)
    from commands.inspiration_commands import register_inspiration_commands

    register_inspiration_commands(bot)
    yield bot


@pytest.fixture
def weapon_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.weapon_commands.SessionLocal", new=session_factory)
    from commands.weapon_commands import register_weapon_commands

    register_weapon_commands(bot)
    yield bot


# ---------------------------------------------------------------------------
# Party-specific seed fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_party(db_session, sample_user, sample_server):
    party = Party(name="The Fellowship", gms=[sample_user], server=sample_server)
    db_session.add(party)
    db_session.commit()
    db_session.refresh(party)
    return party


@pytest.fixture
def sample_active_party(db_session, sample_party, sample_user, sample_server):
    """Creates a party AND sets it as the user's active party via the
    user_server_association table, mirroring what /create_party does."""
    stmt = insert(user_server_association).values(
        user_id=sample_user.id,
        server_id=sample_server.id,
        active_party_id=sample_party.id,
    )
    db_session.execute(stmt)
    db_session.commit()
    return sample_party


# ---------------------------------------------------------------------------
# Encounter seed fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pending_encounter(db_session, sample_active_party):
    encounter = Encounter(
        name="Test Dungeon",
        party_id=sample_active_party.id,
        server_id=sample_active_party.server_id,
        status=EncounterStatus.PENDING,
    )
    db_session.add(encounter)
    db_session.commit()
    db_session.refresh(encounter)
    return encounter


@pytest.fixture
def sample_enemy(db_session, sample_pending_encounter):
    enemy = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Goblin",
        type_name="Goblin",
        initiative_modifier=1,
        max_hp=7,
        current_hp=7,
    )
    db_session.add(enemy)
    db_session.commit()
    db_session.refresh(enemy)
    return enemy


@pytest.fixture
def sample_active_encounter(
    db_session, sample_pending_encounter, sample_enemy, sample_character
):
    """Fully started encounter: Aldric (position 0, roll 15) vs Goblin (position 1, roll 10).
    message_id/channel_id match the defaults in make_interaction."""
    sample_pending_encounter.party.characters.append(sample_character)

    char_turn = EncounterTurn(
        encounter_id=sample_pending_encounter.id,
        character_id=sample_character.id,
        initiative_roll=15,
        order_position=0,
    )
    enemy_turn = EncounterTurn(
        encounter_id=sample_pending_encounter.id,
        enemy_id=sample_enemy.id,
        initiative_roll=10,
        order_position=1,
    )
    db_session.add_all([char_turn, enemy_turn])

    sample_pending_encounter.status = EncounterStatus.ACTIVE
    sample_pending_encounter.current_turn_index = 0
    sample_pending_encounter.round_number = 1
    sample_pending_encounter.message_id = "99999"
    sample_pending_encounter.channel_id = "333"

    db_session.commit()
    db_session.refresh(sample_pending_encounter)
    return sample_pending_encounter
