from enum import Enum


class DeathSaveNat20Mode(str, Enum):
    """Controls how a natural 20 on a death saving throw is resolved."""

    REGAIN_HP = "regain_hp"          # 5e 2024 RAW: regain 1 HP and stop dying
    DOUBLE_SUCCESS = "double_success"  # House rule: count as two successes
