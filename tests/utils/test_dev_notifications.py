"""Tests for utils/dev_notifications.py and the LogBufferHandler."""

import asyncio
import logging

import discord
import pytest

import utils.dev_notifications as dn
from utils.dev_notifications import (
    DEVELOPER_DISCORD_ID,
    buffer_log_line,
    buffer_warning_line,
    get_buffer_stats,
    get_recent_logs,
    get_warning_logs_page,
    notify_background_error,
    notify_command_error,
    notify_guild_join,
    notify_startup,
    schedule_developer_dm,
    set_discord_client,
)
from utils.logging_config import LogBufferHandler, _OrcLogger, _OrcOnlyFilter
from utils.strings import Strings
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Isolation fixture — reset module-level state between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_dev_notifications_state():
    """Clear both log buffers and unset the Discord client before/after each test."""
    dn._log_buffer.clear()
    dn._warning_buffer.clear()
    dn._total_buffered_count = 0
    dn._client = None
    yield
    dn._log_buffer.clear()
    dn._warning_buffer.clear()
    dn._total_buffered_count = 0
    dn._client = None


# ---------------------------------------------------------------------------
# Log buffer
# ---------------------------------------------------------------------------


def test_get_recent_logs_empty_returns_placeholder():
    assert get_recent_logs() == "(no recent logs)"


def test_buffer_log_line_appends():
    buffer_log_line("alpha")
    buffer_log_line("beta")
    assert get_recent_logs() == "alpha\nbeta"


def test_buffer_respects_max_size():
    for i in range(dn._LOG_BUFFER_SIZE + 5):
        buffer_log_line(f"line {i}")
    lines = get_recent_logs().splitlines()
    assert len(lines) == dn._LOG_BUFFER_SIZE


def test_buffer_keeps_most_recent_lines():
    for i in range(dn._LOG_BUFFER_SIZE + 5):
        buffer_log_line(f"line {i}")
    recent = get_recent_logs()
    # Last line must be present; first lines must be evicted
    assert f"line {dn._LOG_BUFFER_SIZE + 4}" in recent
    assert "line 0" not in recent


def test_get_buffer_stats_shows_count_and_total():
    buffer_log_line("alpha")
    buffer_log_line("beta")
    stats = get_buffer_stats()
    assert "2/" in stats
    assert "total ever buffered: 2" in stats


def test_get_buffer_stats_total_exceeds_window_after_overflow():
    """total ever buffered keeps climbing even after the rolling window wraps."""
    overflow_count = dn._LOG_BUFFER_SIZE + 3
    for i in range(overflow_count):
        buffer_log_line(f"line {i}")
    stats = get_buffer_stats()
    assert f"total ever buffered: {overflow_count}" in stats
    assert f"{dn._LOG_BUFFER_SIZE}/{dn._LOG_BUFFER_SIZE}" in stats


# ---------------------------------------------------------------------------
# _OrcOnlyFilter
# ---------------------------------------------------------------------------


def _make_record(logger_name: str, level: int = logging.DEBUG) -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name,
        level=level,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )


@pytest.mark.parametrize(
    "logger_name",
    [
        "discord",
        "discord.gateway",
        "discord.client",
        "discord.app_commands.tree",
        "sqlalchemy",
        "sqlalchemy.engine",
        "asyncio",
        "alembic",
        "alembic.runtime.migration",
    ],
)
def test_orc_only_filter_blocks_third_party(logger_name):
    """Third-party loggers must be rejected so they cannot flood the buffer."""
    orc_filter = _OrcOnlyFilter()
    assert orc_filter.filter(_make_record(logger_name)) is False


@pytest.mark.parametrize(
    "logger_name",
    [
        "root",
        "__main__",
        "commands.party_commands",
        "commands.roll_commands",
        "utils.dnd_logic",
        "utils.dev_notifications",
    ],
)
def test_orc_only_filter_allows_orc_loggers(logger_name):
    """ORC's own loggers must pass through so command activity is buffered."""
    orc_filter = _OrcOnlyFilter()
    assert orc_filter.filter(_make_record(logger_name)) is True


# ---------------------------------------------------------------------------
# set_discord_client
# ---------------------------------------------------------------------------


def test_set_discord_client_stores_client(mocker):
    mock_client = mocker.Mock(spec=discord.Client)
    set_discord_client(mock_client)
    assert dn._client is mock_client


# ---------------------------------------------------------------------------
# _send_developer_dm
# ---------------------------------------------------------------------------


async def test_send_developer_dm_noop_when_no_client():
    """Should return silently when _client is None."""
    assert dn._client is None
    await dn._send_developer_dm("should not explode")


