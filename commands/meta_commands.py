import discord
from discord.ext import commands
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

# Each entry: (emoji, short_button_label, embed_title, embed_content)
HELP_PAGES: list[tuple[str, str, str, str]] = [
    ("⭐", "Quick Start", Strings.HELP_GETTING_STARTED_NAME, Strings.HELP_GETTING_STARTED_VALUE),
    ("👤", "Characters", Strings.HELP_CHAR_MGMT_NAME, Strings.HELP_CHAR_MGMT_VALUE),
    ("⚔️", "Combat", Strings.HELP_COMBAT_NAME, Strings.HELP_COMBAT_VALUE),
    ("🎲", "Rolling", Strings.HELP_ROLLING_NAME, Strings.HELP_ROLLING_VALUE),
    ("❤️", "Health", Strings.HELP_HEALTH_NAME, Strings.HELP_HEALTH_VALUE),
    ("👥", "Parties", Strings.HELP_PARTIES_NAME, Strings.HELP_PARTIES_VALUE),
    ("🤼", "Encounters", Strings.HELP_ENCOUNTER_NAME, Strings.HELP_ENCOUNTER_VALUE),
    ("💫", "Inspiration", Strings.HELP_INSPIRATION_NAME, Strings.HELP_INSPIRATION_VALUE),
    ("👨‍🔧", "Credits", Strings.HELP_CREDITS_NAME, Strings.HELP_CREDITS_VALUE),
]


def _toc_embed() -> discord.Embed:
    """Build the table-of-contents embed."""
    embed = discord.Embed(
        title=Strings.HELP_TITLE,
        description=Strings.HELP_TOC_DESCRIPTION.format(description=Strings.HELP_DESCRIPTION),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=Strings.HELP_FOOTER)
    return embed


def _page_embed(title: str, content: str) -> discord.Embed:
    """Build a help-page embed."""
    embed = discord.Embed(
        title=title,
        description=content,
        color=discord.Color.gold(),
    )
    embed.set_footer(text=Strings.HELP_FOOTER)
    return embed


class _HelpPageButton(discord.ui.Button):
    """Navigate to a specific help page."""

    def __init__(self, emoji: str, label: str, embed_title: str, embed_content: str, row: int) -> None:
        super().__init__(emoji=emoji, label=label, style=discord.ButtonStyle.secondary, row=row)
        self._embed_title = embed_title
        self._embed_content = embed_content

    async def callback(self, interaction: discord.Interaction) -> None:
        """Edit the help message to show this page."""
        embed = _page_embed(self._embed_title, self._embed_content)
        await interaction.response.edit_message(embed=embed, view=self.view)


class _HelpHomeButton(discord.ui.Button):
    """Return to the help table of contents."""

    def __init__(self, row: int) -> None:
        super().__init__(emoji="🏠", label="Home", style=discord.ButtonStyle.primary, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Edit the help message to show the table of contents."""
        await interaction.response.edit_message(embed=_toc_embed(), view=self.view)


class HelpView(discord.ui.View):
    """Interactive help menu with button-based page navigation.

    Buttons are laid out four per row to stay within Discord's 5-button-per-row
    limit while keeping the home button visually separated on its own row.
    """

    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=300)
        self._owner_id = owner_id
        self.message: discord.Message | None = None

        for index, (emoji, label, embed_title, embed_content) in enumerate(HELP_PAGES):
            row = index // 4  # rows 0 and 1, four buttons each
            self.add_item(_HelpPageButton(emoji=emoji, label=label, embed_title=embed_title, embed_content=embed_content, row=row))

        self.add_item(_HelpHomeButton(row=2))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the user who opened this menu to interact with it."""
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(Strings.HELP_NOT_YOUR_MENU, ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Disable all buttons after the view times out."""
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


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


def register_meta_commands(bot: commands.Bot) -> None:
    """Register the /help command and guild join listener."""

    @bot.tree.command(name="help", description="Show help for all bot commands")
    async def help_command(interaction: discord.Interaction) -> None:
        """Show an interactive help menu with button navigation."""
        logger.debug(f"Command /help called by {interaction.user} (ID: {interaction.user.id})")

        view = HelpView(owner_id=interaction.user.id)
        await interaction.response.send_message(embed=_toc_embed(), view=view)
        view.message = await interaction.original_response()
        logger.info(f"/help served to user {interaction.user.id}")

    bot.add_listener(on_guild_join)
