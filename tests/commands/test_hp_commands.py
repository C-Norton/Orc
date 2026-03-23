"""Integration tests for HP-related commands (/damage, /heal, /add_temp_hp).

Tests focus on edge cases not covered in test_death_save_commands.py:
- Massive damage instant-death (single hit >= max HP from positive HP)
- Downed message when reaching 0 HP without triggering massive damage
- HP clamped to 0 — never goes negative
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
    """A single hit equal to or greater than max HP triggers instant-death (massive damage rule).

    Per 5e 2024: if a single hit's damage >= the character's HP maximum while the
    character is above 0 HP, they die instantly rather than entering the dying state.
    """
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    # damage (10) == max_hp (10) → massive damage threshold met exactly
    await cb(interaction, amount="10")

    msg = _sent_message(interaction)
    assert (
        "died" in msg.lower()
        or "slain" in msg.lower()
        or "death" in msg.lower()
        or "killed" in msg.lower()
        or "massive" in msg.lower()
    )


async def test_damage_massive_does_not_add_death_save_failure(
    health_bot, sample_character, db_session, interaction
):
    """Massive-damage instant kill from positive HP bypasses death save failure logic."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="10")

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
    """Damage > temp + current HP: temp = 0, current_hp clamped to 0."""
    _set_hp(db_session, sample_character, current_hp=3, max_hp=10, temp_hp=5)

    cb = get_callback(health_bot, "hp", "damage")
    # 5 temp absorbs first, then 10 more damage vs current_hp (3) → clamped to 0
    await cb(interaction, amount="15")

    db_session.refresh(sample_character)
    assert sample_character.temp_hp == 0
    assert sample_character.current_hp == 0


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


# ---------------------------------------------------------------------------
# /damage — downed message and HP floor
# ---------------------------------------------------------------------------


async def test_damage_to_zero_shows_downed_message(
    health_bot, sample_character, db_session, interaction
):
    """A hit that reduces HP to 0 with damage < max HP shows the downed message,
    not the instant-death message.  HP is clamped to 0."""
    # max_hp=15, current_hp=10, damage=10 → HP reaches 0, but damage (10) < max_hp (15)
    _set_hp(db_session, sample_character, current_hp=10, max_hp=15)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="10")

    db_session.refresh(sample_character)
    assert sample_character.current_hp == 0

    msg = _sent_message(interaction)
    assert "died" not in msg.lower() and "massive" not in msg.lower()
    assert "downed" in msg.lower() or "death saving" in msg.lower()


async def test_hp_never_goes_below_zero(
    health_bot, sample_character, db_session, interaction
):
    """Overkill damage clamps current HP to 0, never negative."""
    _set_hp(db_session, sample_character, current_hp=5, max_hp=20)

    cb = get_callback(health_bot, "hp", "damage")
    # 5 damage == current HP; result should be 0, not negative
    await cb(interaction, amount="5")

    db_session.refresh(sample_character)
    assert sample_character.current_hp == 0


async def test_massive_damage_threshold_exactly_max_hp(
    health_bot, sample_character, db_session, interaction
):
    """A hit exactly equal to max HP triggers massive damage (>= threshold)."""
    _set_hp(db_session, sample_character, current_hp=10, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="10")  # exactly max_hp

    msg = _sent_message(interaction)
    assert "died" in msg.lower() or "massive" in msg.lower()
    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 0  # no failure added — instant kill


async def test_massive_damage_one_below_threshold_gives_downed(
    health_bot, sample_character, db_session, interaction
):
    """A hit one point below max HP drops to 0 HP but does NOT trigger massive damage."""
    # current_hp=9, max_hp=10, damage=9 → HP=0, damage (9) < max_hp (10) → downed only
    _set_hp(db_session, sample_character, current_hp=9, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="9")  # max_hp - 1 → downed only

    msg = _sent_message(interaction)
    assert "died" not in msg.lower() and "massive" not in msg.lower()
    assert "downed" in msg.lower() or "death saving" in msg.lower()


async def test_massive_damage_not_triggered_when_already_dying(
    health_bot, sample_character, db_session, interaction
):
    """Taking massive damage while already at 0 HP (dying) adds a failure counter
    rather than showing the instant-death message — the character is already down."""
    _set_hp(db_session, sample_character, current_hp=0, max_hp=10)

    cb = get_callback(health_bot, "hp", "damage")
    # 20 damage >= max_hp but character is already dying — just adds a failure
    await cb(interaction, amount="20")

    db_session.refresh(sample_character)
    assert sample_character.death_save_failures == 1
    msg = _sent_message(interaction)
    assert "massive" not in msg.lower()
