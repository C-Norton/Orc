"""Tests for commands/admin_commands.py.

Admin commands are prefix commands (``!cmd``) that silently no-op for any
user other than the developer.  Tests use a mock ``commands.Context`` rather
than a ``discord.Interaction``.
"""

import pytest
import discord
from discord.ext import commands

from commands.admin_commands import (
    DEVELOPER_DISCORD_ID,
    _WarningLogsView,
    _is_developer,
    _uptime_string,
    record_start_time,
    register_admin_commands,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NON_DEVELOPER_ID = 999999999


def make_bot() -> commands.Bot:
    """Create a minimal prefix-command bot for testing."""
    return commands.Bot(command_prefix="!", intents=discord.Intents.none())


def make_ctx(mocker, author_id: int = DEVELOPER_DISCORD_ID) -> commands.Context:
    """Build a mock commands.Context."""
    ctx = mocker.Mock(spec=commands.Context)
    author = mocker.Mock()
    author.id = author_id
    author.__str__ = mocker.Mock(return_value=f"TestUser#{author_id}")
    ctx.author = author
    ctx.send = mocker.AsyncMock()
    return ctx


@pytest.fixture
def admin_bot(session_factory, mocker):
    """Bot with admin commands registered and SessionLocal patched."""
    bot = make_bot()
    mocker.patch("database.SessionLocal", new=session_factory)
    register_admin_commands(bot)
    return bot


def get_prefix_callback(bot: commands.Bot, name: str):
    """Return the async callback for a prefix command by name."""
    cmd = bot.get_command(name)
    if cmd is None:
        raise KeyError(f"No prefix command {name!r} registered")
    return cmd.callback


# ---------------------------------------------------------------------------
# _uptime_string
# ---------------------------------------------------------------------------


def test_uptime_string_before_start_returns_unknown():
    """Before record_start_time is called, uptime is reported as unknown."""
    import commands.admin_commands as _mod

    original = _mod._start_time
    _mod._start_time = 0.0
    assert _uptime_string() == "unknown"
    _mod._start_time = original


def test_uptime_string_formats_correctly(mocker):
    """Uptime is reported in hours/minutes/seconds format."""
    import commands.admin_commands as _mod
    import time

    fake_start = 1000.0
    mocker.patch("commands.admin_commands.time.time", return_value=fake_start + 3661)
    _mod._start_time = fake_start
    result = _uptime_string()
    assert "1h" in result
    assert "1m" in result
    assert "1s" in result


def test_record_start_time_sets_nonzero_value():
    """record_start_time() records a nonzero timestamp."""
    import commands.admin_commands as _mod

    record_start_time()
    assert _mod._start_time > 0.0


# ---------------------------------------------------------------------------
# _is_developer
# ---------------------------------------------------------------------------


def test_is_developer_true_for_developer(mocker):
    ctx = make_ctx(mocker, author_id=DEVELOPER_DISCORD_ID)
    assert _is_developer(ctx) is True


def test_is_developer_false_for_non_developer(mocker):
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    assert _is_developer(ctx) is False


# ---------------------------------------------------------------------------
# !message — send a message to a guild channel
# ---------------------------------------------------------------------------


async def test_admin_message_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response."""
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "message")
    await cb(ctx, 12345, message="hello")
    ctx.send.assert_not_called()


async def test_admin_message_guild_not_found(admin_bot, mocker):
    """Reports an error when the target guild is not in the bot's cache."""
    ctx = make_ctx(mocker)
    mocker.patch.object(admin_bot, "get_guild", return_value=None)
    cb = get_prefix_callback(admin_bot, "message")
    await cb(ctx, 99999, message="hello")
    ctx.send.assert_called_once()
    assert "99999" in ctx.send.call_args.args[0]


async def test_admin_message_no_writable_channel(admin_bot, mocker):
    """Reports an error when the guild has no channel the bot can write to."""
    ctx = make_ctx(mocker)
    guild = mocker.Mock()
    guild.name = "TestGuild"
    guild.system_channel = None
    guild.text_channels = []
    mocker.patch.object(admin_bot, "get_guild", return_value=guild)
    mocker.patch("discord.utils.get", return_value=None)

    cb = get_prefix_callback(admin_bot, "message")
    await cb(ctx, 12345, message="hello")
    ctx.send.assert_called_once()
    assert "TestGuild" in ctx.send.call_args.args[0]


async def test_admin_message_sends_to_system_channel(admin_bot, mocker):
    """Sends the message to the guild's system channel when available."""
    ctx = make_ctx(mocker)
    channel = mocker.AsyncMock()
    channel.name = "system"
    guild = mocker.Mock()
    guild.name = "TestGuild"
    guild.system_channel = channel
    mocker.patch.object(admin_bot, "get_guild", return_value=guild)

    cb = get_prefix_callback(admin_bot, "message")
    await cb(ctx, 12345, message="Hello ORC!")
    channel.send.assert_called_once_with("Hello ORC!")
    ctx.send.assert_called_once()  # confirmation message to developer


# ---------------------------------------------------------------------------
# !stats — uptime and DB row counts
# ---------------------------------------------------------------------------


async def test_admin_stats_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response."""
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "stats")
    await cb(ctx)
    ctx.send.assert_not_called()


async def test_admin_stats_sends_message(admin_bot, mocker):
    """Developer receives a stats message containing uptime and DB info."""
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "stats")
    await cb(ctx)
    ctx.send.assert_called_once()
    msg = ctx.send.call_args.args[0]
    assert "Uptime" in msg
    assert "Database" in msg


# ---------------------------------------------------------------------------
# !logs — recent log buffer
# ---------------------------------------------------------------------------


async def test_admin_logs_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response."""
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "logs")
    await cb(ctx)
    ctx.send.assert_not_called()


