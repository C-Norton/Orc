"""Unit tests for utils.death_save_logic — pure death-save calculation logic.

These tests use SimpleNamespace to stand in for Character objects so no
database session is needed.
"""
from types import SimpleNamespace

import pytest

from enums.death_save_nat20_mode import DeathSaveNat20Mode
from utils.death_save_logic import DeathSaveResult, character_is_dying, process_death_save

REGAIN_HP = DeathSaveNat20Mode.REGAIN_HP
DOUBLE_SUCCESS = DeathSaveNat20Mode.DOUBLE_SUCCESS


# ---------------------------------------------------------------------------
# process_death_save — success / failure basics
# ---------------------------------------------------------------------------


def test_roll_10_is_one_success():
    """Roll of 10 records a single success."""
    result = process_death_save(10, REGAIN_HP, 0, 0)
    assert result.is_success is True
    assert result.is_failure is False
    assert result.successes_after == 1
    assert result.failures_after == 0


def test_roll_15_is_one_success():
    """Any roll 10–19 (non-nat20) records a single success."""
    result = process_death_save(15, REGAIN_HP, 0, 0)
    assert result.successes_after == 1
    assert result.failures_after == 0


def test_roll_9_is_one_failure():
    """Roll of 9 records a single failure."""
    result = process_death_save(9, REGAIN_HP, 0, 0)
    assert result.is_failure is True
    assert result.is_success is False
    assert result.failures_after == 1
    assert result.successes_after == 0


def test_roll_5_is_one_failure():
    """Any roll 2–9 records a single failure."""
    result = process_death_save(5, REGAIN_HP, 0, 0)
    assert result.failures_after == 1


# ---------------------------------------------------------------------------
# Natural 1 — two failures
# ---------------------------------------------------------------------------


def test_nat1_records_two_failures():
    """Natural 1 records two failures at once."""
    result = process_death_save(1, REGAIN_HP, 0, 0)
    assert result.failures_after == 2
    assert result.is_failure is True


def test_nat1_with_one_existing_failure_reaches_three():
    """Natural 1 when already at 1 failure → slain (capped at 3)."""
    result = process_death_save(1, REGAIN_HP, 0, 1)
    assert result.is_slain is True
    assert result.failures_after == 0  # reset on death


def test_nat1_with_two_existing_failures_is_slain():
    """Natural 1 when already at 2 failures → slain."""
    result = process_death_save(1, REGAIN_HP, 0, 2)
    assert result.is_slain is True


# ---------------------------------------------------------------------------
# Natural 20 — REGAIN_HP mode
# ---------------------------------------------------------------------------


def test_nat20_regain_hp_sets_nat20_heal_flag():
    """Nat-20 with REGAIN_HP mode sets is_nat20_heal=True."""
    result = process_death_save(20, REGAIN_HP, 0, 0)
    assert result.is_nat20_heal is True
    assert result.is_success is True


def test_nat20_regain_hp_resets_counters():
    """Nat-20 with REGAIN_HP resets both counters to 0 (HP restored by caller)."""
    result = process_death_save(20, REGAIN_HP, 2, 1)
    assert result.successes_after == 0
    assert result.failures_after == 0


def test_nat20_regain_hp_is_not_stabilized():
    """Nat-20 with REGAIN_HP does not set is_stabilized (HP restoration is separate)."""
    result = process_death_save(20, REGAIN_HP, 0, 0)
    assert result.is_stabilized is False


# ---------------------------------------------------------------------------
# Natural 20 — DOUBLE_SUCCESS mode
# ---------------------------------------------------------------------------


def test_nat20_double_success_records_two_successes():
    """Nat-20 with DOUBLE_SUCCESS records two successes."""
    result = process_death_save(20, DOUBLE_SUCCESS, 0, 0)
    assert result.successes_after == 2
    assert result.is_nat20_heal is False


def test_nat20_double_success_with_one_existing_stabilizes():
    """Nat-20 DOUBLE_SUCCESS when at 1 success → stabilized (1 + 2 = 3)."""
    result = process_death_save(20, DOUBLE_SUCCESS, 1, 0)
    assert result.is_stabilized is True
    assert result.successes_after == 0  # reset on stabilize


def test_nat20_double_success_capped_at_three():
    """Nat-20 DOUBLE_SUCCESS cannot push successes above 3."""
    result = process_death_save(20, DOUBLE_SUCCESS, 2, 0)
    assert result.is_stabilized is True


# ---------------------------------------------------------------------------
# Stabilize (3 successes)
# ---------------------------------------------------------------------------


