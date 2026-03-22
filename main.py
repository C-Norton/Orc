import os
import discord
from discord.ext import commands
import dotenv
from alembic.config import Config
from alembic import command as alembic_command
from database import SessionLocal
from models import Server
from commands.meta_commands import register_meta_commands
from commands.roll_commands import register_roll_commands
from commands.character_commands import register_character_commands
from commands.attack_commands import register_attack_commands
from commands.party_commands import register_party_commands
from commands.encounter_commands import register_encounter_commands
from commands.health_commands import register_health_commands
from commands.inspiration_commands import register_inspiration_commands
from commands.admin_commands import record_start_time, register_admin_commands
from commands.weapon_commands import register_weapon_commands
from utils.db_helpers import purge_server_data
from utils.dev_notifications import notify_background_error, notify_command_error, notify_startup, set_discord_client
from utils.logging_config import setup_logging, get_logger, set_guild_context
from utils.rate_limiter import check_rate_limit

# Load environment variables
dotenv.load_dotenv()
TOKEN = os.getenv("DISCORD_API_TOKEN")

# Setup logging
setup_logging()
logger = get_logger(__name__)


def run_migrations() -> None:
    """Apply any pending Alembic migrations.

    Safe to call unconditionally — Alembic is idempotent and will no-op when
    the database is already at head.  Works with both SQLite and PostgreSQL.
    """
    alembic_cfg = Config("alembic.ini")
    alembic_command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied (or already at head)")


# Define bot intents
intents = discord.Intents.default()
intents.message_content = True


class GuildContextTree(discord.app_commands.CommandTree):
    """CommandTree subclass that injects guild context into the logging system.

    Overrides ``call`` so that every slash-command invocation automatically
    sets the current guild's snowflake in the logging context variable.  This
    means all log messages emitted during a command handler automatically
    include the originating guild ID without any per-command boilerplate.
    """

    async def call(self, interaction: discord.Interaction) -> None:
        """Set guild logging context then dispatch the interaction."""
        if interaction.guild_id:
            set_guild_context(str(interaction.guild_id))
        await super().call(interaction)


class DnDBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents, tree_cls=GuildContextTree)

    async def setup_hook(self) -> None:
        """Called by the bot to perform asynchronous setup tasks."""
        run_migrations()
        # Register commands
        register_meta_commands(self)
        register_roll_commands(self)
        register_character_commands(self)
        register_attack_commands(self)
        register_party_commands(self)
        register_encounter_commands(self)
        register_health_commands(self)
        register_inspiration_commands(self)
        register_weapon_commands(self)
        register_admin_commands(self)

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError,
        ) -> None:
            """Fallback handler for unhandled app command errors."""
            original = getattr(error, "original", error)
            logger.error(
                f"Unhandled app command error from {interaction.user} "
                f"(guild {interaction.guild_id}): {type(original).__name__}: {original}",
                exc_info=original,
            )
            await notify_command_error(interaction, original)

        # This syncs the slash commands globally (or to specific guilds if needed)
        # Note: Global sync can take up to an hour to propagate.
        logger.info("Syncing slash commands with Discord...")
        await self.tree.sync()
        logger.info(f"Synced slash commands for {self.user}")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Check rate limits before every slash command."""
        if interaction.type == discord.InteractionType.application_command:
            if check_rate_limit(str(interaction.user.id), str(interaction.guild_id)):
                logger.warning(
                    f"Rate limit exceeded: user {interaction.user.id} "
                    f"({interaction.user}) sent >8 commands in 10s in guild {interaction.guild_id}"
                )
                try:
                    app_info = await self.application_info()
                    await app_info.owner.send(
                        f"\u26a0\ufe0f Rate limit alert: {interaction.user} (`{interaction.user.id}`) "
                        f"in guild `{interaction.guild_id}` exceeded 8 commands in 10s."
                    )
                    logger.debug(
                        f"Rate limit DM sent to owner for user {interaction.user.id}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to send rate limit DM to owner: {type(e).__name__}: {e}"
                    )

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.debug("Bot is ready and running")
        set_discord_client(self)
        record_start_time()
        await notify_startup()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Update the database when the bot joins a new server."""
        set_guild_context(str(guild.id))
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(guild.id)).first()
            if not server:
                server = Server(discord_id=str(guild.id), name=guild.name)
                db.add(server)
                db.commit()
                logger.info(f"Added new server: {guild.name} ({guild.id})")
        except Exception as e:
            logger.error(f"Error on guild join {guild.name}: {e}")
            await notify_background_error(
                e, context=f"Error in on_guild_join for {guild.name} ({guild.id})"
            )
        finally:
            db.close()

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Purge all server data when the bot is kicked or leaves a guild."""
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(guild.id)).first()
            if server:
                purge_server_data(db, server)
                db.commit()
                logger.info(
                    f"Purged all data for removed guild: {guild.name} ({guild.id})"
                )
            else:
                logger.info(
                    f"Bot removed from guild {guild.name} ({guild.id}) — no DB record found"
                )
        except Exception as e:
            db.rollback()
            logger.error(f"Error purging data for guild {guild.name} ({guild.id}): {e}")
            await notify_background_error(
                e, context=f"Error in on_guild_remove for {guild.name} ({guild.id})"
            )
        finally:
            db.close()


bot = DnDBot()

if __name__ == "__main__":
    if TOKEN:
        logger.info("Starting bot...")
        bot.run(TOKEN)
    else:
        logger.critical("Error: DISCORD_API_TOKEN not found in .env file.")
