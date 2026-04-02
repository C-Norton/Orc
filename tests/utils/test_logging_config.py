"""Tests for utils/logging_config.py — covering uncovered paths."""

import logging

import pytest

import utils.dev_notifications as dn
from utils.logging_config import (
    _BufferingStreamHandler,
    _GuildAwareFormatter,
    _OrcLogger,
    _OrcOnlyFilter,
    get_logger,
    set_guild_context,
)


# ---------------------------------------------------------------------------
# Isolation fixture — reset dev_notifications state between every test
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
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    logger_name: str = "orc.test",
    level: int = logging.DEBUG,
    msg: str = "test message",
) -> logging.LogRecord:
    """Build a minimal LogRecord for use in unit tests."""
    return logging.LogRecord(
        name=logger_name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# set_guild_context / _GuildAwareFormatter.format
# ---------------------------------------------------------------------------


def test_set_guild_context_injects_guild_id_into_formatter():
    """When a guild context is set, the formatter must embed that guild ID."""
    set_guild_context("999888777")
    formatter = _GuildAwareFormatter("%(guild_id)s - %(message)s")
    record = _make_record(msg="hello")
    result = formatter.format(record)
    assert "999888777" in result


def test_guild_aware_formatter_uses_dash_when_no_context():
    """When no guild context is active (empty string), the formatter must show '-'."""
    set_guild_context("")  # explicitly clear any residual context
    formatter = _GuildAwareFormatter("%(guild_id)s - %(message)s")
    record = _make_record(msg="hello")
    result = formatter.format(record)
    assert result.startswith("- ")


def test_set_guild_context_value_is_reflected_on_record():
    """set_guild_context must update the ContextVar so subsequent format calls see it."""
    set_guild_context("111222333")
    formatter = _GuildAwareFormatter("%(guild_id)s")
    record = _make_record()
    formatter.format(record)
    assert record.guild_id == "111222333"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _OrcOnlyFilter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "logger_name",
    [
        "discord",
        "discord.gateway",
        "sqlalchemy",
        "sqlalchemy.engine",
        "asyncio",
        "alembic",
        "alembic.runtime.migration",
    ],
)
def test_orc_only_filter_blocks_third_party_loggers(logger_name: str):
    """Records from known third-party logger namespaces must be rejected."""
    orc_filter = _OrcOnlyFilter()
    assert orc_filter.filter(_make_record(logger_name=logger_name)) is False


@pytest.mark.parametrize(
    "logger_name",
    [
        "root",
        "__main__",
        "commands.roll_commands",
        "utils.dnd_logic",
        "utils.dev_notifications",
    ],
)
def test_orc_only_filter_accepts_orc_loggers(logger_name: str):
    """Records from ORC's own namespaces must pass through the filter."""
    orc_filter = _OrcOnlyFilter()
    assert orc_filter.filter(_make_record(logger_name=logger_name)) is True


# ---------------------------------------------------------------------------
# _BufferingStreamHandler.emit
# ---------------------------------------------------------------------------


@pytest.fixture()
def buffering_handler(mocker):
    """A _BufferingStreamHandler wired to an isolated test logger."""
    mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler = _BufferingStreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("test.buffering_handler")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield handler, logger
    logger.removeHandler(handler)
    logger.propagate = True


def test_emit_schedules_dm_for_warning_orc_record(mocker, buffering_handler):
    """WARNING records from an ORC logger must trigger schedule_developer_dm."""
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffering_handler
    logger.warning("something is wrong")
    mock_schedule.assert_called_once()
    assert "something is wrong" in mock_schedule.call_args[0][0]


def test_emit_schedules_dm_for_error_orc_record(mocker, buffering_handler):
    """ERROR records from an ORC logger must trigger schedule_developer_dm."""
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffering_handler
    logger.error("an error occurred")
    mock_schedule.assert_called_once()
    assert "an error occurred" in mock_schedule.call_args[0][0]


def test_emit_does_not_schedule_dm_for_info_orc_record(mocker, buffering_handler):
    """INFO records must NOT trigger a developer DM."""
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffering_handler
    logger.info("just an info message")
    mock_schedule.assert_not_called()


def test_emit_does_not_call_super_for_debug_records(mocker, buffering_handler):
    """Records below INFO must not be written to the stream (super().emit not called)."""
    handler, logger = buffering_handler
    mock_super_emit = mocker.patch.object(logging.StreamHandler, "emit")
    logger.debug("debug only")
    mock_super_emit.assert_not_called()


def test_emit_calls_super_for_info_records(mocker, buffering_handler):
    """Records at INFO+ must be forwarded to the stream via super().emit."""
    handler, logger = buffering_handler
    mock_super_emit = mocker.patch.object(logging.StreamHandler, "emit")
    logger.info("visible info")
    mock_super_emit.assert_called_once()


def test_emit_format_error_uses_fallback_message(mocker, buffering_handler):
    """When self.format() raises, the DM must use the fallback '[format error]' prefix."""
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffering_handler
    # Force format() to raise so the except branch is exercised
    mocker.patch.object(handler, "format", side_effect=Exception("formatter exploded"))
    logger.warning("raw warning text")
    mock_schedule.assert_called_once()
    dm_message = mock_schedule.call_args[0][0]
    assert "[format error]" in dm_message
    assert "raw warning text" in dm_message


