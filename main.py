import os
import discord
from discord.ext import commands
import dotenv
from database import SessionLocal
from models import Server
from commands.meta_commands import register_meta_commands
from commands.roll_commands import register_roll_commands
from commands.character_commands import register_character_commands
from commands.attack_commands import register_attack_commands
from commands.party_commands import register_party_commands

# Load environment variables
dotenv.load_dotenv()
TOKEN = os.getenv('DISCORD_API_TOKEN')

# Define bot intents
intents = discord.Intents.default()
intents.message_content = True

class DnDBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self) -> None:
        """Called by the bot to perform asynchronous setup tasks."""
        # Register commands
        register_meta_commands(self)
        register_roll_commands(self)
        register_character_commands(self)
        register_attack_commands(self)
        register_party_commands(self)
        
        # This syncs the slash commands globally (or to specific guilds if needed)
        # Note: Global sync can take up to an hour to propagate.
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Update the database when the bot joins a new server."""
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(guild.id)).first()
            if not server:
                server = Server(discord_id=str(guild.id), name=guild.name)
                db.add(server)
                db.commit()
                print(f"Added new server: {guild.name} ({guild.id})")
        finally:
            db.close()

bot = DnDBot()

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_API_TOKEN not found in .env file.")
