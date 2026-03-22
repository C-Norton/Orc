"""Tests for utils/dev_notifications.py and the LogBufferHandler."""

import asyncio
import logging

import discord
import pytest

import utils.dev_notifications as dn
from utils.dev_notifications import (
    DEVELOPER_DISCORD_ID,
    buffer_log_line,
    get_recent_logs,
    notify_background_error,
    notify_command_error,
    notify_startup,
    schedule_developer_dm,
    set_discord_client,
)
from utils.logging_config import LogBufferHandler
from utils.strings import Strings
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Isolation fixture — reset module-level state between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_dev_notifications_state():
    """Clear the log buffer and unset the Discord client before/after each test."""
    dn._log_buffer.clear()
    dn._client = None
    yield
    dn._log_buffer.clear()
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
