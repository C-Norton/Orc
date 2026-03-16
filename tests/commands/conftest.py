import pytest
from unittest.mock import patch
import discord
from discord.ext import commands
from sqlalchemy import insert

from models import User, Server, Character, Party, user_server_association
from tests.conftest import make_interaction  # re-export for convenience


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bot():
    intents = discord.Intents.none()
    return commands.Bot(command_prefix="!", intents=intents)


def get_callback(bot, name):
    """Return the raw async callback for a registered slash command."""
    for cmd in bot.tree.get_commands():
        if cmd.name == name:
            return cmd.callback
    raise KeyError(f"No command {name!r} registered on this bot")


# ---------------------------------------------------------------------------
# Per-module bot fixtures
# Each fixture patches SessionLocal in the target module for the whole test.
# ---------------------------------------------------------------------------

@pytest.fixture
def char_bot(session_factory):
    bot = make_bot()
    with patch("commands.character_commands.SessionLocal", new=session_factory):
        from commands.character_commands import register_character_commands
        register_character_commands(bot)
        yield bot


@pytest.fixture
def attack_bot(session_factory):
    bot = make_bot()
    with patch("commands.attack_commands.SessionLocal", new=session_factory):
        from commands.attack_commands import register_attack_commands
        register_attack_commands(bot)
        yield bot


@pytest.fixture
def roll_bot(session_factory):
    bot = make_bot()
    with patch("commands.roll_commands.SessionLocal", new=session_factory):
        from commands.roll_commands import register_roll_commands
        register_roll_commands(bot)
        yield bot


@pytest.fixture
def party_bot(session_factory):
    bot = make_bot()
    with patch("commands.party_commands.SessionLocal", new=session_factory):
        from commands.party_commands import register_party_commands
        register_party_commands(bot)
        yield bot


# ---------------------------------------------------------------------------
# Party-specific seed fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_party(db_session, sample_user, sample_server):
    party = Party(name="The Fellowship", gm=sample_user, server=sample_server)
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
