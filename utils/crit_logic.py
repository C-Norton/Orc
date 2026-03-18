"""Critical hit damage calculation utilities."""

import re
from dataclasses import dataclass
from typing import List

from dice_roller import roll_dice
from enums.crit_rule import CritRule
from utils.logging_config import get_logger

logger = get_logger(__name__)

_FORMULA_RE = re.compile(r'^(\d+)?d(\d+)([+-]\d+)?$', re.IGNORECASE)


@dataclass
class CritResult:
    """The outcome of applying a critical hit rule to a damage formula.

    Attributes:
        rolls: Individual die results used for display.
        modifier: Flat modifier included in the roll (not doubled unless rule
            specifies the full total is doubled).
        total: Final damage total after the crit rule is applied.
        grants_inspiration: True only for PERKINS — the player earns Inspiration.
    """

    rolls: List[int]
    modifier: int
    total: int
    grants_inspiration: bool


def apply_crit_damage(formula: str, crit_rule: CritRule) -> CritResult:
    """Apply a critical hit rule to a damage formula and return the result.

    For DOUBLE_DICE the number of dice is doubled; the flat modifier is added
    only once.  For DOUBLE_DAMAGE the full total (dice + modifier) is doubled.
    For MAX_DAMAGE every die shows its maximum face value.  For PERKINS a normal
    roll is made and ``grants_inspiration`` is set to True.  For NONE no crit
    modification is applied.

    Args:
        formula: A standard dice notation string (e.g. '2d6+3').
        crit_rule: The CritRule to apply.

    Returns:
        A CritResult containing the rolls, modifier, adjusted total, and
        inspiration flag.
    """
    normalised = formula.lower().replace(" ", "")
    match = _FORMULA_RE.match(normalised)

    if not match:
        # Graceful fallback for formulas that don't fit the simple pattern.
        logger.warning(f"apply_crit_damage: unexpected formula '{formula}'; falling back to normal roll")
        rolls, modifier, total = roll_dice(formula)
        return CritResult(rolls=rolls, modifier=modifier, total=total, grants_inspiration=False)

    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if crit_rule == CritRule.DOUBLE_DICE:
        modifier_str = f"{modifier:+d}" if modifier != 0 else ""
        crit_formula = f"{count * 2}d{sides}{modifier_str}"
        rolls, mod, total = roll_dice(crit_formula)
        logger.debug(f"apply_crit_damage DOUBLE_DICE: {formula} → {crit_formula}, total={total}")
        return CritResult(rolls=rolls, modifier=mod, total=total, grants_inspiration=False)

    if crit_rule == CritRule.DOUBLE_DAMAGE:
        rolls, mod, total = roll_dice(formula)
        doubled_total = total * 2
        logger.debug(f"apply_crit_damage DOUBLE_DAMAGE: {formula}, total={total} → {doubled_total}")
        return CritResult(rolls=rolls, modifier=mod, total=doubled_total, grants_inspiration=False)

    if crit_rule == CritRule.MAX_DAMAGE:
        rolls = [sides] * count
        total = sum(rolls) + modifier
        logger.debug(f"apply_crit_damage MAX_DAMAGE: {formula}, total={total}")
        return CritResult(rolls=rolls, modifier=modifier, total=total, grants_inspiration=False)

    if crit_rule == CritRule.PERKINS:
        rolls, mod, total = roll_dice(formula)
        logger.debug(f"apply_crit_damage PERKINS: {formula}, total={total} (inspiration granted)")
        return CritResult(rolls=rolls, modifier=mod, total=total, grants_inspiration=True)

    # CritRule.NONE — no modification
    rolls, mod, total = roll_dice(formula)
    logger.debug(f"apply_crit_damage NONE: {formula}, total={total}")
    return CritResult(rolls=rolls, modifier=mod, total=total, grants_inspiration=False)
