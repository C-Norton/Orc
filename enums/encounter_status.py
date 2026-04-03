"""Enum representing the lifecycle states of a combat encounter."""

from enum import Enum


class EncounterStatus(Enum):
    """Tracks whether an encounter is waiting to start, in progress, or finished."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
