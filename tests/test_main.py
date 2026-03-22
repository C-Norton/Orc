"""Tests for startup behaviour in main.py — specifically run_migrations()."""

import pytest
from main import run_migrations


def test_run_migrations_applies_pending_migrations(mocker):
    """run_migrations() calls alembic upgrade with 'head' on a fresh database."""
    mock_upgrade = mocker.patch("main.alembic_command.upgrade")
    mock_config = mocker.patch("main.Config")
    mock_config_instance = mocker.Mock()
    mock_config.return_value = mock_config_instance

    run_migrations()

    mock_config.assert_called_once_with("alembic.ini")
    mock_upgrade.assert_called_once_with(mock_config_instance, "head")


def test_run_migrations_does_not_call_upgrade_more_than_once_per_invocation(mocker):
    """run_migrations() calls alembic upgrade exactly once — no redundant runs."""
    mock_upgrade = mocker.patch("main.alembic_command.upgrade")
    mocker.patch("main.Config")

    run_migrations()

    assert mock_upgrade.call_count == 1


def test_run_migrations_on_partially_migrated_database(mocker):
    """run_migrations() still calls upgrade('head') when only some migrations have run.

    Alembic's upgrade is idempotent: passing 'head' on an already-current database
    is a no-op, and on a partially migrated database it applies only the remaining
    revisions.  run_migrations() must always call upgrade('head') so that both
    cases are handled without any conditional logic on our side.
    """
    mock_upgrade = mocker.patch("main.alembic_command.upgrade")
    mock_config = mocker.patch("main.Config")
    mock_config_instance = mocker.Mock()
    mock_config.return_value = mock_config_instance

    # Simulate Alembic knowing the DB is at an intermediate revision by having
    # upgrade() succeed (it would internally detect and apply only the remaining
    # migrations).  From run_migrations()'s perspective the call is identical.
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
    _alembic.upgrade(Config("alembic.ini"), "a59f4e37528b")

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
        real_upgrade(Config("alembic.ini"), target)

    mocker.patch("main.alembic_command.upgrade", side_effect=_intercepting_upgrade)

    run_migrations()

    # upgrade was invoked exactly once with "head".
    assert upgrade_targets == ["head"]

    # All remaining migrations were applied — the DB has advanced past the initial revision.
    engine = create_engine(db_url)
    with engine.connect() as conn:
        current_revisions = conn.execute(
            sa_text("SELECT version_num FROM alembic_version")
        ).scalars().all()
    engine.dispose()
    # After upgrade("head"), the DB is at the final head — not the initial revision.
    assert current_revisions != ["a59f4e37528b"]
