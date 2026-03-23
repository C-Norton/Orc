"""Enum representing the supported D&D SRD ruleset editions for weapon lookup."""

from enum import Enum


class RulesetEdition(str, Enum):
    """Identifies which SRD edition to use when searching for weapons via Open5e.

    The Open5e API hosts both the 2014 SRD (``srd-2014``) and the 2024 SRD
    (``srd-2024``).  Many weapons share a name across both editions but may
    differ in properties, damage dice, or mastery options.
    """

    RULES_2014 = "srd-2014"
    RULES_2024 = "srd-2024"

    @property
    def display_year(self) -> str:
        """Return the human-readable year string (e.g. ``"2024"``)."""
        return "2024" if self == RulesetEdition.RULES_2024 else "2014"
