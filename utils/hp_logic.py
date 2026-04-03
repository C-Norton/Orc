"""HP arithmetic helpers: damage, healing, temp HP, and amount parsing."""

from utils.strings import Strings


def apply_damage(current_hp: int, temp_hp: int, damage: int) -> tuple[int, int]:
    """Apply damage to a character, absorbing through temp HP first.

    HP is clamped to a minimum of 0 — it never goes negative.  Callers that
    need to check for massive damage or the downed state must compare the
    returned new_hp against 0 and the raw damage against max_hp themselves.

    Args:
        current_hp: The character's current hit points before damage.
        temp_hp: The character's current temporary hit points.
        damage: The amount of damage to apply.

    Returns:
        A tuple of (new_hp, new_temp_hp) after absorbing damage.
    """
    if temp_hp > 0:
        absorbed = min(temp_hp, damage)
        remaining = damage - absorbed
        return max(0, current_hp - remaining), temp_hp - absorbed
    else:
        return max(0, current_hp - damage), 0


def apply_temp_hp(current_temp: int, new_temp: int) -> int:
    """Return the effective temp HP after an application.

    Per 5e rules, temporary HP does not stack — the higher value wins.
    """
    return max(current_temp, new_temp)


def apply_healing(current_hp: int, max_hp: int, heal: int) -> int:
    """Return HP after healing, clamped to max_hp."""
    return min(max_hp, current_hp + heal)


def set_max_hp(max_hp: int) -> int:
    """Validate and return max_hp. Raises ValueError if less than 1."""
    if max_hp < 1:
        raise ValueError(Strings.ERROR_INVALID_MAX_HP)
    return max_hp


def parse_amount(amount: int | str) -> int:
    """Parse a damage/heal amount: accepts int, plain integer string, or any dice expression
    (e.g. '10', '2d6+3', '1d8+1d4+2').  Named modifiers are not supported here."""
    if isinstance(amount, int):
        return amount
    s = str(amount).strip()
    try:
        return int(s)
    except ValueError:
        pass
    from dice_roller import parse_expression_tokens, evaluate_expression

    tokens = parse_expression_tokens(s)
    result = evaluate_expression(tokens)  # raises ValueError if named tokens found
    return result.total
