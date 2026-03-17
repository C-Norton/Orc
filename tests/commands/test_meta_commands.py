import pytest
import discord
from tests.commands.conftest import get_callback
from commands.meta_commands import HELP_PAGES, help_message_owners, on_reaction_add, on_guild_join
from utils.strings import Strings


@pytest.fixture(autouse=True)
def clear_owners():
    """Ensure help_message_owners is clean before and after every test."""
    help_message_owners.clear()
    yield
    help_message_owners.clear()


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def test_help_command_sends_embed_and_adds_reactions(meta_bot, interaction, mocker):
    """The /help command sends a TOC embed and adds one reaction per page plus 🏠."""
    cb = get_callback(meta_bot, "help")

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = 12345
    interaction.original_response.return_value = mock_message

    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    _, kwargs = interaction.response.send_message.call_args
    embed = kwargs.get("embed")
    assert embed.title == Strings.HELP_TITLE
    assert Strings.HELP_DESCRIPTION in embed.description
    assert embed.footer.text == Strings.HELP_FOOTER

    # Owner recorded
    assert help_message_owners[12345] == interaction.user.id

    # One reaction per HELP_PAGES entry plus the 🏠 home button
    expected_emojis = list(HELP_PAGES.keys()) + ["🏠"]
    assert mock_message.add_reaction.call_count == len(expected_emojis)
    actual_emojis = [call.args[0] for call in mock_message.add_reaction.call_args_list]
    assert actual_emojis == expected_emojis


# ---------------------------------------------------------------------------
# on_reaction_add
# ---------------------------------------------------------------------------

async def test_on_reaction_add_switches_to_category_page(mocker):
    """Reacting with a category emoji edits the message to show that page."""
    user_id = 111
    message_id = 12345
    help_message_owners[message_id] = user_id

    mock_user = mocker.MagicMock(spec=discord.User)
    mock_user.id = user_id
    mock_user.bot = False

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = message_id

    emoji = "👤"
    mock_reaction = mocker.MagicMock(spec=discord.Reaction)
    mock_reaction.emoji = emoji
    mock_reaction.message = mock_message

    await on_reaction_add(mock_reaction, mock_user)

    mock_message.edit.assert_called_once()
    embed = mock_message.edit.call_args.kwargs.get("embed")
    title, content = HELP_PAGES[emoji]
    assert embed.title == f"{emoji} {title}"
    assert embed.description == content

    # Reaction removed using the same user object that was passed in
    mock_message.remove_reaction.assert_called_once_with(emoji, mock_user)


async def test_on_reaction_add_switches_to_home_page(mocker):
    """Reacting with 🏠 returns to the Table of Contents embed."""
    user_id = 111
    message_id = 12345
    help_message_owners[message_id] = user_id

    mock_user = mocker.MagicMock(spec=discord.User)
    mock_user.id = user_id
    mock_user.bot = False

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = message_id

    mock_reaction = mocker.MagicMock(spec=discord.Reaction)
    mock_reaction.emoji = "🏠"
    mock_reaction.message = mock_message

    await on_reaction_add(mock_reaction, mock_user)

    mock_message.edit.assert_called_once()
    embed = mock_message.edit.call_args.kwargs.get("embed")
    assert embed.title == Strings.HELP_TITLE
    assert Strings.HELP_DESCRIPTION in embed.description

    mock_message.remove_reaction.assert_called_once_with("🏠", mock_user)


async def test_on_reaction_add_ignores_bots(mocker):
    """Reactions from bot accounts are silently ignored."""
    mock_user = mocker.MagicMock(spec=discord.User)
    mock_user.bot = True

    mock_reaction = mocker.MagicMock(spec=discord.Reaction)

    await on_reaction_add(mock_reaction, mock_user)

    assert not mock_reaction.message.edit.called


async def test_on_reaction_add_ignores_different_user(meta_bot, interaction, mocker):
    """A reaction from a user who didn't open the help menu is ignored."""
    message_id = 12345
    help_message_owners[message_id] = interaction.user.id  # owner is 111

    different_user = mocker.MagicMock(spec=discord.User)
    different_user.id = 99999
    different_user.bot = False

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = message_id

    mock_reaction = mocker.MagicMock(spec=discord.Reaction)
    mock_reaction.message = mock_message

    # Drive the registered listener directly to avoid double-registering
    listener = meta_bot.extra_events.get("on_reaction_add")[0]
    await listener(mock_reaction, different_user)

    assert not mock_message.edit.called


