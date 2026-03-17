"""Class-specific D&D 5e data and HP calculation logic."""

from typing import TYPE_CHECKING

from enums.character_class import CharacterClass
from utils.dnd_logic import get_stat_modifier

if TYPE_CHECKING:
    from models.character import Character

# Hit die size for each class.
CLASS_HIT_DICE: dict[CharacterClass, int] = {
    CharacterClass.BARBARIAN: 12,
    CharacterClass.BARD: 8,
    CharacterClass.CLERIC: 8,
    CharacterClass.DRUID: 8,
    CharacterClass.FIGHTER: 10,
    CharacterClass.MONK: 8,
    CharacterClass.PALADIN: 10,
    CharacterClass.RANGER: 10,
    CharacterClass.ROGUE: 8,
    CharacterClass.SORCERER: 6,
    CharacterClass.WARLOCK: 8,
    CharacterClass.WIZARD: 6,
    CharacterClass.OTHER: 8,  # Homebrew — default to d8; user should verify with their source material.
}

# Saving throw proficiencies granted at first level for each class.
# Keys are CharacterClass values; values are lists of stat attribute names
# (e.g. "strength", "constitution") as they appear on the Character model.
CLASS_SAVE_PROFS: dict[CharacterClass, list[str]] = {
    CharacterClass.BARBARIAN: ["strength", "constitution"],
    CharacterClass.BARD: ["dexterity", "charisma"],
    CharacterClass.CLERIC: ["wisdom", "charisma"],
    CharacterClass.DRUID: ["intelligence", "wisdom"],
    CharacterClass.FIGHTER: ["strength", "constitution"],
    CharacterClass.MONK: ["strength", "dexterity"],
    CharacterClass.PALADIN: ["wisdom", "charisma"],
    CharacterClass.RANGER: ["strength", "dexterity"],
    CharacterClass.ROGUE: ["dexterity", "intelligence"],
    CharacterClass.SORCERER: ["constitution", "charisma"],
    CharacterClass.WARLOCK: ["wisdom", "charisma"],
    CharacterClass.WIZARD: ["intelligence", "wisdom"],
    # Homebrew — no automatic saves granted; use /set_saving_throws to assign manually.
    CharacterClass.OTHER: [],
}

_ALL_STATS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]


def get_class_save_profs(character_class: CharacterClass) -> list[str]:
    """Return the list of stat names that gain saving throw proficiency for *character_class*."""
    return CLASS_SAVE_PROFS[character_class]


def calculate_max_hp(character: "Character") -> int:
    """Calculate maximum HP for *character* using 5e rules.

    - The first level overall uses the maximum hit die value.
    - Every subsequent level uses ``floor(hit_die / 2) + 1`` (the average rounded up).
    - CON modifier is added to every level; minimum 1 HP granted per level.
    - Returns ``-1`` if CON is not yet set or there are no class levels.

    Class levels are processed in insertion order (sorted by primary key) so that
    the "first class" is always the one created first, which matters for multiclassing.
    """
    if character.constitution is None:
        return -1

    class_levels = sorted(character.class_levels, key=lambda cl: cl.id)
    if not class_levels:
        return -1

    con_mod = get_stat_modifier(character.constitution)
    total_hp = 0
    is_first_level = True

    for cl in class_levels:
        hd = CLASS_HIT_DICE[CharacterClass(cl.class_name)]
        avg_roll = hd // 2 + 1
        for _ in range(cl.level):
            if is_first_level:
                total_hp += max(1, hd + con_mod)
                is_first_level = False
            else:
                total_hp += max(1, avg_roll + con_mod)

    return total_hp


def apply_class_save_profs(character: "Character", character_class: CharacterClass) -> None:
    """Overwrite all six saving throw proficiencies on *character* to match *character_class*.

    This should only be called when creating a fresh character (first class assignment).
    For multiclassing, saving throw proficiencies are not granted or removed.
    """
    granted = CLASS_SAVE_PROFS[character_class]
    for stat in _ALL_STATS:
        setattr(character, f"st_prof_{stat}", stat in granted)
