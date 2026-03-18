"""Placement modes for enemies added to an active encounter."""

import enum


class EnemyPlacementMode(enum.Enum):
    """Options for where a mid-combat enemy enters the initiative order."""

    TOP = "top"
    BOTTOM = "bottom"
    AFTER_CURRENT = "after_current"
    ROLL = "roll"
