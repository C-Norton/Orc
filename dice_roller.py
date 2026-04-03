"""Dice rolling engine: tokeniser, expression evaluator, and simple roll API.

Public surface:
- ``parse_expression_tokens`` / ``evaluate_expression`` — multi-term expression API
- ``has_named_tokens`` / ``get_named_tokens`` — token introspection helpers
- ``roll_dice`` — legacy single-formula API (e.g. '2d6+3')
"""

import random
import re
from dataclasses import dataclass
from typing import Callable, Optional

from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches bare dice groups with no flat modifier: NdM or dM.
_DICE_RE = re.compile(r"^(\d+)?d(\d+)$", re.IGNORECASE)
# Matches a single dice formula including an optional flat modifier: NdM[+-]K.
_DICE_WITH_MOD_RE = re.compile(r"^(\d+)?d(\d+)([+-]\d+)?$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\d+$")

# Guard limits for dice rolls.
_MAX_DICE_COUNT = 1_000
_MAX_DICE_SIDES = 100_000


# ---------------------------------------------------------------------------
# Data classes returned by the new expression API
# ---------------------------------------------------------------------------


@dataclass
class TermResult:
    sign: int  # +1 or -1 (from the expression)
    raw: str  # original token as typed (lowercased)
    label: str  # display string, e.g. "2d8[3,5]=8" or "Perception(+5)"
    rolls: list[int]  # individual dice rolls; empty for flat numbers / named
    value: (
        int  # unsigned magnitude; for named mods this is the raw mod (may be negative)
    )


@dataclass
class ExpressionResult:
    terms: list[TermResult]
    total: int

    def breakdown(self) -> str:
        """Human-readable breakdown, e.g. '2d8[3,5]=8 − Initiative(-2) + 3'."""
        parts = []
        for i, term in enumerate(self.terms):
            if i == 0:
                prefix = "−" if term.sign == -1 else ""
            else:
                prefix = " − " if term.sign == -1 else " + "
            parts.append(f"{prefix}{term.label}")
        return "".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_tokens(notation: str) -> list[tuple[int, str]]:
    """Split a notation string into (sign, token) pairs (tokens lowercased)."""
    parts = re.split(r"([+-])", notation.strip())
    result = []
    sign = 1
    for part in parts:
        part = part.strip()
        if part == "+":
            sign = 1
        elif part == "-":
            sign = -1
        elif part:
            result.append((sign, part.lower()))
            sign = 1
    return result


def _roll_dice_group(
    token: str, advantage: Optional[str] = None
) -> tuple[list[int], int, str]:
    """Roll a dice-group token (e.g. '2d6', 'd20').

    Returns (rolls, total, display_label).
    Advantage / disadvantage only applies to single d20 rolls.
    """
    m = _DICE_RE.match(token)
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))

    if count > _MAX_DICE_COUNT or sides > _MAX_DICE_SIDES:
        raise ValueError(Strings.ERROR_DICE_LIMIT)

    # Advantage / disadvantage: only for a single d20
    if sides == 20 and count == 1 and advantage in ("advantage", "disadvantage"):
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20)
        if advantage == "advantage":
            kept, discarded = max(roll1, roll2), min(roll1, roll2)
            label = f"{token}[{kept}↑,{discarded}]"
        else:
            kept, discarded = min(roll1, roll2), max(roll1, roll2)
            label = f"{token}[{kept}↓,{discarded}]"
        return [kept, discarded], kept, label

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    rolls_str = ",".join(str(r) for r in rolls)
    label = f"{token}[{rolls_str}]" if count == 1 else f"{token}[{rolls_str}]={total}"
    return rolls, total, label


# ---------------------------------------------------------------------------
# Public expression API
# ---------------------------------------------------------------------------


def parse_expression_tokens(notation: str) -> list[tuple[int, str]]:
    """Tokenise a complex dice expression into (sign, token) pairs.

    e.g. '2d8-Initiative+8+2d6+Perception'
      → [(+1,'2d8'), (-1,'initiative'), (+1,'8'), (+1,'2d6'), (+1,'perception')]

    All tokens are lowercased.  Signs default to +1 for the first token.
    """
    return _parse_tokens(notation)


def has_named_tokens(tokens: list[tuple[int, str]]) -> bool:
    """Return True if any token is not a dice group and not a plain integer."""
    return any(not _DICE_RE.match(t) and not _NUMBER_RE.match(t) for _, t in tokens)


def get_named_tokens(tokens: list[tuple[int, str]]) -> list[str]:
    """Return the list of named (non-dice, non-number) token strings."""
    return [t for _, t in tokens if not _DICE_RE.match(t) and not _NUMBER_RE.match(t)]


def evaluate_expression(
    tokens: list[tuple[int, str]],
    named_resolver: Optional[Callable[[str], tuple[int, str]]] = None,
    advantage: Optional[str] = None,
) -> ExpressionResult:
    """Evaluate a tokenised expression.

    named_resolver  callable(name: str) -> (int_value, display_label)
                    Required when any token is not a dice group or integer.
    advantage       'advantage' | 'disadvantage' | None
                    Applies only to single-d20 rolls.
    """
    terms: list[TermResult] = []
    total = 0

    for sign, token in tokens:
        if _DICE_RE.match(token):
            rolls, val, label = _roll_dice_group(token, advantage)
            terms.append(
                TermResult(sign=sign, raw=token, label=label, rolls=rolls, value=val)
            )
            total += sign * val

        elif _NUMBER_RE.match(token):
            val = int(token)
            terms.append(
                TermResult(sign=sign, raw=token, label=token, rolls=[], value=val)
            )
            total += sign * val

        else:
            if named_resolver is None:
                raise ValueError(
                    Strings.ERROR_NAMED_MODIFIER_REQUIRES_CHARACTER.format(token=token)
                )
            int_value, display_label = named_resolver(token)
            terms.append(
                TermResult(
                    sign=sign, raw=token, label=display_label, rolls=[], value=int_value
                )
            )
            total += sign * int_value

    return ExpressionResult(terms=terms, total=total)


# ---------------------------------------------------------------------------
# Legacy simple API (kept for backward compatibility)
# ---------------------------------------------------------------------------


def roll_dice(notation: str) -> tuple[list[int], int, int]:
    """Parse standard single-group dice notation (e.g. '2d6+3') and return
    (individual_rolls, flat_modifier, total).  Use evaluate_expression for
    complex multi-term expressions."""
    logger.debug(f"Rolling dice with notation: {notation}")
    notation = notation.lower().replace(" ", "")
    match = _DICE_WITH_MOD_RE.match(notation)

    if not match:
        logger.debug(f"Invalid dice notation: {notation}")
        raise ValueError(Strings.ERROR_INVALID_DICE)

    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count > _MAX_DICE_COUNT or sides > _MAX_DICE_SIDES:
        logger.warning(f"Dice roll exceeded limits: {count}d{sides}")
        raise ValueError(Strings.ERROR_DICE_LIMIT)

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    logger.debug(
        f"Result for {notation}: rolls={rolls}, modifier={modifier}, total={total}"
    )
    return rolls, modifier, total


# Manual test harness — run `python dice_roller.py` to exercise the tokeniser.
if __name__ == "__main__":
    from utils.logging_config import setup_logging

    setup_logging()
    test_cases = ["1d20", "2d6+3", "d10-1", "3d100", "2d8-initiative+8+2d6+perception"]
    for tc in test_cases:
        logger.info(f"Tokens: {parse_expression_tokens(tc)}")
