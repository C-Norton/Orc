import pytest
import discord
from tests.commands.conftest import get_callback
from commands.meta_commands import HELP_PAGES, HelpView, on_guild_join
from utils.strings import Strings


# ---------------------------------------------------------------------------
# /help — initial response
# ---------------------------------------------------------------------------


async def test_help_command_sends_toc_embed(meta_bot, interaction, mocker):
    """The /help command sends a TOC embed with a random tip in a dedicated field."""
    mocker.patch("commands.meta_commands.random.choice", return_value="A known tip")
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
    tip_field = next((f for f in embed.fields if f.name == "💡 Tip"), None)
    assert tip_field is not None
    assert "A known tip" in tip_field.value


async def test_help_command_sends_help_view(meta_bot, interaction, mocker):
    """The /help command attaches a HelpView with the correct owner."""
    cb = get_callback(meta_bot, "help")

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = 12345
    interaction.original_response.return_value = mock_message

    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    assert isinstance(view, HelpView)
    assert view._owner_id == interaction.user.id


async def test_help_command_has_button_per_page_plus_home(
    meta_bot, interaction, mocker
):
    """HelpView contains one button per HELP_PAGES entry plus a Home button."""
    cb = get_callback(meta_bot, "help")

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = 12345
    interaction.original_response.return_value = mock_message

    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    button_labels = [item.label for item in view.children]
    # One page button per HELP_PAGES entry
    for _, label, _, _ in HELP_PAGES:
        assert label in button_labels
    assert "Home" in button_labels


async def test_help_command_stores_message_reference(meta_bot, interaction, mocker):
    """The view's .message is set after the response is sent."""
    cb = get_callback(meta_bot, "help")

    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.id = 12345
    interaction.original_response.return_value = mock_message

    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    assert view.message is mock_message


# ---------------------------------------------------------------------------
# HelpView — page navigation buttons
# ---------------------------------------------------------------------------


async def test_page_button_edits_to_page_embed(mocker):
    """Clicking a page button edits the message to show that page's embed."""
    mocker.patch("commands.meta_commands.random.choice", return_value="Page tip")
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    emoji, label, embed_title, embed_content = HELP_PAGES[0]
    page_btn = next(
        item for item in view.children if getattr(item, "label", "") == label
    )

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = owner_id
    btn_interaction.response = mocker.AsyncMock()

    await page_btn.callback(btn_interaction)

    btn_interaction.response.edit_message.assert_called_once()
    _, kwargs = btn_interaction.response.edit_message.call_args
    embed = kwargs.get("embed")
    assert embed_title in embed.title
    assert embed.description == embed_content
    tip_field = next((f for f in embed.fields if f.name == "💡 Tip"), None)
    assert tip_field is not None
    assert "Page tip" in tip_field.value


async def test_page_button_tip_drawn_from_tips_list(mocker):
    """The page embed footer tip is chosen from Strings.TIPS."""
    mock_choice = mocker.patch("commands.meta_commands.random.choice")
    mock_choice.return_value = "Some tip"
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    _, label, _, _ = HELP_PAGES[0]
    page_btn = next(
        item for item in view.children if getattr(item, "label", "") == label
    )

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = owner_id
    btn_interaction.response = mocker.AsyncMock()

    await page_btn.callback(btn_interaction)

    mock_choice.assert_called_with(Strings.TIPS)


async def test_tip_changes_between_navigations(mocker):
    """Each navigation produces a fresh random tip — different calls to random.choice."""
    tips = ["First tip", "Second tip", "Third tip"]
    mock_choice = mocker.patch(
        "commands.meta_commands.random.choice", side_effect=tips
    )
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    _, label_a, _, _ = HELP_PAGES[0]
    _, label_b, _, _ = HELP_PAGES[1]
    btn_a = next(item for item in view.children if getattr(item, "label", "") == label_a)
    btn_b = next(item for item in view.children if getattr(item, "label", "") == label_b)
    home_btn = next(item for item in view.children if getattr(item, "label", "") == "Home")

    tip_values = []
    for btn in (btn_a, btn_b, home_btn):
        itr = mocker.AsyncMock(spec=discord.Interaction)
        itr.user = mocker.MagicMock()
        itr.user.id = owner_id
        itr.response = mocker.AsyncMock()
        await btn.callback(itr)
        _, kwargs = itr.response.edit_message.call_args
        embed = kwargs["embed"]
        tip_field = next((f for f in embed.fields if f.name == "💡 Tip"), None)
        tip_values.append(tip_field.value if tip_field else None)

    assert tip_values[0] != tip_values[1] != tip_values[2], (
        "Each navigation should produce a different tip"
    )
    assert mock_choice.call_count == 3


