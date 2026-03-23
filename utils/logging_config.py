import contextvars
import datetime
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import dotenv

# ---------------------------------------------------------------------------
# Guild logging context
# ---------------------------------------------------------------------------

_guild_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "guild_id", default=""
)


def set_guild_context(guild_id: str) -> None:
    """Set the current guild ID for inclusion in log messages.

    Call this at the start of any coroutine that processes a guild interaction
    (slash commands, event handlers, etc.).  Because this uses a
    ``contextvars.ContextVar``, the value is scoped to the current asyncio
    task and never leaks to unrelated tasks.

    Args:
        guild_id: The Discord guild (server) snowflake as a string.
    """
    _guild_id_var.set(guild_id)


class _GuildAwareFormatter(logging.Formatter):
    """Formatter that injects the current guild ID into every log record.

    Sets ``record.guild_id`` directly inside ``format()`` so the value is
    always present regardless of how the record reached this formatter
    (direct log call vs. propagation from a child logger).  When no guild
    context is active the field shows ``"-"``.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.guild_id = _guild_id_var.get() or "-"  # type: ignore[attr-defined]
        return super().format(record)


_THIRD_PARTY_LOGGER_PREFIXES: tuple[str, ...] = (
    "discord.",
    "discord",
    "sqlalchemy.",
    "sqlalchemy",
    "asyncio",
    "alembic.",
    "alembic",
)


class _OrcOnlyFilter(logging.Filter):
    """Accepts only log records originating from ORC's own loggers.

    Filters out third-party library noise (discord.py, SQLAlchemy, asyncio,
    Alembic) so the developer log buffer stays focused on bot activity.
    Records from the root logger (name == "root") are also accepted since
    ORC uses ``logging.info(...)`` directly during startup.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True only for records from ORC or root loggers."""
        return not record.name.startswith(_THIRD_PARTY_LOGGER_PREFIXES)


class _BufferingStreamHandler(logging.StreamHandler):
    """StreamHandler that also buffers ORC records and DMs the developer on WARNING+.

    Combines the console handler and the former ``LogBufferHandler`` into one.
    Using a ``StreamHandler`` subclass (rather than a plain ``Handler``) ensures
    the buffer receives async log records — plain ``Handler`` subclasses can
    silently lose records that are propagated from child loggers inside the
    asyncio event loop.

    * All ORC records (DEBUG+) are buffered via ``dev_notifications``.
    * Only records at ``_CONSOLE_LEVEL`` (INFO) or above are written to the stream.
    * WARNING+ ORC records also schedule a developer DM with recent log context.
    * Third-party library records (discord, sqlalchemy, asyncio, alembic) bypass
      the buffer/DM path but still reach the stream at INFO+.
    """

    _CONSOLE_LEVEL: int = logging.INFO
    _orc_filter: _OrcOnlyFilter = _OrcOnlyFilter()

    def emit(self, record: logging.LogRecord) -> None:
        """Schedule a developer DM for WARNING+ ORC records; write to stream at INFO+.

        Buffering is handled by ``_OrcLogger`` directly on each log call.  This
        handler is responsible only for the WARNING+ developer-DM path and for
        writing records to stdout.
        """
        if self._orc_filter.filter(record) and record.levelno >= logging.WARNING:
            from utils.dev_notifications import get_recent_logs, schedule_developer_dm

            try:
                formatted = self.format(record)
            except Exception:
                formatted = f"[format error] {record.getMessage()}"

            recent = get_recent_logs()
            message = (
                f"**{record.levelname}: `{record.name}`**\n"
                f"```\n{formatted[:800]}\n```\n"
                f"**Recent logs:**\n```\n{recent}\n```"
            )
            schedule_developer_dm(message)

        if record.levelno >= self._CONSOLE_LEVEL:
            super().emit(record)


# Keep the old name available so existing imports in tests don't break.
LogBufferHandler = _BufferingStreamHandler


class _OrcLogger:
    """Proxy logger that directly populates the dev-notification buffers.

    Wraps a standard :class:`logging.Logger` so that every log call
    simultaneously:

    - Dispatches through the normal Python logging machinery (handlers,
      propagation, file output, etc.).
    - Directly appends to the in-memory buffers in ``dev_notifications``
      to guarantee the buffer is always populated regardless of whether
      handler propagation is working correctly in the asyncio event loop.

    Use :func:`get_logger` to obtain instances; do not instantiate directly.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _buffer(self, level: int, msg: str, *args: object) -> None:
        """Format *msg* and push it directly into the dev-notification buffers."""
        from utils.dev_notifications import buffer_log_line, buffer_warning_line

        try:
            formatted_msg = str(msg) % args if args else str(msg)
        except Exception:
            formatted_msg = str(msg)

        guild_id = _guild_id_var.get() or "-"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        level_name = logging.getLevelName(level)
        line = (
            f"{timestamp} - {self._logger.name} - {level_name}"
            f" - [guild:{guild_id}] - {formatted_msg}"
        )
        buffer_log_line(line)
        if level >= logging.WARNING:
            buffer_warning_line(line)

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log a DEBUG-level message."""
        self._buffer(logging.DEBUG, msg, *args)
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log an INFO-level message."""
        self._buffer(logging.INFO, msg, *args)
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log a WARNING-level message."""
        self._buffer(logging.WARNING, msg, *args)
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log an ERROR-level message."""
        self._buffer(logging.ERROR, msg, *args)
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log a CRITICAL-level message."""
        self._buffer(logging.CRITICAL, msg, *args)
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log an ERROR-level message with exception traceback."""
        self._buffer(logging.ERROR, msg, *args)
        self._logger.exception(msg, *args, **kwargs)


