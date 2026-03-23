"""Developer notification utilities for the ORC bot.

Maintains a rolling buffer of the last 25 log lines and a separate 250-entry
warning buffer, and exposes helpers for sending DMs to the bot developer on
WARNING+ log events, command errors, background errors, and bot startup.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import os
import sys
import traceback
from typing import Optional

import discord

DEVELOPER_DISCORD_ID: int = 181919139751788545
_LOG_BUFFER_SIZE: int = 25
_WARNING_BUFFER_SIZE: int = 250

_client: Optional[discord.Client] = None
_log_buffer: collections.deque[str] = collections.deque(maxlen=_LOG_BUFFER_SIZE)
_warning_buffer: collections.deque[str] = collections.deque(maxlen=_WARNING_BUFFER_SIZE)
_total_buffered_count: int = 0

_dev_logger = logging.getLogger(__name__)


def set_discord_client(client: discord.Client) -> None:
    """Register the Discord client used to send developer DMs."""
    global _client
    _client = client


def buffer_log_line(line: str) -> None:
    """Append a formatted log line to the recent-log circular buffer."""
    global _total_buffered_count
    _log_buffer.append(line)
    _total_buffered_count += 1


def buffer_warning_line(line: str) -> None:
    """Append a formatted WARNING+ log line to the warning circular buffer."""
    _warning_buffer.append(line)


def get_buffer_stats() -> str:
    """Return diagnostic stats about the log buffer for use in !logs output."""
    return f"buffer: {len(_log_buffer)}/{_LOG_BUFFER_SIZE} entries, total ever buffered: {_total_buffered_count}"


def get_recent_logs() -> str:
    """Return the buffered log lines joined by newlines."""
    return "\n".join(_log_buffer) or "(no recent logs)"


def get_warning_logs_page(
    page: int = 0, page_size: int = 25
) -> tuple[list[str], int, int]:
    """Return a page of warning-buffer entries ordered most-recent-first.

    Args:
        page: Zero-based page index.
        page_size: Number of entries per page.

    Returns:
        Tuple of (entries_for_page, clamped_page, total_pages).
    """
    all_entries = list(reversed(list(_warning_buffer)))
    total_pages = max(1, math.ceil(len(all_entries) / page_size))
    clamped_page = max(0, min(page, total_pages - 1))
    start = clamped_page * page_size
    return all_entries[start : start + page_size], clamped_page, total_pages


async def _send_developer_dm(message: str) -> None:
    """Send a DM to the developer, writing failures to stderr.

    Failures are written to stderr rather than going back through the logging
    system to prevent an infinite loop (failed DM → error log → new DM attempt
    → failed DM → ...).
    """
    if _client is None:
        return
    try:
        developer_user = await _client.fetch_user(DEVELOPER_DISCORD_ID)
        if len(message) > 1950:
            message = message[:1950] + "\n… (truncated)"
        await developer_user.send(message)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(
            f"[dev_notifications] Failed to send developer DM: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def schedule_developer_dm(message: str) -> None:
    """Schedule a developer DM on the running event loop if one is available."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_developer_dm(message))
    except RuntimeError:
        pass  # No running event loop — bot not yet connected


async def notify_startup(applied_migrations: Optional[list[str]] = None) -> None:
    """Send a startup DM to the developer including DB type, migrations, and recent logs.

    Args:
        applied_migrations: List of migration descriptions applied during this
            boot.  Pass an empty list when the DB was already at head, or
            ``None`` when migration info is unavailable.
    """
    database_url = os.environ.get("DATABASE_URL", "sqlite:///dnd_bot.db")
    if "postgresql" in database_url.lower() or "postgres" in database_url.lower():
        db_type = "PostgreSQL"
    else:
        db_type = "SQLite"

    if applied_migrations is None:
        migration_line = "Migrations: (info unavailable)"
    elif not applied_migrations:
        migration_line = "Migrations: ran 0 migrations"
    else:
        bullet_list = "\n".join(f"  • {m}" for m in applied_migrations)
        migration_line = (
            f"Migrations: ran {len(applied_migrations)} migration(s):\n{bullet_list}"
        )

    recent = get_recent_logs()
    message = (
        f"**ORC Bot Started**\n"
        f"Database: `{db_type}`\n"
        f"{migration_line}\n"
        f"**Recent logs:**\n```\n{recent}\n```"
    )
    await _send_developer_dm(message)


async def notify_command_error(
    interaction: discord.Interaction,
    error: Exception,
) -> None:
    """Notify the developer of a command error and send the user a fallback reply.

    Sends the developer a DM containing the full traceback, the guild and user
    snowflakes, the full command text, and the last 10 log lines.  Then sends
    the generic error string to the user (via followup if already deferred).

    Args:
        interaction: The Discord interaction that triggered the error.
        error: The exception that was raised.
    """
    from utils.strings import Strings  # deferred to avoid circular import

    recent = get_recent_logs()
    error_text = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )

    command_name = interaction.command.name if interaction.command else "unknown"
    try:
        param_str = " ".join(
            f"{key}={value!r}" for key, value in vars(interaction.namespace).items()
        )
    except Exception:
        param_str = ""
    full_command = f"/{command_name} {param_str}".strip()

    dm_message = (
        f"**Command Error: `{full_command}`**\n"
        f"Guild: `{interaction.guild_id}`\n"
        f"User: `{interaction.user.id}` ({interaction.user})\n"
        f"**Error:**\n```\n{error_text[:700]}\n```\n"
        f"**Recent logs:**\n```\n{recent}\n```"
    )
    await _send_developer_dm(dm_message)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                Strings.DEVELOPER_NOTIFIED_ERROR, ephemeral=True
            )
        else:
            await interaction.response.send_message(
                Strings.DEVELOPER_NOTIFIED_ERROR, ephemeral=True
            )
    except Exception as exc:
        print(
            f"[dev_notifications] Failed to send error response to user: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


async def notify_guild_join(guild_name: str, guild_id: int, member_count: int) -> None:
    """Notify the developer when the bot joins a new guild.

    Args:
        guild_name: The human-readable name of the guild.
        guild_id: The guild's Discord snowflake ID.
        member_count: Approximate number of members in the guild.
    """
    message = (
        f"**ORC joined a new guild**\n"
        f"Name: `{guild_name}`\n"
        f"ID: `{guild_id}`\n"
        f"Members: `{member_count}`"
    )
    await _send_developer_dm(message)


async def notify_background_error(error: Exception, context: str = "") -> None:
    """Notify the developer of an error that occurred outside a command handler.

    Args:
        error: The exception that was raised.
        context: Human-readable description of where the error occurred.
    """
    recent = get_recent_logs()
    error_text = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )

    context_line = f"{context}\n" if context else ""
    message = (
        f"**Background Error**\n"
        f"{context_line}"
        f"**Error:**\n```\n{error_text[:700]}\n```\n"
        f"**Recent logs:**\n```\n{recent}\n```"
    )
    await _send_developer_dm(message)