async def test_admin_logs_sends_message(admin_bot, mocker):
    """Developer receives a log message."""
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "logs")
    await cb(ctx)
    ctx.send.assert_called_once()


async def test_admin_logs_truncates_long_output(admin_bot, mocker):
    """Output exceeding 1800 characters is truncated."""
    mocker.patch(
        "commands.admin_commands.get_recent_logs",
        return_value="x" * 2000,
    )
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "logs")
    await cb(ctx)
    msg = ctx.send.call_args.args[0]
    assert "truncated" in msg or len(msg) < 2100


# ---------------------------------------------------------------------------
# !restart — re-exec the bot process
# ---------------------------------------------------------------------------


async def test_admin_restart_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response and the process is not restarted."""
    mocker.patch("commands.admin_commands.os.execv")
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "restart")
    await cb(ctx)
    ctx.send.assert_not_called()
    import commands.admin_commands as _mod

    _mod.os.execv.assert_not_called()


async def test_admin_restart_sends_confirmation_then_restarts(admin_bot, mocker):
    """Developer receives a confirmation message before the process restarts."""
    mock_execv = mocker.patch("commands.admin_commands.os.execv")
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "restart")
    await cb(ctx)
    ctx.send.assert_called_once()
    mock_execv.assert_called_once()


# ---------------------------------------------------------------------------
# !warninglogs — paginated warning log view
# ---------------------------------------------------------------------------


async def test_admin_warninglogs_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response."""
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "warninglogs")
    await cb(ctx)
    ctx.send.assert_not_called()


async def test_admin_warninglogs_sends_view(admin_bot, mocker):
    """Developer receives a message with a _WarningLogsView attached."""
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "warninglogs")
    await cb(ctx)
    ctx.send.assert_called_once()
    _, kwargs = ctx.send.call_args
    assert isinstance(kwargs.get("view"), _WarningLogsView)


# ---------------------------------------------------------------------------
# !help — admin command list
# ---------------------------------------------------------------------------


async def test_admin_help_no_op_for_non_developer(admin_bot, mocker):
    """Non-developer callers receive no response."""
    ctx = make_ctx(mocker, author_id=NON_DEVELOPER_ID)
    cb = get_prefix_callback(admin_bot, "help")
    await cb(ctx)
    ctx.send.assert_not_called()


async def test_admin_help_lists_all_commands(admin_bot, mocker):
    """Developer receives a list of all admin commands."""
    ctx = make_ctx(mocker)
    cb = get_prefix_callback(admin_bot, "help")
    await cb(ctx)
    msg = ctx.send.call_args.args[0]
    for cmd_name in (
        "!message",
        "!stats",
        "!logs",
        "!warninglogs",
        "!restart",
        "!help",
    ):
        assert cmd_name in msg, f"Expected {cmd_name!r} in help output"


# ---------------------------------------------------------------------------
# _WarningLogsView — unit tests for the paginated UI class
# ---------------------------------------------------------------------------


def test_warning_logs_view_prev_disabled_on_first_page():
    """Prev button is disabled when on page 0."""
    view = _WarningLogsView(page=0, total_pages=3)
    assert view.prev_button.disabled is True
    assert view.next_button.disabled is False


def test_warning_logs_view_next_disabled_on_last_page():
    """Next button is disabled when on the final page."""
    view = _WarningLogsView(page=2, total_pages=3)
    assert view.next_button.disabled is True
    assert view.prev_button.disabled is False


def test_warning_logs_view_both_disabled_on_single_page():
    """Both buttons are disabled when there is only one page."""
    view = _WarningLogsView(page=0, total_pages=1)
    assert view.prev_button.disabled is True
    assert view.next_button.disabled is True


def test_warning_logs_view_build_content_includes_page_numbers(mocker):
    """build_content formats the page number and total pages into the string."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=(["WARNING: something bad"], 0, 5),
    )
    content = _WarningLogsView.build_content(page=0, total_pages=5)
    assert "1" in content  # page + 1
    assert "5" in content  # total_pages


def test_warning_logs_view_build_content_empty_buffer(mocker):
    """build_content shows a placeholder when the warning buffer is empty."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=([], 0, 1),
    )
    content = _WarningLogsView.build_content(page=0, total_pages=1)
    assert "no warning logs" in content


def test_warning_logs_view_build_content_truncates_long_body(mocker):
    """build_content truncates body text exceeding 1800 characters."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=(["x" * 2000], 0, 1),
    )
    content = _WarningLogsView.build_content(page=0, total_pages=1)
    assert "…" in content


async def test_warning_logs_view_next_button_advances_page(mocker):
    """Clicking Next increments the page and calls edit_message."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=(["entry"], 0, 3),
    )
    view = _WarningLogsView(page=0, total_pages=3)
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await view.next_button.callback(interaction)

    assert view._page == 1
    interaction.response.edit_message.assert_called_once()


async def test_warning_logs_view_prev_button_decrements_page(mocker):
    """Clicking Prev decrements the page and calls edit_message."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=(["entry"], 1, 3),
    )
    view = _WarningLogsView(page=1, total_pages=3)
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await view.prev_button.callback(interaction)

    assert view._page == 0
    interaction.response.edit_message.assert_called_once()


async def test_warning_logs_view_next_disables_at_last_page(mocker):
    """After clicking Next to reach the last page, Next becomes disabled."""
    mocker.patch(
        "commands.admin_commands.get_warning_logs_page",
        return_value=(["entry"], 0, 2),
    )
    # Start on second-to-last page (index 0 of 2 total)
    view = _WarningLogsView(page=0, total_pages=2)
    interaction = mocker.Mock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await view.next_button.callback(interaction)

    assert view._page == 1
    assert view.next_button.disabled is True
