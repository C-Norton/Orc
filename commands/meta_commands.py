import discord
from discord.ext import commands
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)
help_message_owners = {}

# Help pages mapping: emoji -> (Title, Description/Value)
HELP_PAGES = {
    "⭐": (Strings.HELP_GETTING_STARTED_NAME, Strings.HELP_GETTING_STARTED_VALUE),
    "👤": (Strings.HELP_CHAR_MGMT_NAME, Strings.HELP_CHAR_MGMT_VALUE),
    "⚔️": (Strings.HELP_COMBAT_NAME, Strings.HELP_COMBAT_VALUE),
    "🎲": (Strings.HELP_ROLLING_NAME, Strings.HELP_ROLLING_VALUE),
    "❤️": (Strings.HELP_HEALTH_NAME, Strings.HELP_HEALTH_VALUE),
    "👥": (Strings.HELP_PARTIES_NAME, Strings.HELP_PARTIES_VALUE),
    "🤼": (Strings.HELP_ENCOUNTER_NAME, Strings.HELP_ENCOUNTER_VALUE),
    "👨‍🔧": (Strings.HELP_CREDITS_NAME, Strings.HELP_CREDITS_VALUE)
}

async def on_guild_join(guild: discord.Guild) -> None:
    """Send a welcome message when the bot joins a new server.

    Tries the guild's system channel first, then falls back to the first text
    channel where the bot has permission to send messages.
    """
    channel = guild.system_channel
    if channel is None:
        channel = next(
            (
                c for c in guild.text_channels
                if c.permissions_for(guild.me).send_messages
            ),
            None,
        )

    if channel is None:
        logger.warning(f"No writable channel found in {guild.name} ({guild.id}) for welcome message")
        return

    try:
        await channel.send(Strings.GUILD_JOIN_WELCOME)
        logger.info(f"Sent welcome message to {guild.name} ({guild.id}) in #{channel.name}")
    except discord.Forbidden:
        logger.warning(f"No permission to send welcome message in {guild.name} ({guild.id})")
    except Exception as e:
        logger.error(f"Failed to send welcome message to {guild.name} ({guild.id}): {e}")


async def on_reaction_add(reaction: discord.Reaction, user: discord.User) -> None:
    """Handle reaction clicks on the help menu."""
    if user.bot:
        return

    # Check if the reaction is on a help message and by the correct user
    if reaction.message.id in help_message_owners and user.id == help_message_owners[reaction.message.id]:
        msg = reaction.message
        emoji = str(reaction.emoji)
        
        if emoji == "🏠":
            # Return to the Table of Contents
            embed = discord.Embed(
                title=Strings.HELP_TITLE,
                description=Strings.HELP_TOC_DESCRIPTION.format(description=Strings.HELP_DESCRIPTION),
                color=discord.Color.gold()
            )
        elif emoji in HELP_PAGES:
            # Switch to the selected help page
            title, content = HELP_PAGES[emoji]
            embed = discord.Embed(
                title=f"{emoji} {title}",
                description=content,
                color=discord.Color.gold()
            )
        else:
            return
            
        embed.set_footer(text=Strings.HELP_FOOTER)
        await msg.edit(embed=embed)

        # Remove the user's reaction for a better UI experience
        try:
            await msg.remove_reaction(reaction.emoji, user)
        except (discord.Forbidden, discord.HTTPException):
            # Bot might lack manage messages permission in DMs or certain channels
            pass

def register_meta_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="help", description="Show help for all bot commands")
    async def help_command(interaction: discord.Interaction) -> None:
        """Show help for all bot commands and the party system."""
        logger.debug(f"Command /help called by {interaction.user} (ID: {interaction.user.id})")
        
        # Initial embed: Table of Contents
        embed = discord.Embed(
            title=Strings.HELP_TITLE,
            description=Strings.HELP_TOC_DESCRIPTION.format(description=Strings.HELP_DESCRIPTION),
            color=discord.Color.gold()
        )
        embed.set_footer(text=Strings.HELP_FOOTER)

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        
        # Save message owner for reaction validation
        help_message_owners[message.id] = interaction.user.id
        
        # Add reactions for each category plus home
        for emoji in HELP_PAGES.keys():
            await message.add_reaction(emoji)
        await message.add_reaction("🏠")

    bot.add_listener(on_reaction_add)
    bot.add_listener(on_guild_join)