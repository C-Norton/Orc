"""Admin prefix commands for the bot developer.

All commands silently no-op for any user other than the developer.
These are prefix commands (``!cmd``) rather than slash commands so they are
invisible to regular users and do not appear in Discord's command picker.
"""

from __future__ import annotations

import time

import discord
from discord.ext import commands
from sqlalchemy import inspect as sa_inspect, text

from database import SessionLocal
from utils.dev_notifications import get_recent_logs
from utils.logging_config import get_logger

logger = get_logger(__name__)

DEVELOPER_DISCORD_ID: int = 181919139751788545

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
            await ctx.send(f"❌ Guild `{guild_id}` not found (bot may not be in it).")
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
            await ctx.send(f"❌ No writable text channel found in **{guild.name}**.")
            return

        await channel.send(message)
        await ctx.send(
            f"✅ Message sent to **#{channel.name}** in **{guild.name}**.", delete_after=10
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

        recent = get_recent_logs()
        # Truncate to stay within Discord's 2000-char limit
        if len(recent) > 1800:
            recent = "…(truncated)\n" + recent[-1800:]
        await ctx.send(f"**Recent logs:**\n```\n{recent}\n```")

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
            "`!help` — This list"
        )
        await ctx.send(help_text)
