"""Admin prefix commands for the bot developer.

All commands silently no-op for any user other than the developer.
These are prefix commands (``!cmd``) rather than slash commands so they are
invisible to regular users and do not appear in Discord's command picker.
"""

from __future__ import annotations

import os
import sys
import time

import discord
from discord.ext import commands
from sqlalchemy import inspect as sa_inspect, text

from database import SessionLocal
from utils.dev_notifications import get_buffer_stats, get_recent_logs, get_warning_logs_page
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

DEVELOPER_DISCORD_ID: int = 181919139751788545


class _WarningLogsView(discord.ui.View):
    """Interactive paginated view for browsing the warning/error log buffer.

    Entries are displayed most-recent-first.  Navigation buttons are
    automatically disabled at the start and end of the buffer.
    """

    PAGE_SIZE: int = 25

    def __init__(self, page: int, total_pages: int) -> None:
        super().__init__(timeout=120)
        self._page = page
        self._total_pages = total_pages
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        """Disable navigation buttons at the buffer boundaries."""
        self.prev_button.disabled = self._page == 0
        self.next_button.disabled = self._page >= self._total_pages - 1

    @staticmethod
    def build_content(page: int, total_pages: int) -> str:
        """Build the message string for *page* of the warning log buffer."""
        entries, _, _ = get_warning_logs_page(
            page=page, page_size=_WarningLogsView.PAGE_SIZE
        )
        body = "\n".join(entries) or "(no warning logs)"
        if len(body) > 1800:
            body = body[:1800] + "\n…"
        return Strings.ADMIN_WARNING_LOGS_DISPLAY.format(
            page=page + 1, total_pages=total_pages, body=body
        )

    @discord.ui.button(label=Strings.BUTTON_PREV_SHORT, style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to the previous page."""
        self._page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            content=self.build_content(self._page, self._total_pages), view=self
        )

    @discord.ui.button(label=Strings.BUTTON_NEXT_SHORT, style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to the next page."""
        self._page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            content=self.build_content(self._page, self._total_pages), view=self
        )

_start_time: float = 0.0


def record_start_time() -> None:
    """Record the bot's ready time for uptime calculations."""
    global _start_time
    _start_time = time.time()


def _uptime_string() -> str:
    """Return a human-readable uptime string."""
    if _start_time == 0.0:
        return "unknown"
    elapsed = int(time.time() - _start_time)
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    return f"{hours}h {minutes}m {seconds}s"


def _is_developer(ctx: commands.Context) -> bool:
    """Return True only if the message author is the developer."""
    return ctx.author.id == DEVELOPER_DISCORD_ID


def register_admin_commands(bot: commands.Bot) -> None:
    """Register admin prefix commands on the bot."""

    # Remove the default help command so !help can be reclaimed.
    bot.remove_command("help")

    @bot.command(name="message")
    async def admin_message(
        ctx: commands.Context, guild_id: int, *, message: str
    ) -> None:
        """Send a message to the general channel of a guild by snowflake.

        Usage: ``!message <guild_id> <message text>``
        Tries the guild's system channel first, then a channel named
        "general", then the first text channel the bot can write to.
        """
        if not _is_developer(ctx):
            return

        guild = bot.get_guild(guild_id)
        if guild is None:
            await ctx.send(
                Strings.ADMIN_GUILD_NOT_FOUND.format(guild_id=guild_id)
            )
            return

        channel = (
            guild.system_channel
            or discord.utils.get(guild.text_channels, name="general")
            or next(
                (
                    channel
                    for channel in guild.text_channels
                    if channel.permissions_for(guild.me).send_messages
                ),
                None,
            )
        )

        if channel is None:
            await ctx.send(
                Strings.ADMIN_NO_WRITABLE_CHANNEL.format(guild_name=guild.name)
            )
            return

        await channel.send(message)
        await ctx.send(
            Strings.ADMIN_MESSAGE_SENT.format(
                channel_name=channel.name, guild_name=guild.name
            ),
            delete_after=10,
        )
        logger.info(
            f"Admin !message sent to #{channel.name} in {guild.name} ({guild_id})"
        )

    @bot.command(name="stats")
    async def admin_stats(ctx: commands.Context) -> None:
        """Show bot uptime and row counts for every database table.

        Usage: ``!stats``
        """
        if not _is_developer(ctx):
            return

        uptime = _uptime_string()
        guild_count = len(bot.guilds)

        db = SessionLocal()
        try:
            inspector = sa_inspect(db.bind)
            table_names = sorted(
                name
                for name in inspector.get_table_names()
                if not name.startswith("_") and name != "alembic_version"
            )
            rows = []
            for table_name in table_names:
                count = db.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")  # noqa: S608
                ).scalar()
                rows.append(f"  {table_name}: {count}")
        finally:
            db.close()

        counts_block = "\n".join(rows) or "  (no tables found)"
        message = (
            f"**ORC Bot Stats**\n"
            f"Uptime: `{uptime}`\n"
            f"Guilds: `{guild_count}`\n"
            f"**Database row counts:**\n```\n{counts_block}\n```"
        )
        await ctx.send(message)

    @bot.command(name="logs")
    async def admin_logs(ctx: commands.Context) -> None:
        """Show the last 25 log lines.

        Usage: ``!logs``
        """
        if not _is_developer(ctx):
            return

        stats = get_buffer_stats()
        logger.debug(f"!logs invoked — {stats}")
        recent = get_recent_logs()
        # Truncate to stay within Discord's 2000-char limit
        if len(recent) > 1800:
            recent = "…(truncated)\n" + recent[-1800:]
        await ctx.send(Strings.ADMIN_LOGS_DISPLAY.format(stats=stats, recent=recent))

    @bot.command(name="restart")
    async def admin_restart(ctx: commands.Context) -> None:
        """Restart the bot process by re-executing the current Python interpreter.

        Sends an acknowledgement DM before exiting so the developer knows the
        restart was received.  The process manager (e.g. systemd or Docker
        restart policy) is expected to relaunch the bot automatically.

        Usage: ``!restart``
        """
        if not _is_developer(ctx):
            return

        logger.info(
            f"Admin !restart requested by {ctx.author} ({ctx.author.id})"
        )
        await ctx.send(Strings.ADMIN_RESTARTING, delete_after=5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    @bot.command(name="warninglogs")
    async def admin_warning_logs(ctx: commands.Context) -> None:
        """Show paginated WARNING+ log entries, most recent first.

        Displays up to 25 entries per page from the 250-entry warning buffer.
        Use the Prev/Next buttons to navigate.

        Usage: ``!warninglogs``
        """
        if not _is_developer(ctx):
            return

        _, _, total_pages = get_warning_logs_page(
            page=0, page_size=_WarningLogsView.PAGE_SIZE
        )
        view = _WarningLogsView(page=0, total_pages=total_pages)
        content = _WarningLogsView.build_content(page=0, total_pages=total_pages)
        await ctx.send(content, view=view)

    @bot.command(name="help")
    async def admin_help(ctx: commands.Context) -> None:
        """List all admin commands.

        Usage: ``!help``
        """
        if not _is_developer(ctx):
            return

        help_text = (
            "**ORC Admin Commands**\n"
            "`!message <guild_id> <message>` — Send a message to a guild's general channel\n"
            "`!stats` — Bot uptime and database row counts\n"
            "`!logs` — Last 25 log lines\n"
            "`!warninglogs` — Paginated WARNING+ log history (250 entries, most recent first)\n"
            "`!restart` — Restart the bot process\n"
            "`!help` — This list"
        )
        await ctx.send(help_text)
