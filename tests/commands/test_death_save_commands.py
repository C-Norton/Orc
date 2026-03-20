"""Integration tests for death save behaviour in roll and health commands.

Tests cover:
- /roll death save paths (success, failure, stabilize, slain, nat-20 variants)
- Autocomplete includes/excludes 'death save' based on character HP
- /damage records a failure when character already at 0 HP
- /heal resets death save counters when healing from ≤ 0 HP
"""

import pytest

from models import Character, ClassLevel, PartySettings
from enums.death_save_nat20_mode import DeathSaveNat20Mode
from tests.commands.conftest import get_callback
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sent_message(interaction):
    return interaction.response.send_message.call_args.args[0]


def _set_character_hp(db_session, character, current_hp, max_hp=10):
    character.current_hp = current_hp
    character.max_hp = max_hp
    db_session.commit()
    db_session.refresh(character)


# ---------------------------------------------------------------------------
# /roll death save — basic validation
# ---------------------------------------------------------------------------


async def test_death_save_not_dying_returns_error(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Attempting a death save when HP > 0 returns an ephemeral error."""
    _set_character_hp(db_session, sample_character, current_hp=5, max_hp=10)
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = _sent_message(interaction)
    assert "not currently dying" in msg.lower()


async def test_death_save_no_character_returns_error(
    roll_bot, sample_user, sample_server, interaction
):
    """Death save with no active character returns the no-character error."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /roll death save — success path
# ---------------------------------------------------------------------------


async def test_death_save_success_roll_increments_successes(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """A roll of 12 (success) increments the success counter by 1."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 12))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 1
    assert sample_character.death_save_failures == 0

    msg = _sent_message(interaction)
    assert "Success" in msg


async def test_death_save_failure_roll_increments_failures(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """A roll of 7 (failure) increments the failure counter by 1."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 7))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 1
    assert sample_character.death_save_successes == 0

    msg = _sent_message(interaction)
    assert "Failure" in msg


# ---------------------------------------------------------------------------
# /roll death save — natural 1
# ---------------------------------------------------------------------------


async def test_death_save_nat1_records_two_failures(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Natural 1 records two failures."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 1))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 2

    msg = _sent_message(interaction)
    assert "Natural 1" in msg


# ---------------------------------------------------------------------------
# /roll death save — natural 20 REGAIN_HP mode
# ---------------------------------------------------------------------------


async def test_death_save_nat20_regain_hp_sets_hp_to_one(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Nat-20 with REGAIN_HP sets current_hp=1 and resets counters."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_successes = 1
    sample_character.death_save_failures = 1
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 20))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.current_hp == 1
    assert sample_character.death_save_successes == 0
    assert sample_character.death_save_failures == 0

    msg = _sent_message(interaction)
    assert "Natural 20" in msg
    assert "regains 1 hp" in msg.lower()


# ---------------------------------------------------------------------------
# /roll death save — natural 20 DOUBLE_SUCCESS mode
# ---------------------------------------------------------------------------


async def test_death_save_nat20_double_success_records_two_successes(
    mocker, roll_bot, sample_character, db_session, interaction, sample_active_party
):
    """Nat-20 with DOUBLE_SUCCESS party setting records 2 successes."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_active_party.characters.append(sample_character)

    party_settings = (
        db_session.query(PartySettings)
        .filter_by(party_id=sample_active_party.id)
        .first()
    )
    if party_settings is None:
        party_settings = PartySettings(party_id=sample_active_party.id)
        db_session.add(party_settings)
    party_settings.death_save_nat20_mode = DeathSaveNat20Mode.DOUBLE_SUCCESS
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 20))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 2

    msg = _sent_message(interaction)
    assert "Two successes" in msg


# ---------------------------------------------------------------------------
# /roll death save — stabilize
# ---------------------------------------------------------------------------


async def test_death_save_third_success_stabilizes(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Third success triggers stabilize message and resets counters."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_successes = 2
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 14))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 0
    assert sample_character.death_save_failures == 0

    msg = _sent_message(interaction)
    assert "stabilized" in msg.lower()


# ---------------------------------------------------------------------------
# /roll death save — slain
# ---------------------------------------------------------------------------


async def test_death_save_third_failure_slain(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Third failure triggers slain message and sends public announcement."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 2
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 4))

    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 0  # reset after death

    msg = _sent_message(interaction)
    assert "slain" in msg.lower()

    # Public follow-up should also mention the character was slain
    interaction.followup.send.assert_called_once()
    followup_msg = interaction.followup.send.call_args.args[0]
    assert "slain" in followup_msg.lower()


# ---------------------------------------------------------------------------
# Autocomplete — death save visibility
# ---------------------------------------------------------------------------


def _get_autocomplete_callback(bot, command_name, param_name):
    """Return the autocomplete callback for a command parameter."""
    cmd = bot.tree.get_command(command_name)
    param = cmd._params.get(param_name)
    if param is None:
        return None
    return getattr(param, "autocomplete", None)


async def test_autocomplete_excludes_death_save_when_healthy(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Autocomplete does not suggest 'death save' for a healthy character."""
    _set_character_hp(db_session, sample_character, current_hp=8, max_hp=10)
    autocomplete_cb = _get_autocomplete_callback(roll_bot, "roll", "notation")
    if autocomplete_cb is None:
        pytest.skip("Autocomplete not accessible via this path")

    choices = await autocomplete_cb(interaction, "death")
    names = [c.name for c in choices]
    assert "death save" not in names


async def test_autocomplete_includes_death_save_when_dying(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Autocomplete suggests 'death save' when character is at 0 HP."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    autocomplete_cb = _get_autocomplete_callback(roll_bot, "roll", "notation")
    if autocomplete_cb is None:
        pytest.skip("Autocomplete not accessible via this path")

    choices = await autocomplete_cb(interaction, "death")
    names = [c.name for c in choices]
    assert "death save" in names


# ---------------------------------------------------------------------------
# /damage — failure when already dying
# ---------------------------------------------------------------------------


async def test_damage_records_failure_when_dying(
    mocker, health_bot, sample_character, db_session, interaction
):
    """Taking damage at 0 HP records a death save failure."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 1
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="3")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 2

    msg = _sent_message(interaction)
    assert "failure" in msg.lower()


async def test_damage_at_0hp_with_two_failures_slays(
    mocker, health_bot, sample_character, db_session, interaction
):
    """Third failure from damage slays the character."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 2
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 0  # reset on death

    msg = _sent_message(interaction)
    assert "slain" in msg.lower()


async def test_damage_does_not_record_failure_when_not_dying(
    mocker, health_bot, sample_character, db_session, interaction
):
    """Taking damage at positive HP does not affect death save counters."""
    _set_character_hp(db_session, sample_character, current_hp=5, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="2")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 0


# ---------------------------------------------------------------------------
# /heal — reset death saves when healing from dying state
# ---------------------------------------------------------------------------


async def test_heal_from_dying_resets_death_saves(
    mocker, health_bot, sample_character, db_session, interaction
):
    """Healing a dying character resets death save counters."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_successes = 2
    sample_character.death_save_failures = 1
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="5")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 0
    assert sample_character.death_save_failures == 0
    assert sample_character.current_hp == 5

    msg = _sent_message(interaction)
    assert "reset" in msg.lower()


async def test_heal_from_positive_hp_does_not_reset_saves(
    mocker, health_bot, sample_character, db_session, interaction
):
    """Healing a character who is not dying does not reset death saves."""
    _set_character_hp(db_session, sample_character, current_hp=3, max_hp=10)
    sample_character.death_save_successes = 1
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="2")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 1


# ---------------------------------------------------------------------------
# /roll death save — multi-round and inspiration interactions
# ---------------------------------------------------------------------------


async def test_death_save_multi_round_success_then_failure(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Two sequential death saves persist: first adds success, second adds failure."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)

    cb = get_callback(roll_bot, "roll")

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 12))
    await cb(interaction, notation="death save")
    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 1
    assert sample_character.death_save_failures == 0

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 6))
    await cb(interaction, notation="death save")
    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 1
    assert sample_character.death_save_failures == 1


async def test_death_save_when_character_has_inspiration(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """A dying character who holds inspiration can still roll death saves normally."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.inspiration = True
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 14))
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    # Should succeed without error; inspiration is unrelated to death saves
    assert sample_character.death_save_successes == 1
    assert sample_character.inspiration is True  # unchanged


async def test_death_save_exactly_at_0_hp(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """A character at exactly 0 HP (not negative) qualifies for a death save."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 11))
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    db_session.refresh(sample_character)
    assert sample_character.death_save_successes == 1


async def test_damage_at_0_hp_records_exactly_one_failure(
    mocker, health_bot, sample_character, db_session, interaction
):
    """/damage at 0 HP records exactly 1 additional failure (not more, not less)."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 0
    db_session.commit()

    cb_dmg = get_callback(health_bot, "hp", "damage")
    await cb_dmg(interaction, amount="3")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 1


async def test_death_save_slain_sends_announcement(
    mocker, roll_bot, sample_character, db_session, interaction
):
    """Third failure triggers a public followup announcing the character was slain."""
    _set_character_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 2
    db_session.commit()

    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 4))
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="death save")

    # The public followup must mention being slain
    interaction.followup.send.assert_called_once()
    followup_msg = interaction.followup.send.call_args.args[0]
    assert "slain" in followup_msg.lower()
