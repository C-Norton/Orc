"""Enum representing the possible proficiency levels for a character skill."""

from enum import Enum


class SkillProficiencyStatus(Enum):
    NOT_PROFICIENT = "not_proficient"
    PROFICIENT = "proficient"
    EXPERTISE = "expertise"
    JACK_OF_ALL_TRADES = "jack_of_all_trades"
    OVERRIDDEN = "overridden"
