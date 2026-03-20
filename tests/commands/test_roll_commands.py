import pytest
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sent_message(interaction):
    return interaction.response.send_message.call_args.args[0]


# ---------------------------------------------------------------------------
# Character-based rolls (need sample_character in DB)
# ---------------------------------------------------------------------------


async def test_roll_skill_success(mocker, roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, notation="Perception")

    interaction.response.send_message.assert_called_once()
    msg = _sent_message(interaction)
    assert "Aldric" in msg
    assert "Perception" in msg


async def test_roll_skill_no_character(
    roll_bot, sample_user, sample_server, interaction
):
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="Perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_roll_saving_throw_success(
    mocker, roll_bot, sample_character, interaction
):
    cb = get_callback(roll_bot, "roll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, notation="strength save")

    msg = _sent_message(interaction)
    assert "Strength Save" in msg


async def test_roll_initiative_success(mocker, roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, notation="initiative")

    msg = _sent_message(interaction)
    assert "Initiative" in msg


async def test_roll_stat_check_success(mocker, roll_bot, sample_character, interaction):
    cb = get_callback(roll_bot, "roll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
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


# ---------------------------------------------------------------------------
# Complex multi-dice expressions (no character needed)
# ---------------------------------------------------------------------------


async def test_roll_multi_dice_expression(roll_bot, interaction):
    """1d4+1d6+1d8 — three different dice, no character needed."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d4+1d6+1d8")

    interaction.response.send_message.assert_called_once()
    msg = _sent_message(interaction)
    assert "Total" in msg


async def test_roll_multi_dice_no_character_required(roll_bot, interaction):
    """Pure dice expression must not require a character in the DB."""
    cb = get_callback(roll_bot, "roll")
    # No sample_user / sample_character fixtures — DB is empty
    await cb(interaction, notation="2d6+1d4+3")

    msg = _sent_message(interaction)
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )
    assert "Total" in msg


async def test_roll_complex_notation_in_message(roll_bot, interaction):
    """The notation should appear in the response."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d8+5")

    msg = _sent_message(interaction)
    assert "2d8" in msg


# ---------------------------------------------------------------------------
# Named modifiers inside expressions (require character)
# ---------------------------------------------------------------------------


async def test_roll_named_modifier_in_expression(
    mocker, roll_bot, sample_character, interaction
):
    """2d6+perception — dice plus a named skill modifier."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d6+perception")

    msg = _sent_message(interaction)
    assert "Aldric" in msg
    assert "Perception" in msg


async def test_roll_named_modifier_no_character(
    roll_bot, sample_user, sample_server, interaction
):
    """Named modifier without an active character → ephemeral error."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d6+perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_roll_complex_full_expression(
    mocker, roll_bot, sample_character, interaction
):
    """2d8-initiative+8+2d6+perception — full mixed expression."""
    mocker.patch("dice_roller.random.randint", side_effect=[3, 5, 4, 2])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="2d8-initiative+8+2d6+perception")

    msg = _sent_message(interaction)
    assert "Aldric" in msg


# ---------------------------------------------------------------------------
# Advantage / disadvantage
# ---------------------------------------------------------------------------


async def test_roll_advantage_skill_check(
    mocker, roll_bot, sample_character, interaction
):
    """Advantage on a plain skill check: higher of two d20 rolls is kept."""
    mocker.patch("utils.dnd_logic.random.randint", side_effect=[15, 9])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="perception", advantage="advantage")

    msg = _sent_message(interaction)
    assert "15" in msg  # kept d20 appears in the message
    assert "9" in msg  # discarded roll also shown


async def test_roll_disadvantage_skill_check(
    mocker, roll_bot, sample_character, interaction
):
    """Disadvantage on a skill check: lower of two d20 rolls is kept."""
    mocker.patch("utils.dnd_logic.random.randint", side_effect=[15, 9])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="perception", advantage="disadvantage")

    msg = _sent_message(interaction)
    assert "9" in msg  # lower roll kept
    assert "15" in msg  # discarded shown


async def test_roll_advantage_on_raw_d20(mocker, roll_bot, interaction):
    """Advantage on a raw 1d20 expression (no character needed)."""
    mocker.patch("dice_roller.random.randint", side_effect=[18, 7])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d20", advantage="advantage")

    msg = _sent_message(interaction)
    assert "18" in msg  # higher kept
    assert "7" in msg  # discarded shown


async def test_roll_disadvantage_on_raw_d20(mocker, roll_bot, interaction):
    """Disadvantage on a raw 1d20 expression."""
    mocker.patch("dice_roller.random.randint", side_effect=[18, 7])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d20", advantage="disadvantage")

    msg = _sent_message(interaction)
    assert "7" in msg  # lower kept
    assert "18" in msg  # discarded shown


async def test_roll_advantage_saving_throw(
    mocker, roll_bot, sample_character, interaction
):
    mocker.patch("utils.dnd_logic.random.randint", side_effect=[14, 6])
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="strength save", advantage="advantage")

    msg = _sent_message(interaction)
    assert "14" in msg
    assert "6" in msg


async def test_roll_no_advantage_is_default(
    mocker, roll_bot, sample_character, interaction
):
    """When advantage is not passed the command still works normally."""
    mocker.patch("utils.dnd_logic.random.randint", return_value=12)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="perception")

    msg = _sent_message(interaction)
    assert "Aldric" in msg
    assert "12" in msg
