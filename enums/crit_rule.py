from enum import Enum


class CritRule(str, Enum):
    """Controls how a natural 20 attack roll is resolved for a party."""

    DOUBLE_DICE = "double_dice"     # Roll 2× the dice, add modifier once (default)
    PERKINS = "perkins"             # Normal roll; player gains Inspiration
    DOUBLE_DAMAGE = "double_damage" # Roll normally, double the total
    MAX_DAMAGE = "max_damage"       # All dice show their maximum face value
    NONE = "none"                   # No special crit handling
