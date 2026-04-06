"""Wizard state dataclass and database persistence helpers.

``WizardState`` holds all data collected across the character creation wizard.
``save_character_from_wizard`` validates and persists it to the database.
The snapshot helpers allow section views to offer discard-changes behaviour.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from enums.character_class import CharacterClass
from enums.skill_proficiency_status import SkillProficiencyStatus
from models import Attack, Character, CharacterSkill, ClassLevel
from utils.class_data import apply_class_save_profs, calculate_max_hp
from utils.constants import SKILL_TO_STAT
from utils.db_helpers import get_or_create_user_server
from utils.limits import MAX_ATTACKS_PER_CHARACTER, MAX_CHARACTERS_PER_USER
from utils.logging_config import get_logger
from utils.strings import Strings
from utils.weapon_utils import (
    calculate_weapon_hit_modifier,
    parse_weapon_fields,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ALL_STATS: list[str] = [
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
]

_STAT_DISPLAY: dict[str, str] = {
    "strength": "STR",
    "dexterity": "DEX",
    "constitution": "CON",
    "intelligence": "INT",
    "wisdom": "WIS",
    "charisma": "CHA",
}

_SKILLS: list[str] = list(SKILL_TO_STAT.keys())

# Maximum number of classes a single character can have in the wizard.
_MAX_CLASSES = 5

# Maximum total character level across all classes (5e 2024 cap).
_MAX_CHARACTER_LEVEL = 20

# Maximum remove-buttons shown for existing attacks in the weapons section
# (3 Discord button rows × 5 buttons per row = 15).
_MAX_EXISTING_WEAPON_BUTTONS = 15

# Wizard timeout in seconds (10 minutes).
_WIZARD_TIMEOUT = 600

# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

# Maps each section key to the WizardState field names it owns.
_SECTION_FIELDS: dict[str, list[str]] = {
    "class_level": ["classes_and_levels", "saving_throws", "saves_explicitly_set"],
    "ability_scores": [
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
        "initiative_bonus",
    ],
    "ac": ["ac"],
    "saving_throws": ["saving_throws", "saves_explicitly_set"],
    "skills": ["skills"],
    "hp": ["hp_override"],
    "weapons": ["weapons_to_add", "existing_attacks", "weapons_to_remove"],
}


def snapshot_section(state: "WizardState", section: str) -> dict:
    """Capture mutable fields owned by a section for rollback.

    Returns a shallow-copied dict of field names to deep-copied values so
    that in-place mutations (e.g. list appends) do not affect the snapshot.
    """
    snapshot = {}
    for field_name in _SECTION_FIELDS[section]:
        value = getattr(state, field_name)
        snapshot[field_name] = copy.deepcopy(value)
    return snapshot


def restore_section(state: "WizardState", section: str, snapshot: dict) -> None:
    """Restore mutable fields from a snapshot taken before section entry."""
    for field_name, value in snapshot.items():
        setattr(state, field_name, value)


# ---------------------------------------------------------------------------
# Wizard state
# ---------------------------------------------------------------------------


@dataclass
class WizardState:
    """All data collected across the character creation wizard sections.

    ``classes_and_levels`` stores (CharacterClass, level) pairs to support
    multiclassing.  Convenience properties ``character_class``, ``level``,
    and ``total_level`` provide quick access to common values.

    ``weapons_to_add`` holds raw Open5e weapon dicts queued in the Weapons
    section.  They are committed to the database when the wizard finishes.

    ``sections_completed`` tracks which section keys the user has explicitly
    saved, enabling the hub to display a green/red completion indicator per
    section.
    """

    user_discord_id: str
    guild_discord_id: str
    guild_name: str
    name: str = ""
    classes_and_levels: list[tuple[CharacterClass, int]] = field(default_factory=list)
    strength: int | None = None
    dexterity: int | None = None
    constitution: int | None = None
    intelligence: int | None = None
    wisdom: int | None = None
    charisma: int | None = None
    initiative_bonus: int | None = None
    ac: int | None = None
    hp_override: int | None = None
    # Saving throws: stat_name -> bool (defaults all False; updated when
    # first class is selected or user explicitly toggles)
    saving_throws: dict[str, bool] = field(
        default_factory=lambda: {s: False for s in _ALL_STATS}
    )
    # Skills toggled to Proficient in the Skills section
    skills: dict[str, bool] = field(default_factory=dict)
    # True when the user explicitly configured saves (not just class defaults)
    saves_explicitly_set: bool = False
    # Sections where the user pressed "Save & Return"
    sections_completed: set[str] = field(default_factory=set)
    # Raw Open5e weapon dicts queued for creation when the wizard finishes
    weapons_to_add: list[dict] = field(default_factory=list)
    # Edit mode: ID of the character being edited (None for new character creation)
    edit_character_id: int | None = None
    # Edit mode: (attack_id, attack_name) pairs for attacks currently on the character
    existing_attacks: list[tuple[int, str]] = field(default_factory=list)
    # Edit mode: IDs of existing attacks to delete when the wizard finishes
    weapons_to_remove: list[int] = field(default_factory=list)

    @property
    def character_class(self) -> CharacterClass | None:
        """Return the first class in ``classes_and_levels``, or ``None``."""
        return self.classes_and_levels[0][0] if self.classes_and_levels else None

    @property
    def level(self) -> int | None:
        """Return the level of the first class, or ``None``."""
        return self.classes_and_levels[0][1] if self.classes_and_levels else None

    @property
    def total_level(self) -> int:
        """Return the sum of all class levels."""
        return sum(lv for _, lv in self.classes_and_levels)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _apply_hp_to_character(
    char: Character,
    state: WizardState,
    clear_on_no_calc: bool = False,
) -> None:
    """Apply HP from *state* to *char*.

    Manual override takes precedence.  Falls back to auto-calculation via
    ``calculate_max_hp``; when that returns -1 (missing class or CON) the
    behaviour depends on *clear_on_no_calc*:

    - ``False`` (create mode): leave HP untouched so the field stays at its
      default value.
    - ``True`` (edit mode): reset both fields to -1 to clear any previous HP.
    """
    if state.hp_override is not None:
        char.max_hp = state.hp_override
        char.current_hp = state.hp_override
    else:
        new_max = calculate_max_hp(char)
        if new_max != -1:
            char.max_hp = new_max
            char.current_hp = new_max
        elif clear_on_no_calc:
            char.max_hp = -1
            char.current_hp = -1


def _add_attack_from_weapon_data(
    weapon_data: dict,
    character: Character,
    db: Session,
) -> None:
    """Create an Attack record on *character* from a raw Open5e weapon dict.

    Calculates the to-hit modifier using the character's current stats.
    The caller is responsible for calling ``db.flush()`` / ``db.commit()``.
    """
    # Extract all weapon fields from the API dict in one call
    fields = parse_weapon_fields(weapon_data)
    hit_modifier_result = calculate_weapon_hit_modifier(
        character, fields.properties, fields.range_normal_float
    )
    db.add(
        Attack(
            character_id=character.id,
            name=fields.name,
            hit_modifier=hit_modifier_result.total,
            damage_formula=fields.damage_dice,
            damage_type=fields.damage_type_name,
            weapon_category=fields.weapon_category,
            two_handed_damage=fields.two_handed_damage,
            properties_json=fields.properties_json,
            is_imported=True,
        )
    )


def save_character_from_wizard(
    state: WizardState,
    interaction: discord.Interaction,
    db: Session,
) -> tuple[Character | None, str | None]:
    """Validate and persist a character from *state*.

    Creates all ClassLevel records for every entry in
    ``state.classes_and_levels``.  Save proficiencies from the first class
    are applied automatically (subsequent classes do not grant additional
    saving throw proficiencies per 5e 2024 rules).

    If ``state.hp_override`` is set it takes precedence over the
    auto-calculated value.

    Any weapons queued in ``state.weapons_to_add`` are created as Attack
    records, up to ``MAX_ATTACKS_PER_CHARACTER``.

    Returns ``(character, None)`` on success or ``(None, error_message)``
    on validation failure.  The caller is responsible for calling
    ``db.commit()`` after a successful return.
    """
    if len(state.name) > 100:
        return None, Strings.CHAR_CREATE_NAME_LIMIT

    user, server = get_or_create_user_server(db, interaction)

    char_count = (
        db.query(Character).filter_by(user_id=user.id, server_id=server.id).count()
    )
    if char_count >= MAX_CHARACTERS_PER_USER:
        return None, Strings.ERROR_LIMIT_CHARACTERS.format(
            limit=MAX_CHARACTERS_PER_USER
        )

    existing = (
        db.query(Character).filter_by(user=user, server=server, name=state.name).first()
    )
    if existing:
        return None, Strings.CHAR_EXISTS.format(name=state.name)

    # Deactivate all current characters for this user in this server
    db.query(Character).filter_by(user=user, server=server).update({"is_active": False})

    char = Character(name=state.name, user=user, server=server, is_active=True)
    db.add(char)
    db.flush()

    # Class & Level — first class gets save proficiencies applied
    for index, (class_enum, class_level) in enumerate(state.classes_and_levels):
        db.add(
            ClassLevel(
                character_id=char.id,
                class_name=class_enum.value,
                level=class_level,
            )
        )
        if index == 0:
            # Flush so that char.class_levels is populated for HP calc
            db.flush()
            db.refresh(char)
            apply_class_save_profs(char, class_enum)

    if state.classes_and_levels:
        db.flush()
        db.refresh(char)

    # Ability scores
    for stat in _ALL_STATS:
        value = getattr(state, stat)
        if value is not None:
            setattr(char, stat, value)
    if state.initiative_bonus is not None:
        char.initiative_bonus = state.initiative_bonus

    # HP — manual override takes precedence over auto-calculation
    _apply_hp_to_character(char, state)

    # AC
    if state.ac is not None:
        char.ac = state.ac

    # Saving throws — explicit user configuration overrides class defaults
    if state.saves_explicitly_set:
        for stat in _ALL_STATS:
            setattr(char, f"st_prof_{stat}", state.saving_throws.get(stat, False))
    char.saves_explicitly_configured = state.saves_explicitly_set
    char.hp_manually_set = state.hp_override is not None

    # Skill proficiencies — only store proficient entries
    for skill_name, is_proficient in state.skills.items():
        if is_proficient:
            db.add(
                CharacterSkill(
                    character_id=char.id,
                    skill_name=skill_name,
                    proficiency=SkillProficiencyStatus.PROFICIENT,
                )
            )

    # Weapons queued during the Weapons section (capped at per-character limit)
    for weapon_data in state.weapons_to_add[:MAX_ATTACKS_PER_CHARACTER]:
        _add_attack_from_weapon_data(weapon_data, char, db)

    db.flush()
    return char, None


def character_to_wizard_state(
    char: Character, interaction: discord.Interaction
) -> "WizardState":
    """Build a pre-filled WizardState from an existing Character for edit mode.

    All values are loaded from *char* so the wizard opens with every section
    pre-filled and coloured green.  ``edit_character_id`` is set so that
    ``save_character_from_wizard`` knows to update instead of create.
    """
    state = WizardState(
        user_discord_id=str(interaction.user.id),
        guild_discord_id=str(interaction.guild_id),
        guild_name=getattr(interaction.guild, "name", str(interaction.guild_id)),
        name=char.name,
        edit_character_id=char.id,
    )

    # Classes and levels (preserve insertion order via id sort)
    state.classes_and_levels = [
        (CharacterClass(cl.class_name), cl.level)
        for cl in sorted(char.class_levels, key=lambda cl: cl.id)
    ]

    # Ability scores
    for stat in _ALL_STATS:
        value = getattr(char, stat)
        if value is not None:
            setattr(state, stat, value)
    state.initiative_bonus = char.initiative_bonus

    # AC
    state.ac = char.ac

    # HP — only treat existing max_hp as a manual override when the character
    # record says it was explicitly set by the user; auto-calculated HP should
    # remain blue (auto-calc) in the edit wizard rather than appearing green.
    if char.max_hp != -1 and char.hp_manually_set:
        state.hp_override = char.max_hp

    # Saving throws — load existing profs.  Restore the explicit-set flag from
    # the persisted value so that auto-applied class defaults stay blue instead
    # of appearing green when the wizard is reopened.
    for stat in _ALL_STATS:
        state.saving_throws[stat] = getattr(char, f"st_prof_{stat}", False)
    state.saves_explicitly_set = char.saves_explicitly_configured

    # Skills — only proficient entries are stored
    for skill in char.skills:
        if skill.proficiency == SkillProficiencyStatus.PROFICIENT:
            state.skills[skill.skill_name] = True

    # Existing attacks (id + name) — displayed with remove buttons in weapons section
    state.existing_attacks = [
        (attack.id, attack.name) for attack in sorted(char.attacks, key=lambda a: a.id)
    ]

    # Mark populated sections as completed so hub buttons show green
    if state.classes_and_levels:
        state.sections_completed.add("class_level")
    if any(getattr(state, s) is not None for s in _ALL_STATS):
        state.sections_completed.add("ability_scores")
    if state.ac is not None:
        state.sections_completed.add("ac")
    state.sections_completed.add("saving_throws")
    if state.skills:
        state.sections_completed.add("skills")
    if char.hp_manually_set:
        state.sections_completed.add("hp")
    if state.existing_attacks:
        state.sections_completed.add("weapons")

    return state


def update_character_from_wizard(
    state: WizardState,
    db: Session,
) -> tuple[Character | None, str | None]:
    """Apply wizard *state* to the existing character being edited.

    Replaces class levels, ability scores, saving throws, skills, AC, and HP
    in-place on the character record.  Attacks listed in
    ``state.weapons_to_remove`` are deleted; attacks in ``state.weapons_to_add``
    are created up to ``MAX_ATTACKS_PER_CHARACTER``.

    Returns ``(character, None)`` on success or ``(None, error_message)``
    on failure.  The caller is responsible for calling ``db.commit()``.
    """
    char = db.get(Character, state.edit_character_id)
    if not char:
        return None, Strings.ACTIVE_CHARACTER_NOT_FOUND

    # Class levels — delete all existing, recreate from state
    for class_level in list(char.class_levels):
        db.delete(class_level)
    db.flush()

    for index, (class_enum, class_level) in enumerate(state.classes_and_levels):
        db.add(
            ClassLevel(
                character_id=char.id,
                class_name=class_enum.value,
                level=class_level,
            )
        )
        if index == 0:
            db.flush()
            db.refresh(char)

    if state.classes_and_levels:
        db.flush()
        db.refresh(char)

    # Ability scores (allow clearing any stat to None)
    for stat in _ALL_STATS:
        setattr(char, stat, getattr(state, stat))
    char.initiative_bonus = state.initiative_bonus

    # HP — manual override takes precedence; fall back to auto-calculation
    _apply_hp_to_character(char, state, clear_on_no_calc=True)

    # AC
    char.ac = state.ac

    # Saving throws — always write from state (saves_explicitly_set is always
    # True for edit mode, but apply regardless to keep logic simple)
    for stat in _ALL_STATS:
        setattr(char, f"st_prof_{stat}", state.saving_throws.get(stat, False))
    char.saves_explicitly_configured = state.saves_explicitly_set
    char.hp_manually_set = state.hp_override is not None

    # Skills — delete all existing, recreate proficient ones from state
    for skill in list(char.skills):
        db.delete(skill)
    db.flush()
    for skill_name, is_proficient in state.skills.items():
        if is_proficient:
            db.add(
                CharacterSkill(
                    character_id=char.id,
                    skill_name=skill_name,
                    proficiency=SkillProficiencyStatus.PROFICIENT,
                )
            )

    # Weapons — remove attacks marked for deletion (verify ownership to be safe)
    for attack_id in state.weapons_to_remove:
        attack = db.get(Attack, attack_id)
        if attack and attack.character_id == char.id:
            db.delete(attack)
    db.flush()

    # Add new weapons, respecting the per-character limit
    current_attack_count = db.query(Attack).filter_by(character_id=char.id).count()
    weapon_count = 0
    for weapon_data in state.weapons_to_add:
        if current_attack_count + weapon_count >= MAX_ATTACKS_PER_CHARACTER:
            break
        _add_attack_from_weapon_data(weapon_data, char, db)
        weapon_count += 1

    db.flush()
    return char, None