def test_emit_dm_includes_recent_logs(mocker, buffering_handler):
    """The developer DM must include the recent log buffer snapshot."""
    mock_schedule = mocker.patch("utils.dev_notifications.schedule_developer_dm")
    handler, logger = buffering_handler
    dn._log_buffer.append("pre-existing context line")
    logger.warning("triggering warning")
    dm_message = mock_schedule.call_args[0][0]
    assert "pre-existing context line" in dm_message


# ---------------------------------------------------------------------------
# _OrcLogger._buffer — format error branch
# ---------------------------------------------------------------------------


def test_orc_logger_buffer_handles_format_error_gracefully(mocker):
    """When %-formatting fails, _buffer must fall back to str(msg) without raising."""
    mock_inner = mocker.MagicMock()
    mock_inner.name = "test.orc_logger"
    orc_logger = _OrcLogger(mock_inner)
    # Pass args that are incompatible with the format string to trigger the except branch
    orc_logger.info("no placeholders here", "unexpected", "extra args")
    # The log buffer should still contain the raw message string
    recent = dn.get_recent_logs()
    assert "no placeholders here" in recent


# ---------------------------------------------------------------------------
# _OrcLogger.critical and .exception
# ---------------------------------------------------------------------------


def test_orc_logger_critical_populates_both_buffers(mocker):
    """critical() must write to both the recent log buffer and the warning buffer."""
    mock_inner = mocker.MagicMock()
    mock_inner.name = "test.orc_logger"
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.critical("catastrophic failure")
    recent = dn.get_recent_logs()
    assert "catastrophic failure" in recent
    warning_entries, _, _ = dn.get_warning_logs_page(page=0, page_size=25)
    assert any("catastrophic failure" in entry for entry in warning_entries)


def test_orc_logger_critical_delegates_to_inner_logger(mocker):
    """critical() must forward the call to the underlying logging.Logger."""
    mock_inner = mocker.MagicMock()
    mock_inner.name = "test.orc_logger"
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.critical("must reach inner logger")
    mock_inner.critical.assert_called_once_with("must reach inner logger")


def test_orc_logger_exception_populates_both_buffers(mocker):
    """exception() must write to both the recent log buffer and the warning buffer."""
    mock_inner = mocker.MagicMock()
    mock_inner.name = "test.orc_logger"
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.exception("unhandled exception")
    recent = dn.get_recent_logs()
    assert "unhandled exception" in recent
    warning_entries, _, _ = dn.get_warning_logs_page(page=0, page_size=25)
    assert any("unhandled exception" in entry for entry in warning_entries)


def test_orc_logger_exception_delegates_to_inner_logger(mocker):
    """exception() must forward the call to the underlying logging.Logger."""
    mock_inner = mocker.MagicMock()
    mock_inner.name = "test.orc_logger"
    orc_logger = _OrcLogger(mock_inner)
    orc_logger.exception("must reach inner logger")
    mock_inner.exception.assert_called_once_with("must reach inner logger")


# ---------------------------------------------------------------------------
# setup_logging — LOG_LEVEL branch (file handlers skipped)
# ---------------------------------------------------------------------------


def test_setup_logging_skips_file_handlers_when_log_level_env_set(mocker, monkeypatch):
    """When LOG_LEVEL is set (e.g. in Docker), no RotatingFileHandler must be added."""
    from logging.handlers import RotatingFileHandler

    monkeypatch.setenv("LOG_LEVEL", "INFO")

    # Capture the root logger's handler list at the time setup_logging runs,
    # then restore it afterward so we don't pollute other tests.
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    # Patch load_dotenv so it doesn't touch the filesystem
    mocker.patch("dotenv.load_dotenv")

    from utils.logging_config import setup_logging

    try:
        setup_logging()
        added_handlers = [h for h in root_logger.handlers if h not in handlers_before]
        rotating_handlers = [
            h for h in added_handlers if isinstance(h, RotatingFileHandler)
        ]
        assert rotating_handlers == [], (
            "Expected no RotatingFileHandler when LOG_LEVEL env var is set, "
            f"but found: {rotating_handlers}"
        )
    finally:
        # Remove only the handlers that setup_logging added
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)
                handler.close()


def test_setup_logging_stream_handler_gates_output_at_info_level(mocker, monkeypatch):
    """The _BufferingStreamHandler added by setup_logging should write to stdout at INFO+,
    not at DEBUG, so that debug noise doesn't appear in the container log stream."""
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    mocker.patch("dotenv.load_dotenv")

    from utils.logging_config import setup_logging

    try:
        setup_logging()
        added_handlers = [h for h in root_logger.handlers if h not in handlers_before]
        stream_handlers = [
            h for h in added_handlers if isinstance(h, _BufferingStreamHandler)
        ]
        assert len(stream_handlers) == 1
        # The handler itself is set to DEBUG so all records reach emit(), but
        # _BufferingStreamHandler.emit only calls super().emit at INFO+.
        # Verify the handler level is DEBUG (not INFO) so ORC records reach emit()
        # and can be buffered even if they are below the stream threshold.
        assert stream_handlers[0].level == logging.DEBUG
    finally:
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)
                handler.close()


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


def test_get_logger_returns_orc_logger_instance():
    """get_logger must return an _OrcLogger, not a plain logging.Logger."""
    logger = get_logger("test.get_logger")
    assert isinstance(logger, _OrcLogger)


def test_get_logger_wraps_logger_with_correct_name():
    """The wrapped logger's name must match the argument passed to get_logger."""
    logger = get_logger("test.named_logger")
    assert logger._logger.name == "test.named_logger"
