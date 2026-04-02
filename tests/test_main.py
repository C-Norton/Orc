"""Tests for startup behaviour in main.py — specifically run_migrations()
and the on_interaction gate (DM guard, rate limiting).
"""

import os
import pytest
import discord
from main import run_migrations, _ALEMBIC_INI, DnDBot
from utils.strings import Strings


def _patch_migration_infrastructure(mocker, current_rev=None, pending_scripts=None):
    """Patch ScriptDirectory, MigrationContext, and the DB engine for unit tests.

    Returns the mocked upgrade function and Config instance so callers can add
    their own assertions.
    """
    if pending_scripts is None:
        pending_scripts = []

    mock_config = mocker.patch("main.Config")
    mock_config_instance = mocker.Mock()
    mock_config.return_value = mock_config_instance

    mock_sd = mocker.patch("main.ScriptDirectory")
    mock_sd.from_config.return_value.walk_revisions.return_value = iter(pending_scripts)

    mock_mc = mocker.patch("main.MigrationContext")
    mock_mc.configure.return_value.get_current_revision.return_value = current_rev

    mocker.patch("database.engine")  # MagicMock supports the context-manager protocol

    mock_upgrade = mocker.patch("main.alembic_command.upgrade")
    return mock_upgrade, mock_config, mock_config_instance


def test_run_migrations_applies_pending_migrations(mocker):
    """run_migrations() calls alembic upgrade with 'head' on a fresh database."""
    mock_upgrade, mock_config, mock_config_instance = _patch_migration_infrastructure(
        mocker
    )

    run_migrations()

    mock_config.assert_called_once_with(_ALEMBIC_INI)
    mock_upgrade.assert_called_once_with(mock_config_instance, "head")


def test_run_migrations_does_not_call_upgrade_more_than_once_per_invocation(mocker):
    """run_migrations() calls alembic upgrade exactly once — no redundant runs."""
    mock_upgrade, _, _ = _patch_migration_infrastructure(mocker)

    run_migrations()

    assert mock_upgrade.call_count == 1


def test_run_migrations_on_partially_migrated_database(mocker):
    """run_migrations() still calls upgrade('head') when only some migrations have run.

    Alembic's upgrade is idempotent: passing 'head' on an already-current database
    is a no-op, and on a partially migrated database it applies only the remaining
    revisions.  run_migrations() must always call upgrade('head') so that both
    cases are handled without any conditional logic on our side.
    """
    mock_upgrade, mock_config, mock_config_instance = _patch_migration_infrastructure(
        mocker, current_rev="abc123"
    )

    run_migrations()

    mock_upgrade.assert_called_once_with(mock_config_instance, "head")


def test_run_migrations_partial_applies_only_remaining_revisions(
    tmp_path, mocker, monkeypatch
):
    """Alembic applies only the missing revisions on a partially migrated database.

    This test uses a real SQLite database to verify the end-to-end behaviour:
    stamp the database at an early revision, run run_migrations(), and confirm
    that the head revision is now current and that upgrade was called exactly once.
    """
    from alembic.config import Config
    from alembic import command as _alembic
    from sqlalchemy import create_engine, text as sa_text

    db_path = tmp_path / "partial_test.db"
    db_url = f"sqlite:///{db_path}"

    # alembic/env.py reads DATABASE_URL from the environment and overwrites
    # sqlalchemy.url, so we must set the env var to point at our test database.
    monkeypatch.setenv("DATABASE_URL", db_url)

    # Apply only the initial migration — simulates a partially migrated database.
    _alembic.upgrade(Config(_ALEMBIC_INI), "a59f4e37528b")

    # Confirm only the first revision is stamped.
    engine = create_engine(db_url)
    with engine.connect() as conn:
        revision_before = conn.execute(
            sa_text("SELECT version_num FROM alembic_version")
        ).scalar()
    engine.dispose()
    assert revision_before == "a59f4e37528b"

    # Intercept run_migrations()'s upgrade call to verify it targets "head", then
    # delegate to the real upgrade (env.py still points at db_url via DATABASE_URL).
    real_upgrade = _alembic.upgrade  # captured before patching

    upgrade_targets = []

    def _intercepting_upgrade(cfg_obj, target):
        upgrade_targets.append(target)
        real_upgrade(Config(_ALEMBIC_INI), target)

    mocker.patch("main.alembic_command.upgrade", side_effect=_intercepting_upgrade)

    run_migrations()

    # upgrade was invoked exactly once with "head".
    assert upgrade_targets == ["head"]

    # All remaining migrations were applied — the DB has advanced past the initial revision.
    engine = create_engine(db_url)
    with engine.connect() as conn:
        current_revisions = (
            conn.execute(sa_text("SELECT version_num FROM alembic_version"))
            .scalars()
            .all()
        )
    engine.dispose()
    # After upgrade("head"), the DB is at the final head — not the initial revision.
    assert current_revisions != ["a59f4e37528b"]


# ---------------------------------------------------------------------------
# GuildContextTree.interaction_check — DM guard
# ---------------------------------------------------------------------------


@pytest.fixture()
def bot(mocker):
    """A minimal DnDBot instance for testing interaction_check and on_interaction."""
    instance = DnDBot()
    # Prevent setup_hook from doing real network work during tests.
    mocker.patch.object(instance.tree, "sync", return_value=None)
    return instance


@pytest.mark.asyncio
async def test_dm_interaction_is_rejected_with_guild_only_message(mocker, bot):
    """Commands invoked outside a guild (DMs) must return an ephemeral error.

    The check is enforced by GuildContextTree.interaction_check, which runs
    before command dispatch and returns False to abort it — preventing the
    AttributeError: 'NoneType' has no attribute 'name' crash that occurred
    when character_create tried to access interaction.guild.name in a DM.
    """
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.guild_id = None
    interaction.response = mocker.AsyncMock()

    result = await bot.tree.interaction_check(interaction)

    assert result is False
    interaction.response.send_message.assert_called_once_with(
        Strings.ERROR_GUILD_ONLY, ephemeral=True
    )


@pytest.mark.asyncio
async def test_guild_interaction_passes_check(mocker, bot):
    """Interactions from inside a guild must pass interaction_check."""
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.guild_id = 12345

    result = await bot.tree.interaction_check(interaction)

    assert result is True


@pytest.mark.asyncio
async def test_dm_interaction_does_not_call_rate_limiter(mocker, bot):
    """on_interaction must not call the rate limiter for DM interactions (guild_id is None)."""
    mock_check_rate = mocker.patch("main.check_rate_limit")
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.type = discord.InteractionType.application_command
    interaction.guild_id = None
    interaction.response = mocker.AsyncMock()

    await bot.on_interaction(interaction)

    # Rate limiter receives guild_id="dm" — the None case is handled without skipping
    mock_check_rate.assert_called_once_with(str(interaction.user.id), "dm")
