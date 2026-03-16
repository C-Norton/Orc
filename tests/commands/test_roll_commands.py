import pytest
from unittest.mock import patch
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sent_message(interaction):
    return interaction.response.send_message.call_args.args[0]


# ---------------------------------------------------------------------------
# Character-based rolls (need sample_character in DB)
# ---------------------------------------------------------------------------

async def test_roll_skill_success(roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    with patch("utils.dnd_logic.random.randint", return_value=10):
        await cb(interaction, notation="Perception")

    interaction.response.send_message.assert_called_once()
    msg = _sent_message(interaction)
    assert "Aldric" in msg
    assert "Perception" in msg


async def test_roll_skill_no_character(roll_bot, sample_user, sample_server, interaction):
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="Perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_roll_saving_throw_success(roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    with patch("utils.dnd_logic.random.randint", return_value=10):
        await cb(interaction, notation="strength save")

    msg = _sent_message(interaction)
    assert "Strength Save" in msg


async def test_roll_initiative_success(roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    with patch("utils.dnd_logic.random.randint", return_value=10):
        await cb(interaction, notation="initiative")

    msg = _sent_message(interaction)
    assert "Initiative" in msg


async def test_roll_stat_check_success(roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    with patch("utils.dnd_logic.random.randint", return_value=10):
        await cb(interaction, notation="dexterity")

    msg = _sent_message(interaction)
    assert "Dexterity Check" in msg


# ---------------------------------------------------------------------------
# Raw dice rolls (no character needed)
# ---------------------------------------------------------------------------

async def test_roll_raw_dice_no_character_needed(roll_bot, interaction):
    """Raw dice notation should work even without a character in the DB."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d6+3")

    interaction.response.send_message.assert_called_once()
    msg = _sent_message(interaction)
    assert "2d6+3" in msg
    assert "Total" in msg


async def test_roll_raw_dice_total_present(roll_bot, interaction):
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d1")  # always rolls 1

    msg = _sent_message(interaction)
    assert "Total" in msg


# ---------------------------------------------------------------------------
# Invalid notation
# ---------------------------------------------------------------------------

async def test_roll_invalid_notation_sends_ephemeral_error(roll_bot, interaction):
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="notdice")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