async def test_home_button_returns_to_toc(mocker):
    """Clicking the Home button edits the message back to the TOC embed."""
    mocker.patch("commands.meta_commands.random.choice", return_value="Home tip")
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    home_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Home"
    )

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = owner_id
    btn_interaction.response = mocker.AsyncMock()

    await home_btn.callback(btn_interaction)

    btn_interaction.response.edit_message.assert_called_once()
    _, kwargs = btn_interaction.response.edit_message.call_args
    embed = kwargs.get("embed")
    assert embed.title == Strings.HELP_TITLE
    assert Strings.HELP_DESCRIPTION in embed.description
    tip_field = next((f for f in embed.fields if f.name == "💡 Tip"), None)
    assert tip_field is not None
    assert "Home tip" in tip_field.value


async def test_all_page_buttons_produce_distinct_embeds(mocker):
    """Every page button renders a different embed title."""
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    titles = []
    for emoji, label, embed_title, embed_content in HELP_PAGES:
        btn = next(
            item for item in view.children if getattr(item, "label", "") == label
        )
        btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
        btn_interaction.user = mocker.MagicMock()
        btn_interaction.user.id = owner_id
        btn_interaction.response = mocker.AsyncMock()

        await btn.callback(btn_interaction)

        _, kwargs = btn_interaction.response.edit_message.call_args
        titles.append(kwargs["embed"].title)

    assert len(set(titles)) == len(HELP_PAGES), (
        "Each page button must render a unique embed title"
    )


# ---------------------------------------------------------------------------
# HelpView — interaction_check
# ---------------------------------------------------------------------------


async def test_interaction_check_allows_owner(mocker):
    """The owner's interactions pass the check."""
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = owner_id

    result = await view.interaction_check(btn_interaction)

    assert result is True
    btn_interaction.response.send_message.assert_not_called()


async def test_interaction_check_blocks_other_users(mocker):
    """Non-owner interactions are rejected with an ephemeral message."""
    owner_id = 111
    view = HelpView(owner_id=owner_id)

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = 99999
    btn_interaction.response = mocker.AsyncMock()

    result = await view.interaction_check(btn_interaction)

    assert result is False
    btn_interaction.response.send_message.assert_called_once()
    _, kwargs = btn_interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    assert (
        Strings.HELP_NOT_YOUR_MENU
        in btn_interaction.response.send_message.call_args.args[0]
    )


# ---------------------------------------------------------------------------
# HelpView — on_timeout
# ---------------------------------------------------------------------------


async def test_on_timeout_disables_all_buttons(mocker):
    """All buttons are disabled when the view times out."""
    view = HelpView(owner_id=111)
    mock_message = mocker.AsyncMock(spec=discord.Message)
    view.message = mock_message

    await view.on_timeout()

    for item in view.children:
        assert item.disabled is True
    mock_message.edit.assert_called_once()


async def test_on_timeout_without_message_does_not_raise(mocker):
    """on_timeout is safe when no message reference has been stored."""
    view = HelpView(owner_id=111)
    view.message = None

    # Must not raise
    await view.on_timeout()


async def test_on_timeout_swallows_http_exception(mocker):
    """An HTTPException while editing is swallowed and not re-raised."""
    view = HelpView(owner_id=111)
    mock_message = mocker.AsyncMock(spec=discord.Message)
    mock_message.edit.side_effect = discord.HTTPException(mocker.MagicMock(), "error")
    view.message = mock_message

    # Must not raise
    await view.on_timeout()


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
    mock_channel.send.side_effect = discord.Forbidden(
        mocker.MagicMock(), "Missing Permissions"
    )

    mock_guild = mocker.MagicMock(spec=discord.Guild)
    mock_guild.name = "Test Server"
    mock_guild.id = 12345
    mock_guild.system_channel = mock_channel

    # Must not raise
    await on_guild_join(mock_guild)


# ---------------------------------------------------------------------------
# /tip
# ---------------------------------------------------------------------------


async def test_tip_command_sends_message(meta_bot, interaction):
    cb = get_callback(meta_bot, "tip")
    await cb(interaction)
    interaction.response.send_message.assert_called_once()


async def test_tip_command_response_contains_tip_text(meta_bot, interaction, mocker):
    mocker.patch("commands.meta_commands.random.choice", return_value="Use autocomplete!")
    cb = get_callback(meta_bot, "tip")
    await cb(interaction)
    msg = interaction.response.send_message.call_args[0][0]
    assert "Use autocomplete!" in msg


async def test_tip_command_response_contains_prefix(meta_bot, interaction, mocker):
    mocker.patch("commands.meta_commands.random.choice", return_value="Any tip")
    cb = get_callback(meta_bot, "tip")
    await cb(interaction)
    msg = interaction.response.send_message.call_args[0][0]
    assert "💡" in msg


async def test_tip_command_chooses_from_tips_list(meta_bot, interaction, mocker):
    mock_choice = mocker.patch("commands.meta_commands.random.choice")
    mock_choice.return_value = "A tip"
    cb = get_callback(meta_bot, "tip")
    await cb(interaction)
    mock_choice.assert_called_once_with(Strings.TIPS)


async def test_tip_command_ephemeral(meta_bot, interaction, mocker):
    """Tips are ephemeral — visible only to the invoking user."""
    mocker.patch("commands.meta_commands.random.choice", return_value="tip")
    cb = get_callback(meta_bot, "tip")
    await cb(interaction)
    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