async def test_send_developer_dm_fetches_developer_and_sends(mocker):
    mock_user = mocker.AsyncMock()
    mock_client = mocker.AsyncMock(spec=discord.Client)
    mock_client.fetch_user = mocker.AsyncMock(return_value=mock_user)
    dn._client = mock_client

    await dn._send_developer_dm("hello developer")

    mock_client.fetch_user.assert_called_once_with(DEVELOPER_DISCORD_ID)
    mock_user.send.assert_called_once_with("hello developer")


async def test_send_developer_dm_truncates_long_message(mocker):
    mock_user = mocker.AsyncMock()
    mock_client = mocker.AsyncMock(spec=discord.Client)
    mock_client.fetch_user = mocker.AsyncMock(return_value=mock_user)
    dn._client = mock_client

    await dn._send_developer_dm("x" * 2000)

    sent = mock_user.send.call_args[0][0]
    assert len(sent) < 2000
    assert "truncated" in sent


async def test_send_developer_dm_silences_fetch_failure(mocker):
    mock_client = mocker.AsyncMock(spec=discord.Client)
    mock_client.fetch_user = mocker.AsyncMock(side_effect=Exception("network error"))
    dn._client = mock_client

    # Must not raise
    await dn._send_developer_dm("message")


async def test_send_developer_dm_silences_send_failure(mocker):
    mock_user = mocker.AsyncMock()
    mock_user.send = mocker.AsyncMock(side_effect=Exception("forbidden"))
    mock_client = mocker.AsyncMock(spec=discord.Client)
    mock_client.fetch_user = mocker.AsyncMock(return_value=mock_user)
    dn._client = mock_client

    await dn._send_developer_dm("message")


# ---------------------------------------------------------------------------
# schedule_developer_dm
# ---------------------------------------------------------------------------


def test_schedule_developer_dm_no_loop_silently_noop(mocker):
    """When there is no running event loop, must not raise."""
    mocker.patch("asyncio.get_running_loop", side_effect=RuntimeError)
    schedule_developer_dm("test")  # should not raise


async def test_schedule_developer_dm_creates_task(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm",
        new_callable=mocker.AsyncMock,
    )
    schedule_developer_dm("scheduled message")
    await asyncio.sleep(0)  # yield to allow the created task to run
    mock_send.assert_called_once_with("scheduled message")


# ---------------------------------------------------------------------------
# notify_startup
# ---------------------------------------------------------------------------


