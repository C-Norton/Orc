import discord
from discord.ext import commands
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

def register_meta_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="help", description="Show help for all bot commands")
    async def help_command(interaction: discord.Interaction) -> None:
        """Show help for all bot commands and the party system."""
        logger.debug(f"Command /help called by {interaction.user} (ID: {interaction.user.id})")
        embed = discord.Embed(
            title=Strings.HELP_TITLE,
            description=Strings.HELP_DESCRIPTION,
            color=discord.Color.gold()
        )

        embed.add_field(
            name=Strings.HELP_CHAR_MGMT_NAME,
            value=Strings.HELP_CHAR_MGMT_VALUE,
            inline=False
        )

        embed.add_field(
            name=Strings.HELP_COMBAT_NAME,
            value=Strings.HELP_COMBAT_VALUE,
            inline=False
        )

        embed.add_field(
            name=Strings.HELP_ROLLING_NAME,
            value=Strings.HELP_ROLLING_VALUE,
            inline=False
        )

        embed.add_field(
            name=Strings.HELP_HEALTH_NAME,
            value=Strings.HELP_HEALTH_VALUE,
            inline=False
        )

        embed.add_field(
            name=Strings.HELP_PARTIES_NAME,
            value=Strings.HELP_PARTIES_VALUE,
            inline=False
        )

        embed.add_field(
            name=Strings.HELP_ENCOUNTER_NAME,
            value=Strings.HELP_ENCOUNTER_VALUE,
            inline=False
        )

        embed.set_footer(text=Strings.HELP_FOOTER)
        
        await interaction.response.send_message(embed=embed)
