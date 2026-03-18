"""Unit tests for utils.hp_logic — pure HP calculation functions.

These are pure-function tests with no database access required.
"""
import pytest

from utils.hp_logic import apply_damage, apply_temp_hp, apply_healing, parse_amount


# ---------------------------------------------------------------------------
# apply_damage — zero and negative inputs
# ---------------------------------------------------------------------------


def test_apply_damage_zero_does_not_change_hp():
    """Applying 0 damage returns the same HP and temp HP unchanged."""
    current_hp, temp_hp = apply_damage(10, 0, 0)
    assert current_hp == 10
    assert temp_hp == 0


def test_apply_damage_zero_with_temp_hp_unchanged():
    """Applying 0 damage when temp HP exists leaves both values intact."""
    current_hp, temp_hp = apply_damage(10, 5, 0)
    assert current_hp == 10
    assert temp_hp == 5


# ---------------------------------------------------------------------------
# apply_damage — temp HP absorption
# ---------------------------------------------------------------------------


def test_temp_hp_absorbs_partial_damage():
    """5 temp HP, 8 damage → temp HP depleted, current HP reduced by remainder (3)."""
    current_hp, temp_hp = apply_damage(current_hp=20, temp_hp=5, damage=8)
    assert temp_hp == 0
    assert current_hp == 17  # 20 - (8 - 5) = 20 - 3


def test_temp_hp_absorbs_all_damage():
    """10 temp HP, 5 damage → temp HP reduced to 5, current HP unchanged."""
    current_hp, temp_hp = apply_damage(current_hp=20, temp_hp=10, damage=5)
    assert temp_hp == 5
    assert current_hp == 20


def test_apply_damage_no_temp_reduces_current_hp():
    """With no temp HP, damage is applied directly to current HP."""
    current_hp, temp_hp = apply_damage(current_hp=10, temp_hp=0, damage=4)
    assert current_hp == 6
    assert temp_hp == 0


def test_apply_damage_exceeds_current_plus_temp():
    """Damage exceeding temp + current: temp goes to 0, current can go negative."""
    # 5 temp + 3 current = 8 effective; 15 damage → temp=0, current=3-10=-7
    current_hp, temp_hp = apply_damage(current_hp=3, temp_hp=5, damage=15)
    assert temp_hp == 0
    # After absorbing 5 temp, remaining damage=10, current_hp=3-10=-7
    assert current_hp == -7


# ---------------------------------------------------------------------------
# apply_temp_hp — 5e stacking rule (no stacking, keep highest)
# ---------------------------------------------------------------------------


def test_add_temp_hp_replaces_if_higher():
    """New temp HP value > existing → replaced (5e rule: take higher value)."""
    result = apply_temp_hp(current_temp=3, new_temp=10)
    assert result == 10


def test_add_temp_hp_keeps_if_lower():
    """New temp HP value < existing → unchanged (5e rule: don't stack)."""
    result = apply_temp_hp(current_temp=10, new_temp=3)
    assert result == 10


def test_add_temp_hp_equal_values():
    """Equal temp HP values → result equals that value."""
    result = apply_temp_hp(current_temp=5, new_temp=5)
    assert result == 5


# ---------------------------------------------------------------------------
# apply_healing — caps at max_hp
# ---------------------------------------------------------------------------


def test_apply_healing_does_not_exceed_max():
    """Healing beyond max HP is capped at max HP."""
    result = apply_healing(current_hp=8, max_hp=10, heal=5)
    assert result == 10


def test_apply_healing_from_zero():
    """Healing from 0 HP adds the heal amount (up to max)."""
    result = apply_healing(current_hp=0, max_hp=10, heal=4)
    assert result == 4


# ---------------------------------------------------------------------------
# parse_amount — edge cases
# ---------------------------------------------------------------------------


def test_parse_amount_integer_input():
    """Integer input is returned as-is."""
    assert parse_amount(5) == 5


def test_parse_amount_string_integer():
    """String integer is parsed correctly."""
    assert parse_amount("7") == 7


def test_parse_amount_dice_expression():
    """Dice expression is evaluated and returns an integer."""
    # We mock nothing — the actual dice roller is called; result must be an int
    result = parse_amount("1d1")  # 1d1 always rolls 1
    assert result == 1


def test_parse_amount_invalid_raises():
    """Invalid expression raises ValueError."""
    with pytest.raises((ValueError, Exception)):
        parse_amount("notanumber")
