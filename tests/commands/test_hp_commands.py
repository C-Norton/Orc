"""Integration tests for HP-related commands (/damage, /heal, /add_temp_hp).

Tests focus on edge cases not covered in test_death_save_commands.py:
- Massive damage instant-death (≥ 2× max HP from positive HP)
- Dying-character interactions with damage and slain threshold
- Temp HP replacement logic via /add_temp_hp
- Damage absorption through temp HP
"""
import pytest

from tests.commands.conftest import get_callback
from tests.conftest import make_interaction


def _sent_message(interaction):
    """Return the first positional argument of the last send_message call."""
    return interaction.response.send_message.call_args.args[0]


def _set_hp(db_session, character, current_hp, max_hp=20, temp_hp=0):
    """Helper: configure HP values directly and commit."""
    character.current_hp = current_hp
    character.max_hp = max_hp
    character.temp_hp = temp_hp
    db_session.commit()
    db_session.refresh(character)


# ---------------------------------------------------------------------------
# /damage — massive damage instant-death (current_hp ≤ -max_hp)
# ---------------------------------------------------------------------------


async def test_damage_massive_instant_death_at_double_max_hp(
    health_bot, sample_character, db_session, interaction
):
    """Damage bringing HP to ≤ -max_hp triggers instant-death message."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    # 10 current HP, 10 max HP → need > 20 total damage for current_hp ≤ -10
    await cb(interaction, amount="21")

    msg = _sent_message(interaction)
    # current_hp = 10 - 21 = -11, which is ≤ -10 (max_hp) → instant death
    assert "died" in msg.lower() or "slain" in msg.lower() or "death" in msg.lower() or "killed" in msg.lower()


async def test_damage_massive_does_not_add_death_save_failure(
    health_bot, sample_character, db_session, interaction
):
    """Massive-damage instant kill from positive HP bypasses death save failure logic."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="21")

    db_session.refresh(sample_character)
    # was_dying_before was False (HP=10 > 0), so no death save failure added
    assert sample_character.death_save_failures == 0


# ---------------------------------------------------------------------------
# /damage — dying character reaches 3 failures and is slain
# ---------------------------------------------------------------------------


async def test_damage_to_dying_character_slays_at_3_failures(
    health_bot, sample_character, db_session, interaction
):
    """Taking damage at 0 HP when already at 2 failures = slain (3rd failure)."""
    _set_hp(db_session, sample_character, current_hp=0, max_hp=10)
    sample_character.death_save_failures = 2
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="1")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 0  # reset after death

    msg = _sent_message(interaction)
    assert "slain" in msg.lower()


# ---------------------------------------------------------------------------
# /heal — does not reset saves for non-dying character
# ---------------------------------------------------------------------------


async def test_heal_from_positive_hp_does_not_reset_saves(
    health_bot, sample_character, db_session, interaction
):
    """Healing a character who is not dying leaves death save counters unchanged."""
    _set_hp(db_session, sample_character, current_hp=5, max_hp=10)
    sample_character.death_save_successes = 1
    sample_character.death_save_failures = 1
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="3")

    db_session.refresh(sample_character)
    # Non-dying character: counters should not be touched
    assert sample_character.death_save_successes == 1
    assert sample_character.death_save_failures == 1


# ---------------------------------------------------------------------------
# /add_temp_hp — 5e stacking rule
# ---------------------------------------------------------------------------


async def test_temp_hp_set_replaces_lower_existing(
    health_bot, sample_character, db_session, interaction
):
    """Adding higher temp HP replaces the existing lower value (5e rule)."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10, temp_hp=3)

    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=8)

    db_session.refresh(sample_character)
    assert sample_character.temp_hp == 8  # 8 > 3 → replaced


async def test_temp_hp_set_keeps_higher_existing(
    health_bot, sample_character, db_session, interaction
):
    """Adding lower temp HP keeps the existing higher value (5e rule: no stacking)."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10, temp_hp=10)

    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=4)

    db_session.refresh(sample_character)
    assert sample_character.temp_hp == 10  # 10 > 4 → kept


# ---------------------------------------------------------------------------
# /damage — damage absorbed by temp HP
# ---------------------------------------------------------------------------


async def test_damage_exceeding_current_plus_temp_hp(
    health_bot, sample_character, db_session, interaction
):
    """Damage > temp + current HP: temp = 0, current_hp clamped by application."""
    _set_hp(db_session, sample_character, current_hp=3, max_hp=10, temp_hp=5)

    cb = get_callback(health_bot, "hp", "damage")
    # 5 temp absorbs first, then 10 more damage hits current_hp (3 - 10 = -7)
    await cb(interaction, amount="15")

    db_session.refresh(sample_character)
    assert sample_character.temp_hp == 0
    # current_hp = 3 - (15 - 5) = 3 - 10 = -7
    assert sample_character.current_hp == -7


async def test_damage_absorbed_entirely_by_temp_hp(
    health_bot, sample_character, db_session, interaction
):
    """Damage fully absorbed by temp HP leaves current HP unchanged."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10, temp_hp=8)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5")

    db_session.refresh(sample_character)
    assert sample_character.current_hp == 10  # unchanged
    assert sample_character.temp_hp == 3  # 8 - 5 = 3


# ---------------------------------------------------------------------------
# /damage — GM targeting a party member
# ---------------------------------------------------------------------------


async def test_gm_can_damage_party_member(
    health_bot, sample_character, db_session, sample_active_party, interaction
):
    """A GM can apply damage to a named party member."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="3", partymember="Aldric")

    db_session.refresh(sample_character)
    assert sample_character.current_hp == 7
