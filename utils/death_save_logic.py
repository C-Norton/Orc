"""Pure logic for death saving throws (no database access).

Rules (5e 2024):
- Roll 1d20 when prompted on your turn at 0 HP.
- 10+ = 1 success; 9- = 1 failure.
- Natural 20 = configurable (REGAIN_HP: regain 1 HP and reset; DOUBLE_SUCCESS: 2 successes).
- Natural 1 = 2 failures.
- 3 successes = stabilize (reset counters, stay at 0 HP).
- 3 failures = slain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from enums.death_save_nat20_mode import DeathSaveNat20Mode

if TYPE_CHECKING:
    from models import Character


@dataclass
class DeathSaveResult:
    """Outcome of a single death saving throw."""

    roll: int
    is_success: bool
    is_failure: bool
    is_stabilized: bool  # 3 successes reached — character is stable
    is_slain: bool  # 3 failures reached — character dies
    is_nat20_heal: bool  # nat20 + REGAIN_HP mode → HP restored to 1
    successes_after: int
    failures_after: int


_NAT20 = 20
_NAT1 = 1
_SUCCESS_THRESHOLD = 10
_SAVES_TO_STABILIZE = 3
_SAVES_TO_DIE = 3


def process_death_save(
    roll: int,
    nat20_mode: DeathSaveNat20Mode,
    current_successes: int,
    current_failures: int,
) -> DeathSaveResult:
    """Compute the result of a single death saving throw.

    This is a pure function — it does not touch the database.  Callers are
    responsible for persisting the returned counters and handling the
    ``is_stabilized`` / ``is_slain`` / ``is_nat20_heal`` flags.

    Args:
        roll: The raw d20 result (1–20).
        nat20_mode: Party setting controlling nat-20 behaviour.
        current_successes: Successes already recorded before this roll.
        current_failures: Failures already recorded before this roll.

    Returns:
        A :class:`DeathSaveResult` with updated counter values and outcome flags.
    """
    is_nat20_heal = False
    is_success = False
    is_failure = False
    new_successes = current_successes
    new_failures = current_failures

    if roll == _NAT20:
        if nat20_mode == DeathSaveNat20Mode.REGAIN_HP:
            is_nat20_heal = True
            is_success = True
            # Counters will be reset by the caller when is_nat20_heal is True
            new_successes = 0
            new_failures = 0
        else:  # DOUBLE_SUCCESS
            is_success = True
            new_successes = min(current_successes + 2, _SAVES_TO_STABILIZE)
    elif roll == _NAT1:
        is_failure = True
        new_failures = min(current_failures + 2, _SAVES_TO_DIE)
    elif roll >= _SUCCESS_THRESHOLD:
        is_success = True
        new_successes = current_successes + 1
    else:
        is_failure = True
        new_failures = current_failures + 1

    is_stabilized = (not is_nat20_heal) and new_successes >= _SAVES_TO_STABILIZE
    is_slain = new_failures >= _SAVES_TO_DIE

    if is_stabilized or is_slain:
        new_successes = 0
        new_failures = 0

    return DeathSaveResult(
        roll=roll,
        is_success=is_success,
        is_failure=is_failure,
        is_stabilized=is_stabilized,
        is_slain=is_slain,
        is_nat20_heal=is_nat20_heal,
        successes_after=new_successes,
        failures_after=new_failures,
    )


def character_is_dying(character: "Character") -> bool:
    """Return True when the character is in the dying state (0 HP, HP set).

    A character whose max_hp is -1 (never configured) is not considered dying.
    """
    return (
        character.max_hp is not None
        and character.max_hp >= 0
        and character.current_hp is not None
        and character.current_hp <= 0
    )
