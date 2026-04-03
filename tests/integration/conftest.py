"""Shared fixtures and helpers for E2E integration tests.

The session-scoped DB keeps all state in a single in-memory SQLite instance
for the duration of the full test session, so integration tests can exercise
realistic multi-step flows (e.g. create character → edit → roll) without
rebuilding the schema between every test.
"""

import pytest
import discord
from discord.ext import commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from typing import Any

from models import Base


# ---------------------------------------------------------------------------
# Module-level player / guild constants
# ---------------------------------------------------------------------------

PLAYER_A_ID = "1001"
PLAYER_B_ID = "1002"
GUILD_ID = "9001"
CHANNEL_ID = "8001"


# ---------------------------------------------------------------------------
# Session-scoped DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def int_engine():
    """Session-scoped in-memory SQLite DB that persists across all E2E tests.

    Uses StaticPool so every session shares the same underlying connection,
    preventing SQLite from silently creating isolated per-connection databases.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def int_session_factory(int_engine):
    """Session-scoped sessionmaker bound to int_engine.

    All integration tests share this factory so data written in one test is
    visible to subsequent tests in the same session.
    """
    return sessionmaker(bind=int_engine, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# Plain-function helpers (not fixtures)
# ---------------------------------------------------------------------------


def make_e2e_interaction(
    mocker: Any,
    user_id: str,
    guild_id: str = GUILD_ID,
    channel_id: str = CHANNEL_ID,
    username: str = "player",
) -> Any:
    """Build a mock discord.Interaction suitable for E2E integration tests.

    Mirrors make_interaction() from tests/conftest.py but accepts an explicit
    user_id so individual tests can impersonate different players.

    Args:
        mocker: The pytest-mock ``mocker`` fixture.
        user_id: Discord snowflake string for the acting user.
        guild_id: Discord snowflake string for the guild. Defaults to GUILD_ID.
        channel_id: Discord snowflake string for the channel. Defaults to CHANNEL_ID.
        username: Display name for the acting user. Defaults to ``"player"``.

    Returns:
        A configured mock discord.Interaction instance.
    """
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.type = discord.InteractionType.application_command

    user = mocker.Mock()
    user.id = user_id
    user.bot = False
    user.display_name = username
    user.__str__ = mocker.Mock(return_value=f"{username}#{user_id}")
    interaction.user = user

    guild = mocker.Mock()
    guild.id = guild_id
    guild.name = "Integration Test Server"
    interaction.guild = guild
    interaction.guild_id = guild_id
    interaction.channel_id = channel_id

    # Mock message object returned by followup.send and channel.fetch_message.
    mock_message = mocker.Mock()
    mock_message.id = 99999
    mock_message.edit = mocker.AsyncMock()

    channel = mocker.Mock()
    channel.fetch_message = mocker.AsyncMock(return_value=mock_message)
    interaction.channel = channel

    interaction.response = mocker.AsyncMock()

    # is_done() is synchronous on discord.InteractionResponse. Start False,
    # flip to True once defer() or send_message() is called — matching real
    # Discord behaviour where only the first response is allowed.
    interaction.response.is_done = mocker.Mock(return_value=False)

    def _mark_response_done(*_args, **_kwargs):
        interaction.response.is_done.return_value = True

    interaction.response.defer.side_effect = _mark_response_done
    interaction.response.send_message.side_effect = _mark_response_done

    interaction.followup = mocker.AsyncMock()
    interaction.followup.send = mocker.AsyncMock(return_value=mock_message)
    interaction.original_response = mocker.AsyncMock(return_value=mock_message)
    interaction.namespace = mocker.Mock()

    # client is needed by commands that DM a user (e.g. gmroll).
    interaction.client = mocker.Mock()

    return interaction


def make_bot() -> commands.Bot:
    """Create a minimal discord.ext.commands.Bot for command registration.

    Returns:
        A Bot instance with no intents, suitable for slash-command testing.
    """
    intents = discord.Intents.none()
    return commands.Bot(command_prefix="!", intents=intents)


def get_callback(bot: commands.Bot, *path: str) -> Any:
    """Return the raw async callback for a (possibly nested) slash command.

    Args:
        bot: The Bot whose command tree will be searched.
        *path: One or more strings forming the command path, e.g.
               ``"roll"`` for a top-level command or
               ``"character", "create"`` for a subcommand.

    Returns:
        The underlying async callable registered for the command.

    Raises:
        KeyError: If any segment of the command path is not found.

    Examples::

        get_callback(bot, "roll")                # top-level
        get_callback(bot, "character", "create") # group > subcommand
    """
    cmd = bot.tree.get_command(path[0])
    if cmd is None:
        raise KeyError(f"No command {path[0]!r} registered on this bot")
    for part in path[1:]:
        cmd = cmd.get_command(part)
        if cmd is None:
            raise KeyError(f"No subcommand {part!r}")
    return cmd.callback


def patch_session_locals(
    mocker: Any,
    session_factory: Any,
    *module_paths: str,
) -> list:
    """Patch database.SessionLocal to redirect all db_session() calls to session_factory.

    All command modules use ``db_session()`` from ``database``, which calls
    ``SessionLocal()`` internally.  Patching the single source is sufficient
    to redirect every command's DB access to the shared integration-test
    database regardless of which modules are listed in *module_paths*.

    The *module_paths* parameter is accepted for backwards compatibility but
    is no longer used; a single patch on ``database.SessionLocal`` replaces
    all per-module patches.

    Args:
        mocker: The pytest-mock ``mocker`` fixture.
        session_factory: A SQLAlchemy sessionmaker (e.g. int_session_factory).
        *module_paths: Ignored. Kept for call-site compatibility.

    Returns:
        A list containing the single active patcher object.

    Example::

        patch_session_locals(
            mocker,
            int_session_factory,
            "commands.character_commands",
            "commands.wizard.completion",
        )
    """
    patcher = mocker.patch("database.SessionLocal", new=session_factory)
    return [patcher]
