from utils.strings import Strings

def apply_damage(current_hp: int, temp_hp: int, damage: int) -> tuple[int, int]:
    if temp_hp > 0:
        temp_hp -= damage
        if temp_hp > 0:
            return current_hp, temp_hp
        else:
            return current_hp + temp_hp, 0
    else:
        return current_hp - damage, 0


def apply_temp_hp(current_temp: int, new_temp: int) -> int:
    return max(current_temp, new_temp)


def apply_healing(current_hp: int, max_hp: int, heal: int) -> int:
    return min(max_hp, current_hp + heal)


def set_max_hp(max_hp: int) -> int:
    if max_hp < 1:
        raise ValueError(Strings.ERROR_INVALID_MAX_HP)
    return max_hp


def parse_amount(amount) -> int:
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
    result = evaluate_expression(tokens)   # raises ValueError if named tokens found
    return result.total