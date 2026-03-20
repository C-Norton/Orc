"""Enum representing the two weapon categories in D&D 5e 2024."""

from enum import Enum


class WeaponCategory(str, Enum):
    """D&D 5e 2024 weapon category.

    Controls which class proficiencies allow a character to add their
    proficiency bonus to attack rolls with a given weapon.
    """

    SIMPLE = "Simple"
    MARTIAL = "Martial"