def test_third_success_stabilizes():
    """Third success triggers stabilize flag and resets counters."""
    result = process_death_save(12, REGAIN_HP, 2, 0)
    assert result.is_stabilized is True
    assert result.successes_after == 0
    assert result.failures_after == 0


def test_stabilize_does_not_set_slain():
    """Stabilize and slain are mutually exclusive."""
    result = process_death_save(15, REGAIN_HP, 2, 0)
    assert result.is_stabilized is True
    assert result.is_slain is False


# ---------------------------------------------------------------------------
# Slain (3 failures)
# ---------------------------------------------------------------------------


def test_third_failure_slain():
    """Third failure triggers is_slain and resets counters."""
    result = process_death_save(5, REGAIN_HP, 0, 2)
    assert result.is_slain is True
    assert result.failures_after == 0
    assert result.successes_after == 0


def test_slain_does_not_set_stabilized():
    """Slain and stabilize are mutually exclusive."""
    result = process_death_save(3, REGAIN_HP, 0, 2)
    assert result.is_slain is True
    assert result.is_stabilized is False


# ---------------------------------------------------------------------------
# character_is_dying
# ---------------------------------------------------------------------------


def test_character_is_dying_at_zero_hp():
    """A character at 0 HP with HP configured is dying."""
    char = SimpleNamespace(max_hp=10, current_hp=0)
    assert character_is_dying(char) is True


def test_character_is_dying_at_negative_hp():
    """A character at negative HP is also dying."""
    char = SimpleNamespace(max_hp=10, current_hp=-3)
    assert character_is_dying(char) is True


def test_character_not_dying_at_positive_hp():
    """A character with positive HP is not dying."""
    char = SimpleNamespace(max_hp=10, current_hp=5)
    assert character_is_dying(char) is False


def test_character_not_dying_when_hp_not_set():
    """A character whose max_hp is -1 (never configured) is not dying."""
    char = SimpleNamespace(max_hp=-1, current_hp=-1)
    assert character_is_dying(char) is False


# ---------------------------------------------------------------------------
# Boundary tests — explicit 10/9 boundary
# ---------------------------------------------------------------------------


def test_roll_exactly_10_is_success():
    """Roll of exactly 10 is a success, not a failure (boundary condition)."""
    result = process_death_save(10, REGAIN_HP, 0, 0)
    assert result.is_success is True
    assert result.is_failure is False


def test_roll_exactly_9_is_failure():
    """Roll of exactly 9 is a failure, not a success (boundary condition)."""
    result = process_death_save(9, REGAIN_HP, 0, 0)
    assert result.is_failure is True
    assert result.is_success is False


# ---------------------------------------------------------------------------
# Boundary tests — nat1 at 2 existing failures
# ---------------------------------------------------------------------------


def test_nat20_double_success_at_2_existing_clamps_to_3():
    """2 existing successes + nat20 DOUBLE_SUCCESS = stabilized (clamped at 3, not 4)."""
    result = process_death_save(20, DOUBLE_SUCCESS, 2, 0)
    assert result.is_stabilized is True
    assert result.successes_after == 0  # reset after stabilize


def test_nat1_at_2_failures_slays():
    """2 existing failures + nat1 = slain (2 failures added, capped at 3)."""
    result = process_death_save(1, REGAIN_HP, 0, 2)
    assert result.is_slain is True
    assert result.failures_after == 0  # reset on death


# ---------------------------------------------------------------------------
# result.roll field
# ---------------------------------------------------------------------------


def test_process_death_save_returns_correct_roll_value():
    """result.roll matches the roll argument passed to process_death_save."""
    for roll in (1, 9, 10, 15, 20):
        result = process_death_save(roll, REGAIN_HP, 0, 0)
        assert result.roll == roll


# ---------------------------------------------------------------------------
# character_is_dying — additional cases
# ---------------------------------------------------------------------------


def test_character_is_dying_with_none_current_hp():
    """A character with current_hp=None (never set) is not dying."""
    char = SimpleNamespace(max_hp=10, current_hp=None)
    assert character_is_dying(char) is False


def test_character_is_dying_with_positive_hp():
    """A character at current_hp=1 (positive) is not dying."""
    char = SimpleNamespace(max_hp=10, current_hp=1)
    assert character_is_dying(char) is False


def test_character_is_dying_with_negative_hp():
    """A character at current_hp=-5 (below zero) is dying."""
    char = SimpleNamespace(max_hp=10, current_hp=-5)
    assert character_is_dying(char) is True