async def test_notify_startup_identifies_sqlite(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///dnd_bot.db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup()
    message = mock_send.call_args[0][0]
    assert "SQLite" in message
    assert "PostgreSQL" not in message


async def test_notify_startup_identifies_postgresql(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host/db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup()
    message = mock_send.call_args[0][0]
    assert "PostgreSQL" in message
    assert "SQLite" not in message


async def test_notify_startup_identifies_postgres_short_url(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host/db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup()
    assert "PostgreSQL" in mock_send.call_args[0][0]


async def test_notify_startup_includes_recent_logs(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    buffer_log_line("startup context line")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup()
    assert "startup context line" in mock_send.call_args[0][0]


async def test_notify_startup_uses_default_url_when_env_unset(mocker, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup()
    assert "SQLite" in mock_send.call_args[0][0]


async def test_notify_startup_shows_zero_migrations(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup(applied_migrations=[])
    assert "ran 0 migrations" in mock_send.call_args[0][0]


async def test_notify_startup_lists_applied_migrations(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup(applied_migrations=["add users table", "add guild_id column"])
    message = mock_send.call_args[0][0]
    assert "ran 2 migration(s)" in message
    assert "add users table" in message
    assert "add guild_id column" in message


async def test_notify_startup_shows_unavailable_when_none(mocker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_startup(applied_migrations=None)
    assert "unavailable" in mock_send.call_args[0][0]


# ---------------------------------------------------------------------------
# Warning buffer
# ---------------------------------------------------------------------------


def test_buffer_warning_line_appends():
    buffer_warning_line("alpha warning")
    buffer_warning_line("beta error")
    all_entries, _, _ = get_warning_logs_page(page=0, page_size=100)
    # most-recent-first, so beta is first
    assert all_entries[0] == "beta error"
    assert all_entries[1] == "alpha warning"


def test_warning_buffer_respects_max_size():
    for i in range(dn._WARNING_BUFFER_SIZE + 10):
        buffer_warning_line(f"warn {i}")
    all_entries, _, _ = get_warning_logs_page(page=0, page_size=dn._WARNING_BUFFER_SIZE + 100)
    assert len(all_entries) == dn._WARNING_BUFFER_SIZE


def test_get_warning_logs_page_empty():
    entries, page, total_pages = get_warning_logs_page()
    assert entries == []
    assert page == 0
    assert total_pages == 1


def test_get_warning_logs_page_single_page():
    for i in range(10):
        buffer_warning_line(f"warn {i}")
    entries, page, total_pages = get_warning_logs_page(page=0, page_size=25)
    assert len(entries) == 10
    assert page == 0
    assert total_pages == 1
    # most-recent-first
    assert entries[0] == "warn 9"
    assert entries[-1] == "warn 0"


def test_get_warning_logs_page_pagination():
    for i in range(60):
        buffer_warning_line(f"warn {i}")
    entries_p0, _, total = get_warning_logs_page(page=0, page_size=25)
    entries_p1, _, _ = get_warning_logs_page(page=1, page_size=25)
    entries_p2, _, _ = get_warning_logs_page(page=2, page_size=25)
    assert total == 3
    assert len(entries_p0) == 25
    assert len(entries_p1) == 25
    assert len(entries_p2) == 10
    # no overlap
    assert set(entries_p0).isdisjoint(entries_p1)


def test_get_warning_logs_page_clamps_out_of_range():
    buffer_warning_line("only entry")
    entries, clamped_page, total_pages = get_warning_logs_page(page=99, page_size=25)
    assert clamped_page == 0
    assert total_pages == 1
    assert len(entries) == 1


# ---------------------------------------------------------------------------
# _OrcLogger
# ---------------------------------------------------------------------------


def test_orc_logger_info_populates_recent_buffer(mocker):
    """_OrcLogger.info() must write to the recent log buffer directly."""
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.info("hello from info")
    assert "hello from info" in get_recent_logs()


def test_orc_logger_debug_populates_recent_buffer(mocker):
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.debug("debug message")
    assert "debug message" in get_recent_logs()


def test_orc_logger_warning_populates_both_buffers(mocker):
    """WARNING+ messages must appear in both the recent buffer and the warning buffer."""
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.warning("something suspicious")
    assert "something suspicious" in get_recent_logs()
    entries, _, _ = get_warning_logs_page(page=0, page_size=25)
    assert any("something suspicious" in e for e in entries)


def test_orc_logger_error_populates_both_buffers(mocker):
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.error("critical failure")
    assert "critical failure" in get_recent_logs()
    entries, _, _ = get_warning_logs_page(page=0, page_size=25)
    assert any("critical failure" in e for e in entries)


def test_orc_logger_debug_does_not_populate_warning_buffer(mocker):
    """DEBUG messages must NOT appear in the warning buffer."""
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.debug("just debugging")
    entries, _, _ = get_warning_logs_page(page=0, page_size=25)
    assert entries == []


def test_orc_logger_delegates_to_inner_logger(mocker):
    """_OrcLogger must still call the underlying logger for normal propagation."""
    mock_inner = mocker.MagicMock()
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.info("propagate me")
    mock_inner.info.assert_called_once_with("propagate me")


# ---------------------------------------------------------------------------
# notify_command_error
# ---------------------------------------------------------------------------


async def test_notify_command_error_dm_contains_guild_and_user(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker, user_id=555, guild_id=777)
    interaction.command = mocker.Mock()
    interaction.command.name = "roll"
    interaction.response.is_done = mocker.Mock(return_value=False)

    await notify_command_error(interaction, ValueError("bad input"))

    message = mock_send.call_args[0][0]
    assert "777" in message  # guild_id
    assert "555" in message  # user_id


async def test_notify_command_error_dm_contains_command_name(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "weapon"
    interaction.response.is_done = mocker.Mock(return_value=False)

    await notify_command_error(interaction, RuntimeError("crash"))

    assert "weapon" in mock_send.call_args[0][0]


async def test_notify_command_error_dm_contains_traceback(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "roll"
    interaction.response.is_done = mocker.Mock(return_value=False)

    try:
        raise RuntimeError("specific error text")
    except RuntimeError as error:
        await notify_command_error(interaction, error)

    message = mock_send.call_args[0][0]
    assert "RuntimeError" in message
    assert "specific error text" in message


async def test_notify_command_error_dm_contains_recent_logs(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    buffer_log_line("recent context log")
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "roll"
    interaction.response.is_done = mocker.Mock(return_value=False)

    await notify_command_error(interaction, RuntimeError("err"))

    assert "recent context log" in mock_send.call_args[0][0]


async def test_notify_command_error_responds_with_send_message_when_not_deferred(mocker):
    mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "roll"
    interaction.response.is_done = mocker.Mock(return_value=False)

    await notify_command_error(interaction, RuntimeError("err"))

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert Strings.DEVELOPER_NOTIFIED_ERROR in args[0]
    assert kwargs.get("ephemeral") is True


async def test_notify_command_error_uses_followup_when_already_deferred(mocker):
    mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "weapon"
    interaction.response.is_done = mocker.Mock(return_value=True)

    await notify_command_error(interaction, RuntimeError("api down"))

    interaction.response.send_message.assert_not_called()
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    assert Strings.DEVELOPER_NOTIFIED_ERROR in args[0]
    assert kwargs.get("ephemeral") is True


async def test_notify_command_error_handles_unknown_command(mocker):
    """When interaction.command is None, command name should fall back to 'unknown'."""
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = None
    interaction.response.is_done = mocker.Mock(return_value=False)

    await notify_command_error(interaction, RuntimeError("err"))

    assert "unknown" in mock_send.call_args[0][0]


async def test_notify_command_error_silences_user_response_failure(mocker):
    """If sending the error reply to the user fails, must not propagate."""
    mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    interaction = make_interaction(mocker)
    interaction.command = mocker.Mock()
    interaction.command.name = "roll"
    interaction.response.is_done = mocker.Mock(return_value=False)
    interaction.response.send_message = mocker.AsyncMock(
        side_effect=Exception("discord error")
    )

    await notify_command_error(interaction, RuntimeError("err"))


# ---------------------------------------------------------------------------
# notify_background_error
# ---------------------------------------------------------------------------


async def test_notify_background_error_includes_context(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_background_error(RuntimeError("boom"), context="guild join handler")
    message = mock_send.call_args[0][0]
    assert "guild join handler" in message
    assert "RuntimeError" in message
    assert "boom" in message


async def test_notify_background_error_no_context(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_background_error(ValueError("oops"))
    message = mock_send.call_args[0][0]
    assert "Background Error" in message
    assert "ValueError" in message


async def test_notify_background_error_includes_recent_logs(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    buffer_log_line("background context log")
    await notify_background_error(RuntimeError("err"))
    assert "background context log" in mock_send.call_args[0][0]


# ---------------------------------------------------------------------------
# LogBufferHandler
# ---------------------------------------------------------------------------


@pytest.fixture()
def buffer_handler(mocker):
    """A configured LogBufferHandler attached to a fresh test logger."""
    mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler = LogBufferHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("test.log_buffer_handler")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield handler, logger
    logger.removeHandler(handler)
    logger.propagate = True


def test_log_buffer_handler_buffers_debug_lines(buffer_handler):
    handler, logger = buffer_handler
    logger.debug("debug line")
    assert "debug line" in get_recent_logs()


def test_log_buffer_handler_buffers_info_lines(buffer_handler):
    handler, logger = buffer_handler
    logger.info("info line")
    assert "info line" in get_recent_logs()


def test_log_buffer_handler_no_dm_for_debug(mocker, buffer_handler):
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffer_handler
    logger.debug("debug only")
    mock_schedule.assert_not_called()


def test_log_buffer_handler_no_dm_for_info(mocker, buffer_handler):
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffer_handler
    logger.info("info only")
    mock_schedule.assert_not_called()


def test_log_buffer_handler_dms_on_warning(mocker, buffer_handler):
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffer_handler
    logger.warning("something suspicious")
    mock_schedule.assert_called_once()
    assert "something suspicious" in mock_schedule.call_args[0][0]


def test_log_buffer_handler_dms_on_error(mocker, buffer_handler):
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffer_handler
    logger.error("an error occurred")
    mock_schedule.assert_called_once()
    assert "an error occurred" in mock_schedule.call_args[0][0]


def test_log_buffer_handler_warning_dm_includes_recent_context(mocker, buffer_handler):
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffer_handler
    logger.info("pre-warning context")
    logger.warning("warning event")
    dm_message = mock_schedule.call_args[0][0]
    assert "pre-warning context" in dm_message
    assert "warning event" in dm_message


# ---------------------------------------------------------------------------
# send_developer_dm — failure handling
# ---------------------------------------------------------------------------


async def test_send_developer_dm_failure_writes_to_stderr_not_logger(mocker, capsys):
    """DM send failures must print to stderr rather than logging, to prevent
    an infinite loop where a failed DM triggers another DM attempt via the
    WARNING+ log buffer handler."""
    mock_user = mocker.AsyncMock()
    mock_user.send = mocker.AsyncMock(side_effect=Exception("forbidden"))
    mock_client = mocker.AsyncMock(spec=discord.Client)
    mock_client.fetch_user = mocker.AsyncMock(return_value=mock_user)
    dn._client = mock_client

    await dn._send_developer_dm("hello")

    captured = capsys.readouterr()
    assert "forbidden" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# notify_guild_join
# ---------------------------------------------------------------------------


async def test_notify_guild_join_sends_dm(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_guild_join("Test Server", 123456789, 42)

    message = mock_send.call_args[0][0]
    assert "Test Server" in message
    assert "123456789" in message
    assert "42" in message


async def test_notify_guild_join_dm_includes_guild_name_and_id(mocker):
    mock_send = mocker.patch(
        "utils.dev_notifications._send_developer_dm", new_callable=mocker.AsyncMock
    )
    await notify_guild_join("Dungeons & Discord", 987654321, 100)

    message = mock_send.call_args[0][0]
    assert "Dungeons & Discord" in message
    assert "987654321" in message