async def test_on_reaction_add_ignores_unknown_emoji(mocker):
    """An emoji not in HELP_PAGES and not 🏠 produces no edit."""
    user_id = 111
    message_id = 12345
    help_message_owners[message_id] = user_id

    mock_user = mocker.MagicMock(spec=discord.User)
    mock_user.id = user_id
    mock_user.bot = False

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = message_id

    mock_reaction = mocker.MagicMock(spec=discord.Reaction)
    mock_reaction.emoji = "🤔"
    mock_reaction.message = mock_message

    await on_reaction_add(mock_reaction, mock_user)

    assert not mock_message.edit.called


async def test_on_reaction_add_handles_remove_reaction_error(mocker):
    """A Forbidden error on remove_reaction is swallowed; the edit still happens."""
    user_id = 111
    message_id = 12345
    help_message_owners[message_id] = user_id

    mock_user = mocker.MagicMock(spec=discord.User)
    mock_user.id = user_id
    mock_user.bot = False

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = message_id
    mock_message.remove_reaction.side_effect = discord.Forbidden(mocker.MagicMock(), "Forbidden")

    mock_reaction = mocker.MagicMock(spec=discord.Reaction)
    mock_reaction.emoji = "🏠"
    mock_reaction.message = mock_message

    await on_reaction_add(mock_reaction, mock_user)

    assert mock_message.edit.called
    mock_message.remove_reaction.assert_called_once()


# ---------------------------------------------------------------------------
# on_guild_join
# ---------------------------------------------------------------------------

async def test_on_guild_join_sends_welcome_to_system_channel(mocker):
    """Welcome message is sent to the guild's system channel when one exists."""
    mock_channel = mocker.AsyncMock(spec=discord.TextChannel)
    mock_channel.name = "general"

    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = mock_channel

    await on_guild_join(mock_guild)

    mock_channel.send.assert_called_once()
    msg = mock_channel.send.call_args.args[0]
    assert Strings.GUILD_JOIN_WELCOME == msg


async def test_on_guild_join_falls_back_to_text_channel(mocker):
    """When there is no system channel, the first writable text channel is used."""
    mock_channel = mocker.AsyncMock(spec=discord.TextChannel)
    mock_channel.name = "general"

    mock_perms = mocker.MagicMock(spec=discord.Permissions)
    mock_perms.send_messages = True
    mock_channel.permissions_for = mocker.MagicMock(return_value=mock_perms)

    mock_me = mocker.MagicMock()

    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = None
    mock_guild.text_channels = [mock_channel]
    mock_guild.me = mock_me

    await on_guild_join(mock_guild)

    mock_channel.send.assert_called_once()
    msg = mock_channel.send.call_args.args[0]
    assert Strings.GUILD_JOIN_WELCOME == msg


async def test_on_guild_join_skips_channel_without_send_permission(mocker):
    """A channel where the bot cannot send messages is skipped."""
    no_perm_channel = mocker.AsyncMock(spec=discord.TextChannel)
    no_perm_channel.name = "readonly"
    no_perm_perms = mocker.MagicMock(spec=discord.Permissions)
    no_perm_perms.send_messages = False
    no_perm_channel.permissions_for = mocker.MagicMock(return_value=no_perm_perms)

    ok_channel = mocker.AsyncMock(spec=discord.TextChannel)
    ok_channel.name = "general"
    ok_perms = mocker.MagicMock(spec=discord.Permissions)
    ok_perms.send_messages = True
    ok_channel.permissions_for = mocker.MagicMock(return_value=ok_perms)

    mock_me = mocker.MagicMock()

    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = None
    mock_guild.text_channels = [no_perm_channel, ok_channel]
    mock_guild.me = mock_me

    await on_guild_join(mock_guild)

    no_perm_channel.send.assert_not_called()
    ok_channel.send.assert_called_once()


async def test_on_guild_join_no_channel_does_not_raise(mocker):
    """If no suitable channel exists, nothing is sent and no exception is raised."""
    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = None
    mock_guild.text_channels = []
    mock_guild.me = mocker.MagicMock()

    # Must not raise
    await on_guild_join(mock_guild)


async def test_on_guild_join_forbidden_is_swallowed(mocker):
    """A Forbidden error from Discord when sending is logged but not re-raised."""
    mock_channel = mocker.AsyncMock(spec=discord.TextChannel)
    mock_channel.name = "general"
    mock_channel.send.side_effect = discord.Forbidden(mocker.MagicMock(), "Missing Permissions")

    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = mock_channel

    # Must not raise
    await on_guild_join(mock_guild)
