import contextvars
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


class LogBufferHandler(logging.Handler):
    """Buffers every log record and DMs the developer on WARNING+ events.

    The buffer (maintained in ``dev_notifications``) always holds the last 10
    formatted lines regardless of level, so any WARNING/ERROR DM automatically
    includes recent DEBUG/INFO context.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Buffer this record; if WARNING or above, schedule a developer DM."""
        from utils.dev_notifications import (
            buffer_log_line,
            get_recent_logs,
            schedule_developer_dm,
        )

        try:
            formatted = self.format(record)
        except Exception:
            formatted = f"[format error] {record.getMessage()}"
        buffer_log_line(formatted)

        if record.levelno >= logging.WARNING:
            recent = get_recent_logs()
            message = (
                f"**{record.levelname}: `{record.name}`**\n"
                f"```\n{formatted[:800]}\n```\n"
                f"**Recent logs:**\n```\n{recent}\n```"
            )
            schedule_developer_dm(message)


def setup_logging():
    dotenv.load_dotenv()

    log_format = "%(asctime)s - %(name)s - %(levelname)s - [guild:%(guild_id)s] - %(message)s"
    formatter = _GuildAwareFormatter(log_format)

    # Root logger captures everything; handlers filter by level independently.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler: always active. In Docker, stdout is captured by the
    # container runtime and shipped to Cloud Logging by the Ops Agent.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

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

    # Buffer handler: captures all records for context and DMs developer on WARNING+.
    buffer_handler = LogBufferHandler()
    buffer_handler.setLevel(logging.DEBUG)
    buffer_handler.setFormatter(formatter)
    root_logger.addHandler(buffer_handler)

    # Silence noisy third-party libraries.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.info("Logging initialized")


def get_logger(name):
    return logging.getLogger(name)
