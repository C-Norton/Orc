"""Unit tests for utils.crit_logic.apply_crit_damage."""

import pytest

from enums.crit_rule import CritRule
from utils.crit_logic import apply_crit_damage


# ---------------------------------------------------------------------------
# DOUBLE_DICE
# ---------------------------------------------------------------------------


def test_double_dice_doubles_die_count(mocker):
    """DOUBLE_DICE: 1d8 becomes 2d8 (two dice are rolled)."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    result = apply_crit_damage("1d8+2", CritRule.DOUBLE_DICE)
    assert len(result.rolls) == 2
    assert result.modifier == 2
    assert result.total == 10  # 4+4+2


def test_double_dice_multi_die(mocker):
    """DOUBLE_DICE: 2d6+1 becomes 4d6+1."""
    mocker.patch("dice_roller.random.randint", return_value=3)
    result = apply_crit_damage("2d6+1", CritRule.DOUBLE_DICE)
    assert len(result.rolls) == 4
    assert result.modifier == 1
    assert result.total == 13  # 3*4+1


def test_double_dice_does_not_double_modifier(mocker):
    """DOUBLE_DICE: the flat modifier is NOT doubled."""
    mocker.patch("dice_roller.random.randint", return_value=5)
    result = apply_crit_damage("1d6+10", CritRule.DOUBLE_DICE)
    assert result.modifier == 10
    assert result.total == 20  # 5+5+10


def test_double_dice_no_modifier(mocker):
    """DOUBLE_DICE: formula with no modifier works correctly."""
    mocker.patch("dice_roller.random.randint", return_value=6)
    result = apply_crit_damage("1d8", CritRule.DOUBLE_DICE)
    assert len(result.rolls) == 2
    assert result.modifier == 0
    assert result.total == 12


def test_double_dice_negative_modifier(mocker):
    """DOUBLE_DICE: negative modifier is preserved, not doubled."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    result = apply_crit_damage("1d6-1", CritRule.DOUBLE_DICE)
    assert result.modifier == -1
    assert result.total == 7  # 4+4-1


# ---------------------------------------------------------------------------
# DOUBLE_DAMAGE
# ---------------------------------------------------------------------------


def test_double_damage_doubles_total(mocker):
    """DOUBLE_DAMAGE: the full final total is doubled."""
    mocker.patch("dice_roller.random.randint", return_value=5)
    result = apply_crit_damage("1d8+2", CritRule.DOUBLE_DAMAGE)
    assert result.total == 14  # (5+2)*2


def test_double_damage_grants_no_inspiration(mocker):
    mocker.patch("dice_roller.random.randint", return_value=5)
    result = apply_crit_damage("1d8+2", CritRule.DOUBLE_DAMAGE)
    assert result.grants_inspiration is False


# ---------------------------------------------------------------------------
# MAX_DAMAGE
# ---------------------------------------------------------------------------


def test_max_damage_returns_max_value():
    """MAX_DAMAGE: every die shows its max face value."""
    result = apply_crit_damage("2d6+3", CritRule.MAX_DAMAGE)
    assert result.rolls == [6, 6]
    assert result.modifier == 3
    assert result.total == 15


def test_max_damage_single_die():
    """MAX_DAMAGE: 1d8+0 → rolls=[8], total=8."""
    result = apply_crit_damage("1d8", CritRule.MAX_DAMAGE)
    assert result.rolls == [8]
    assert result.total == 8


def test_max_damage_grants_no_inspiration():
    result = apply_crit_damage("2d6+3", CritRule.MAX_DAMAGE)
    assert result.grants_inspiration is False


# ---------------------------------------------------------------------------
# PERKINS
# ---------------------------------------------------------------------------


def test_perkins_grants_inspiration(mocker):
    """PERKINS: grants_inspiration is True."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    result = apply_crit_damage("1d8+2", CritRule.PERKINS)
    assert result.grants_inspiration is True


def test_perkins_is_normal_roll(mocker):
    """PERKINS: damage roll is NOT modified — same as a normal hit."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    result = apply_crit_damage("1d8+2", CritRule.PERKINS)
    assert result.total == 6  # 4+2
    assert len(result.rolls) == 1


# ---------------------------------------------------------------------------
# NONE
# ---------------------------------------------------------------------------


def test_none_is_normal_roll(mocker):
    """NONE: no crit modification at all."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    result = apply_crit_damage("1d8+2", CritRule.NONE)
    assert result.total == 6
    assert result.grants_inspiration is False
    assert len(result.rolls) == 1
