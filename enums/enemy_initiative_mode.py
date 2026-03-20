from enum import Enum


class EnemyInitiativeMode(str, Enum):
    """Controls how enemy initiative is rolled when an encounter starts."""

    BY_TYPE = "by_type"  # Default: enemies sharing type_name share one roll
    INDIVIDUAL = "individual"  # Every enemy rolls separately
    SHARED = "shared"  # All enemies share a single roll