def setup_logging():
    dotenv.load_dotenv()

    log_format = "%(asctime)s - %(name)s - %(levelname)s - [guild:%(guild_id)s] - %(message)s"
    formatter = _GuildAwareFormatter(log_format)

    # Root logger captures everything; handlers filter by level independently.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Combined console + buffer handler.  Level is DEBUG so all ORC records
    # reach emit(); the handler itself gates stream output at INFO+.
    console_buffer_handler = _BufferingStreamHandler(sys.stdout)
    console_buffer_handler.setLevel(logging.DEBUG)
    console_buffer_handler.setFormatter(formatter)
    root_logger.addHandler(console_buffer_handler)

    # File handlers: only in local development (no LOG_LEVEL env var).
    # In Docker, LOG_LEVEL is injected via /etc/orc-bot.env, so file handlers
    # are skipped — the container filesystem is ephemeral and stdout suffices.
    if not os.environ.get("LOG_LEVEL"):
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        info_file_handler = RotatingFileHandler(
            os.path.join(log_dir, "bot.log"),
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
        )
        info_file_handler.setLevel(logging.INFO)
        info_file_handler.setFormatter(formatter)
        root_logger.addHandler(info_file_handler)

        debug_file_handler = RotatingFileHandler(
            os.path.join(log_dir, "bot_debug.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
        )
        debug_file_handler.setLevel(logging.DEBUG)
        debug_file_handler.setFormatter(formatter)
        root_logger.addHandler(debug_file_handler)

    # Silence noisy third-party libraries.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    handler_names = [type(h).__name__ for h in root_logger.handlers]
    logging.info("Logging initialized")
    logging.debug(
        f"Root logger has {len(root_logger.handlers)} handler(s): {handler_names}"
    )


def get_logger(name: str) -> _OrcLogger:
    """Return an :class:`_OrcLogger` wrapping the standard logger for *name*.

    Use this instead of ``logging.getLogger`` throughout the ORC codebase so
    that every log call also populates the in-memory dev-notification buffers
    directly, bypassing any handler propagation issues.
    """
    return _OrcLogger(logging.getLogger(name))
