"""Enum of all 12 standard SRD character classes."""

from enum import Enum


class CharacterClass(str, Enum):
    """5e 2024 SRD character classes."""

    BARBARIAN = "Barbarian"
    BARD = "Bard"
    CLERIC = "Cleric"
    DRUID = "Druid"
    FIGHTER = "Fighter"
    MONK = "Monk"
    PALADIN = "Paladin"
    RANGER = "Ranger"
    ROGUE = "Rogue"
    SORCERER = "Sorcerer"
    WARLOCK = "Warlock"
    WIZARD = "Wizard"
    OTHER = "UA/Homebrew"
