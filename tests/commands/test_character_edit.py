"""Tests for the character edit wizard feature.

Covers:
- ``character_to_wizard_state`` — loading an existing character into a WizardState
- ``update_character_from_wizard`` — persisting wizard state back to an existing character
- ``_WeaponRemoveButton.callback`` — removes attack from state and queues it for deletion
- ``_WeaponSelectButton.callback`` in edit mode — blocked when weapon already exists on char
- ``_build_hub_embed`` — title/description switches to edit strings in edit mode
- ``_finish_wizard`` — routes to ``update_character_from_wizard`` when edit_character_id is set
"""

from __future__ import annotations

import pytest
import discord

from commands.wizard.state import (
    WizardState,
    character_to_wizard_state,
    update_character_from_wizard,
)
from commands.wizard.buttons import _WeaponRemoveButton, _WeaponSelectButton
from commands.wizard.hub_view import _build_hub_embed
from enums.character_class import CharacterClass
from enums.skill_proficiency_status import SkillProficiencyStatus
from models import Attack, Character, CharacterSkill, ClassLevel
from tests.conftest import make_interaction
from utils.limits import MAX_ATTACKS_PER_CHARACTER
from utils.strings import Strings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wizard_interaction(mocker):
    """Build a minimal mock interaction suitable for wizard state helpers."""
    return make_interaction(mocker)


def _make_edit_state(
    character: Character,
    mocker,
) -> WizardState:
    """Return a WizardState built from *character* using a mock interaction."""
    interaction = _make_wizard_interaction(mocker)
    return character_to_wizard_state(character, interaction)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fighter_character(db_session, sample_user, sample_server):
    """Fighter 5 with all ability scores, AC, two save profs, and one skill."""
    char = Character(
        name="Aldric",
        user=sample_user,
        server=sample_server,
        is_active=True,
        strength=16,
        dexterity=14,
        constitution=15,
        intelligence=10,
        wisdom=12,
        charisma=8,
        ac=17,
        max_hp=47,
        current_hp=47,
        initiative_bonus=2,
        st_prof_strength=True,
        st_prof_constitution=True,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=5))
    db_session.flush()
    db_session.add(
        CharacterSkill(
            character_id=char.id,
            skill_name="Athletics",
            proficiency=SkillProficiencyStatus.PROFICIENT,
        )
    )
    db_session.add(
        Attack(
            character_id=char.id,
            name="Longsword",
            hit_modifier=5,
            damage_formula="1d8+3",
        )
    )
    db_session.commit()
    db_session.refresh(char)
    return char


@pytest.fixture
def empty_character(db_session, sample_user, sample_server):
    """Character with no class levels, no stats, no AC, no HP override, no attacks."""
    char = Character(
        name="Blank",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(char)
    db_session.commit()
    db_session.refresh(char)
    return char


@pytest.fixture
def multiclass_character(db_session, sample_user, sample_server):
    """Fighter 3 / Rogue 2 multiclass character."""
    char = Character(
        name="Multiblade",
        user=sample_user,
        server=sample_server,
        is_active=True,
        strength=14,
        dexterity=16,
        constitution=13,
        intelligence=10,
        wisdom=10,
        charisma=10,
        ac=15,
        max_hp=30,
        current_hp=30,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=3))
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Rogue", level=2))
    db_session.commit()
    db_session.refresh(char)
    return char


# ---------------------------------------------------------------------------
# character_to_wizard_state — happy path
# ---------------------------------------------------------------------------


async def test_character_to_wizard_state_loads_name(fighter_character, mocker):
    """The character name must be copied into state.name."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.name == "Aldric"


async def test_character_to_wizard_state_sets_edit_character_id(
    fighter_character, mocker
):
    """edit_character_id must be set to the character's primary key."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.edit_character_id == fighter_character.id


async def test_character_to_wizard_state_loads_class_levels(
    fighter_character, mocker
):
    """Classes and levels must be loaded in id order."""
    state = _make_edit_state(fighter_character, mocker)
    assert len(state.classes_and_levels) == 1
    class_enum, level = state.classes_and_levels[0]
    assert class_enum == CharacterClass.FIGHTER
    assert level == 5


async def test_character_to_wizard_state_loads_multiclass_order(
    multiclass_character, mocker
):
    """Multiclass character's classes must appear in id (insertion) order."""
    state = _make_edit_state(multiclass_character, mocker)
    assert len(state.classes_and_levels) == 2
    assert state.classes_and_levels[0][0] == CharacterClass.FIGHTER
    assert state.classes_and_levels[1][0] == CharacterClass.ROGUE


async def test_character_to_wizard_state_loads_ability_scores(
    fighter_character, mocker
):
    """All six ability scores must match the character's stored values."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.strength == 16
    assert state.dexterity == 14
    assert state.constitution == 15
    assert state.intelligence == 10
    assert state.wisdom == 12
    assert state.charisma == 8


async def test_character_to_wizard_state_loads_initiative_bonus(
    fighter_character, mocker
):
    """initiative_bonus must be copied from the character."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.initiative_bonus == 2


async def test_character_to_wizard_state_loads_ac(fighter_character, mocker):
    """AC must be copied from the character."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.ac == 17


async def test_character_to_wizard_state_loads_hp_override(fighter_character, mocker):
    """max_hp (when not -1) must be stored as hp_override."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.hp_override == 47


async def test_character_to_wizard_state_saves_explicitly_set_is_always_true(
    fighter_character, mocker
):
    """saves_explicitly_set must always be True for an edit wizard state."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.saves_explicitly_set is True


async def test_character_to_wizard_state_loads_saving_throws(
    fighter_character, mocker
):
    """Saving throw proficiencies must be loaded from the character columns."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.saving_throws["strength"] is True
    assert state.saving_throws["constitution"] is True
    # Stats without proficiency should be False
    assert state.saving_throws["dexterity"] is False
    assert state.saving_throws["intelligence"] is False
    assert state.saving_throws["wisdom"] is False
    assert state.saving_throws["charisma"] is False


async def test_character_to_wizard_state_loads_skills(fighter_character, mocker):
    """Proficient skills must appear in state.skills as True."""
    state = _make_edit_state(fighter_character, mocker)
    assert state.skills.get("Athletics") is True


async def test_character_to_wizard_state_loads_existing_attacks(
    fighter_character, mocker
):
    """existing_attacks must contain (id, name) pairs for each of the character's attacks."""
    state = _make_edit_state(fighter_character, mocker)
    assert len(state.existing_attacks) == 1
    attack_id, attack_name = state.existing_attacks[0]
    assert isinstance(attack_id, int)
    assert attack_name == "Longsword"


async def test_character_to_wizard_state_existing_attacks_sorted_by_id(
    db_session, sample_user, sample_server, mocker
):
    """Attacks must be ordered by their database id."""
    char = Character(
        name="Attacker",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(
        Attack(character_id=char.id, name="Dagger", hit_modifier=3, damage_formula="1d4")
    )
    db_session.add(
        Attack(
            character_id=char.id, name="Shortsword", hit_modifier=4, damage_formula="1d6"
        )
    )
    db_session.commit()
    db_session.refresh(char)

    state = _make_edit_state(char, mocker)

    names = [name for _, name in state.existing_attacks]
    assert names == ["Dagger", "Shortsword"]


# ---------------------------------------------------------------------------
# character_to_wizard_state — empty character defaults
# ---------------------------------------------------------------------------


async def test_character_to_wizard_state_empty_character_has_no_classes(
    empty_character, mocker
):
    """A character with no class levels must produce an empty classes_and_levels list."""
    state = _make_edit_state(empty_character, mocker)
    assert state.classes_and_levels == []


async def test_character_to_wizard_state_empty_character_stats_are_none(
    empty_character, mocker
):
    """A character with no stats must leave all ability score fields as None."""
    state = _make_edit_state(empty_character, mocker)
    for stat in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
        assert getattr(state, stat) is None, f"Expected {stat} to be None"


async def test_character_to_wizard_state_empty_character_no_hp_override(
    empty_character, mocker
):
    """A character with max_hp == -1 must not set hp_override."""
    state = _make_edit_state(empty_character, mocker)
    assert state.hp_override is None


async def test_character_to_wizard_state_empty_character_no_existing_attacks(
    empty_character, mocker
):
    """A character with no attacks must produce an empty existing_attacks list."""
    state = _make_edit_state(empty_character, mocker)
    assert state.existing_attacks == []


async def test_character_to_wizard_state_empty_character_no_skills(
    empty_character, mocker
):
    """A character with no skill records must produce an empty skills dict."""
    state = _make_edit_state(empty_character, mocker)
    assert state.skills == {}


# ---------------------------------------------------------------------------
# character_to_wizard_state — sections_completed population
# ---------------------------------------------------------------------------


async def test_sections_completed_includes_class_level_when_class_set(
    fighter_character, mocker
):
    """class_level must be in sections_completed when the character has class levels."""
    state = _make_edit_state(fighter_character, mocker)
    assert "class_level" in state.sections_completed


async def test_sections_completed_excludes_class_level_for_empty_character(
    empty_character, mocker
):
    """class_level must not be in sections_completed when the character has no classes."""
    state = _make_edit_state(empty_character, mocker)
    assert "class_level" not in state.sections_completed


async def test_sections_completed_includes_ability_scores_when_stats_set(
    fighter_character, mocker
):
    """ability_scores must be in sections_completed when at least one stat is set."""
    state = _make_edit_state(fighter_character, mocker)
    assert "ability_scores" in state.sections_completed


async def test_sections_completed_excludes_ability_scores_when_no_stats(
    empty_character, mocker
):
    """ability_scores must not be in sections_completed when all stats are None."""
    state = _make_edit_state(empty_character, mocker)
    assert "ability_scores" not in state.sections_completed


async def test_sections_completed_includes_ac_when_ac_set(fighter_character, mocker):
    """ac must be in sections_completed when the character has an AC value."""
    state = _make_edit_state(fighter_character, mocker)
    assert "ac" in state.sections_completed


async def test_sections_completed_excludes_ac_when_ac_none(empty_character, mocker):
    """ac must not be in sections_completed when AC is None."""
    state = _make_edit_state(empty_character, mocker)
    assert "ac" not in state.sections_completed


async def test_sections_completed_always_includes_saving_throws(
    fighter_character, mocker
):
    """saving_throws is always added because saves_explicitly_set is forced True."""
    state = _make_edit_state(fighter_character, mocker)
    assert "saving_throws" in state.sections_completed


async def test_sections_completed_always_includes_saving_throws_empty_character(
    empty_character, mocker
):
    """saving_throws is in sections_completed even for an empty character."""
    state = _make_edit_state(empty_character, mocker)
    assert "saving_throws" in state.sections_completed


async def test_sections_completed_includes_skills_when_skills_set(
    fighter_character, mocker
):
    """skills must be in sections_completed when the character has proficient skills."""
    state = _make_edit_state(fighter_character, mocker)
    assert "skills" in state.sections_completed


async def test_sections_completed_includes_hp_when_hp_override_set(
    fighter_character, mocker
):
    """hp must be in sections_completed when max_hp is not -1."""
    state = _make_edit_state(fighter_character, mocker)
    assert "hp" in state.sections_completed


async def test_sections_completed_includes_weapons_when_attacks_exist(
    fighter_character, mocker
):
    """weapons must be in sections_completed when the character has existing attacks."""
    state = _make_edit_state(fighter_character, mocker)
    assert "weapons" in state.sections_completed


async def test_sections_completed_excludes_weapons_when_no_attacks(
    empty_character, mocker
):
    """weapons must not be in sections_completed when there are no attacks."""
    state = _make_edit_state(empty_character, mocker)
    assert "weapons" not in state.sections_completed


# ---------------------------------------------------------------------------
# update_character_from_wizard — ability scores, AC, saves, skills
# ---------------------------------------------------------------------------


async def test_update_character_updates_ability_scores(
    db_session, fighter_character, mocker
):
    """update_character_from_wizard must write all six ability scores back to the character."""
    state = _make_edit_state(fighter_character, mocker)
    state.strength = 18
    state.dexterity = 16
    state.constitution = 17
    state.intelligence = 12
    state.wisdom = 14
    state.charisma = 10

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.strength == 18
    assert char.dexterity == 16
    assert char.constitution == 17
    assert char.intelligence == 12
    assert char.wisdom == 14
    assert char.charisma == 10


async def test_update_character_clears_stat_when_set_to_none(
    db_session, fighter_character, mocker
):
    """Setting a stat to None in state must clear that column on the character."""
    state = _make_edit_state(fighter_character, mocker)
    state.intelligence = None

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.intelligence is None


async def test_update_character_updates_ac(db_session, fighter_character, mocker):
    """AC must be written back from wizard state."""
    state = _make_edit_state(fighter_character, mocker)
    state.ac = 19

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.ac == 19


async def test_update_character_updates_saving_throws(
    db_session, fighter_character, mocker
):
    """Saving throw proficiencies must be written from state.saving_throws."""
    state = _make_edit_state(fighter_character, mocker)
    # Flip saves: remove STR, add DEX
    state.saving_throws["strength"] = False
    state.saving_throws["dexterity"] = True

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.st_prof_strength is False
    assert char.st_prof_dexterity is True
    assert char.st_prof_constitution is True  # unchanged


async def test_update_character_replaces_skills(
    db_session, fighter_character, mocker
):
    """Existing skills must be deleted and recreated from the wizard state."""
    state = _make_edit_state(fighter_character, mocker)
    # Remove Athletics, add Perception
    state.skills = {"Perception": True}

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    skill_names = {s.skill_name for s in char.skills}
    assert "Perception" in skill_names
    assert "Athletics" not in skill_names


async def test_update_character_clears_skills_when_empty(
    db_session, fighter_character, mocker
):
    """Passing an empty skills dict must remove all existing skill records."""
    state = _make_edit_state(fighter_character, mocker)
    state.skills = {}

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    assert char.skills == []


# ---------------------------------------------------------------------------
# update_character_from_wizard — class level replacement
# ---------------------------------------------------------------------------


async def test_update_character_replaces_class_levels(
    db_session, fighter_character, mocker
):
    """Old ClassLevel rows must be deleted and new ones created from state."""
    state = _make_edit_state(fighter_character, mocker)
    state.classes_and_levels = [(CharacterClass.PALADIN, 3)]

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    assert len(char.class_levels) == 1
    assert char.class_levels[0].class_name == "Paladin"
    assert char.class_levels[0].level == 3


async def test_update_character_multiclass_replacement(
    db_session, fighter_character, mocker
):
    """Multiple classes must all be created when classes_and_levels has more than one entry."""
    state = _make_edit_state(fighter_character, mocker)
    state.classes_and_levels = [
        (CharacterClass.ROGUE, 4),
        (CharacterClass.RANGER, 1),
    ]

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    assert len(char.class_levels) == 2
    class_names = {cl.class_name for cl in char.class_levels}
    assert class_names == {"Rogue", "Ranger"}


async def test_update_character_no_class_levels_clears_all(
    db_session, fighter_character, mocker
):
    """Passing an empty classes_and_levels must remove all existing ClassLevel rows."""
    state = _make_edit_state(fighter_character, mocker)
    state.classes_and_levels = []

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    assert char.class_levels == []


# ---------------------------------------------------------------------------
# update_character_from_wizard — weapons_to_remove
# ---------------------------------------------------------------------------


async def test_update_character_removes_queued_attacks(
    db_session, fighter_character, mocker
):
    """Attacks in weapons_to_remove must be deleted from the character."""
    existing_attack = fighter_character.attacks[0]
    state = _make_edit_state(fighter_character, mocker)
    state.weapons_to_remove = [existing_attack.id]

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    remaining_names = [a.name for a in char.attacks]
    assert "Longsword" not in remaining_names


async def test_update_character_does_not_remove_attack_from_another_character(
    db_session, sample_user, sample_server, fighter_character, mocker
):
    """weapons_to_remove must not delete attacks that belong to a different character."""
    other_char = Character(
        name="OtherHero",
        user=sample_user,
        server=sample_server,
        is_active=False,
    )
    db_session.add(other_char)
    db_session.flush()
    other_attack = Attack(
        character_id=other_char.id,
        name="Battleaxe",
        hit_modifier=4,
        damage_formula="1d8+2",
    )
    db_session.add(other_attack)
    db_session.commit()
    db_session.refresh(other_char)

    state = _make_edit_state(fighter_character, mocker)
    # Attempt to remove an attack belonging to other_char
    state.weapons_to_remove = [other_attack.id]

    update_character_from_wizard(state, db_session)

    # The other character's attack must still exist
    still_there = db_session.get(Attack, other_attack.id)
    assert still_there is not None


async def test_update_character_ignores_nonexistent_attack_id_in_weapons_to_remove(
    db_session, fighter_character, mocker
):
    """A non-existent attack id in weapons_to_remove must not raise an error."""
    state = _make_edit_state(fighter_character, mocker)
    state.weapons_to_remove = [999999]  # id that does not exist

    char, error = update_character_from_wizard(state, db_session)

    assert error is None


# ---------------------------------------------------------------------------
# update_character_from_wizard — weapons_to_add
# ---------------------------------------------------------------------------


async def test_update_character_adds_new_weapons(
    db_session, fighter_character, mocker, mocker_patch_weapon_utils
):
    """New weapons in weapons_to_add must be created as Attack records."""
    state = _make_edit_state(fighter_character, mocker)
    state.weapons_to_add = [{"name": "Dagger", "damage_dice": "1d4", "properties": []}]

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    attack_names = [a.name for a in char.attacks]
    assert "Dagger" in attack_names


async def test_update_character_respects_max_attacks_limit(
    db_session, sample_user, sample_server, mocker, mocker_patch_weapon_utils
):
    """weapons_to_add must not exceed MAX_ATTACKS_PER_CHARACTER total attacks."""
    char = Character(
        name="WeaponHoarder",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(char)
    db_session.flush()
    # Fill up to the limit
    for index in range(MAX_ATTACKS_PER_CHARACTER):
        db_session.add(
            Attack(
                character_id=char.id,
                name=f"Sword{index}",
                hit_modifier=0,
                damage_formula="1d6",
            )
        )
    db_session.commit()
    db_session.refresh(char)

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=char.name,
        edit_character_id=char.id,
    )
    state.weapons_to_add = [{"name": "Extra Sword", "damage_dice": "1d8", "properties": []}]

    char, error = update_character_from_wizard(state, db_session)

    db_session.refresh(char)
    # Total must not exceed the cap
    assert len(char.attacks) <= MAX_ATTACKS_PER_CHARACTER


# ---------------------------------------------------------------------------
# update_character_from_wizard — hp_override
# ---------------------------------------------------------------------------


async def test_update_character_applies_hp_override(
    db_session, fighter_character, mocker
):
    """When hp_override is set, max_hp and current_hp must be updated to that value."""
    state = _make_edit_state(fighter_character, mocker)
    state.hp_override = 99

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.max_hp == 99
    assert char.current_hp == 99


async def test_update_character_auto_calculates_hp_when_override_is_none(
    db_session, mocker, sample_user, sample_server
):
    """When hp_override is None and auto-calc is possible, max_hp must be recalculated."""
    char = Character(
        name="AutoHP",
        user=sample_user,
        server=sample_server,
        is_active=True,
        constitution=14,  # +2 modifier
        max_hp=1,
        current_hp=1,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
    db_session.commit()
    db_session.refresh(char)

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=char.name,
        edit_character_id=char.id,
        classes_and_levels=[(CharacterClass.FIGHTER, 1)],
        constitution=14,
    )
    state.hp_override = None  # force auto-calculation

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    # Fighter level 1 with CON +2 = 10 + 2 = 12
    assert char.max_hp == 12


async def test_update_character_hp_set_to_minus_one_when_no_auto_calc_possible(
    db_session, mocker, sample_user, sample_server
):
    """When hp_override is None and auto-calc returns -1, max_hp must be set to -1."""
    char = Character(
        name="NoHP",
        user=sample_user,
        server=sample_server,
        is_active=True,
        max_hp=50,
        current_hp=50,
    )
    db_session.add(char)
    db_session.commit()
    db_session.refresh(char)

    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name=char.name,
        edit_character_id=char.id,
        classes_and_levels=[],  # no class = no auto-calc
    )
    state.hp_override = None

    char, error = update_character_from_wizard(state, db_session)

    assert error is None
    assert char.max_hp == -1
    assert char.current_hp == -1


# ---------------------------------------------------------------------------
# update_character_from_wizard — character not found
# ---------------------------------------------------------------------------


async def test_update_character_returns_error_when_character_not_found(
    db_session, mocker
):
    """update_character_from_wizard must return (None, error) when the character id is missing."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="Ghost",
        edit_character_id=999999,
    )

    char, error = update_character_from_wizard(state, db_session)

    assert char is None
    assert error == Strings.ACTIVE_CHARACTER_NOT_FOUND


async def test_update_character_returns_none_character_when_not_found(
    db_session, mocker
):
    """The first element of the return tuple must be None when the character is missing."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
        name="Phantom",
        edit_character_id=0,
    )

    result_char, _ = update_character_from_wizard(state, db_session)

    assert result_char is None


# ---------------------------------------------------------------------------
# _WeaponRemoveButton.callback
# ---------------------------------------------------------------------------


async def test_weapon_remove_button_removes_from_existing_attacks(mocker):
    """Clicking _WeaponRemoveButton must remove the attack from state.existing_attacks."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(10, "Longsword"), (11, "Dagger")]

    weapons_view = mocker.AsyncMock()
    weapons_view._refresh = mocker.AsyncMock()

    button = _WeaponRemoveButton(
        attack_id=10,
        attack_name="Longsword",
        state=state,
        weapons_view=weapons_view,
        row=1,
    )
    interaction = mocker.AsyncMock(spec=discord.Interaction)

    await button.callback(interaction)

    remaining_ids = [aid for aid, _ in state.existing_attacks]
    assert 10 not in remaining_ids
    assert 11 in remaining_ids


async def test_weapon_remove_button_adds_id_to_weapons_to_remove(mocker):
    """Clicking _WeaponRemoveButton must append the attack id to state.weapons_to_remove."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(10, "Longsword")]

    weapons_view = mocker.AsyncMock()
    weapons_view._refresh = mocker.AsyncMock()

    button = _WeaponRemoveButton(
        attack_id=10,
        attack_name="Longsword",
        state=state,
        weapons_view=weapons_view,
        row=1,
    )
    interaction = mocker.AsyncMock(spec=discord.Interaction)

    await button.callback(interaction)

    assert 10 in state.weapons_to_remove


async def test_weapon_remove_button_calls_weapons_view_refresh(mocker):
    """Clicking _WeaponRemoveButton must call weapons_view._refresh with the interaction."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(20, "Handaxe")]

    weapons_view = mocker.AsyncMock()
    weapons_view._refresh = mocker.AsyncMock()

    button = _WeaponRemoveButton(
        attack_id=20,
        attack_name="Handaxe",
        state=state,
        weapons_view=weapons_view,
        row=1,
    )
    interaction = mocker.AsyncMock(spec=discord.Interaction)

    await button.callback(interaction)

    weapons_view._refresh.assert_called_once_with(interaction)


async def test_weapon_remove_button_does_not_duplicate_in_weapons_to_remove(mocker):
    """Clicking remove twice must not add the same id to weapons_to_remove twice."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(10, "Longsword")]
    state.weapons_to_remove = [10]  # already queued for removal

    weapons_view = mocker.AsyncMock()
    weapons_view._refresh = mocker.AsyncMock()

    button = _WeaponRemoveButton(
        attack_id=10,
        attack_name="Longsword",
        state=state,
        weapons_view=weapons_view,
        row=1,
    )
    interaction = mocker.AsyncMock(spec=discord.Interaction)

    await button.callback(interaction)

    assert state.weapons_to_remove.count(10) == 1


# ---------------------------------------------------------------------------
# _WeaponSelectButton.callback — blocked by already_existing check
# ---------------------------------------------------------------------------


async def test_weapon_select_blocked_when_attack_already_in_existing_attacks(mocker):
    """Selecting a weapon that is in existing_attacks must send the already-queued message."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(5, "Longsword")]

    weapon_data = {"name": "Longsword"}
    weapons_view = mocker.MagicMock()

    button = _WeaponSelectButton(state=state, weapon_data=weapon_data, weapons_view=weapons_view)
    interaction = mocker.AsyncMock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await button.callback(interaction)

    interaction.response.send_message.assert_called_once()
    call_args = interaction.response.send_message.call_args
    message_text = call_args[0][0] if call_args[0] else call_args.kwargs.get("content", "")
    assert "Longsword" in message_text


async def test_weapon_select_blocked_does_not_add_to_weapons_to_add(mocker):
    """When blocked by already_existing, nothing must be added to weapons_to_add."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(5, "Shortsword")]

    weapon_data = {"name": "Shortsword"}
    weapons_view = mocker.MagicMock()

    button = _WeaponSelectButton(state=state, weapon_data=weapon_data, weapons_view=weapons_view)
    interaction = mocker.AsyncMock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await button.callback(interaction)

    assert state.weapons_to_add == []


async def test_weapon_select_allowed_when_name_not_in_existing_or_queued(mocker):
    """Selecting a weapon not already on the character or queued must add it to weapons_to_add."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
        edit_character_id=1,
    )
    state.existing_attacks = [(5, "Longsword")]

    weapon_data = {"name": "Dagger"}
    weapons_view = mocker.MagicMock()
    weapons_view._build_embed.return_value = discord.Embed()

    button = _WeaponSelectButton(state=state, weapon_data=weapon_data, weapons_view=weapons_view)
    interaction = mocker.AsyncMock(spec=discord.Interaction)
    interaction.response = mocker.AsyncMock()

    await button.callback(interaction)

    assert any(w.get("name") == "Dagger" for w in state.weapons_to_add)


# ---------------------------------------------------------------------------
# _build_hub_embed — edit mode title / description
# ---------------------------------------------------------------------------


async def test_build_hub_embed_creation_mode_uses_creation_title(mocker):
    """Hub embed in creation mode must use WIZARD_HUB_TITLE."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="NewHero",
    )

    embed = _build_hub_embed(state)

    assert embed.title == Strings.WIZARD_HUB_TITLE


async def test_build_hub_embed_edit_mode_uses_edit_title(mocker):
    """Hub embed in edit mode must use WIZARD_EDIT_HUB_TITLE."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="ExistingHero",
        edit_character_id=42,
    )

    embed = _build_hub_embed(state)

    assert embed.title == Strings.WIZARD_EDIT_HUB_TITLE


async def test_build_hub_embed_edit_mode_uses_edit_description(mocker):
    """Hub embed in edit mode must use WIZARD_EDIT_HUB_DESC."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="ExistingHero",
        edit_character_id=42,
    )

    embed = _build_hub_embed(state)

    assert embed.description == Strings.WIZARD_EDIT_HUB_DESC


async def test_build_hub_embed_creation_mode_title_differs_from_edit_mode(mocker):
    """Hub embed titles must differ between creation and edit modes."""
    creation_state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="NewHero",
    )
    edit_state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="ExistingHero",
        edit_character_id=1,
    )

    creation_embed = _build_hub_embed(creation_state)
    edit_embed = _build_hub_embed(edit_state)

    assert creation_embed.title != edit_embed.title


# ---------------------------------------------------------------------------
# _finish_wizard — routes to update_character_from_wizard in edit mode
# ---------------------------------------------------------------------------


async def test_finish_wizard_calls_update_when_edit_character_id_set(
    mocker, session_factory, fighter_character
):
    """When edit_character_id is set, _finish_wizard must call update_character_from_wizard."""
    import commands.wizard.completion as completion_module

    original_session_local = completion_module.SessionLocal
    completion_module.SessionLocal = session_factory
    try:
        mock_update = mocker.patch(
            "commands.wizard.completion.update_character_from_wizard",
            return_value=(fighter_character, None),
        )
        mocker.patch(
            "commands.wizard.completion._build_edit_complete_embed",
            return_value=discord.Embed(),
        )

        state = WizardState(
            user_discord_id="111",
            guild_discord_id="222",
            guild_name="Test Server",
            name="Aldric",
            edit_character_id=fighter_character.id,
        )
        interaction = make_interaction(mocker)

        from commands.wizard.completion import _finish_wizard

        await _finish_wizard(state, interaction)

        mock_update.assert_called_once()
    finally:
        completion_module.SessionLocal = original_session_local


async def test_finish_wizard_does_not_call_update_in_creation_mode(
    mocker, session_factory, sample_user, sample_server
):
    """When edit_character_id is None, _finish_wizard must NOT call update_character_from_wizard."""
    import commands.wizard.completion as completion_module

    original_session_local = completion_module.SessionLocal
    completion_module.SessionLocal = session_factory
    try:
        mock_update = mocker.patch(
            "commands.wizard.completion.update_character_from_wizard",
        )

        # Patch save_character_from_wizard to avoid needing a real user/server pair
        fake_char = mocker.MagicMock(spec=Character)
        fake_char.name = "BrandNew"
        fake_char.max_hp = 10
        mocker.patch(
            "commands.wizard.completion.save_character_from_wizard",
            return_value=(fake_char, None),
        )
        mocker.patch(
            "commands.wizard.completion._build_complete_embed",
            return_value=discord.Embed(),
        )

        state = WizardState(
            user_discord_id="111",
            guild_discord_id="222",
            guild_name="Test Server",
            name="BrandNew",
            edit_character_id=None,  # creation mode
        )
        interaction = make_interaction(mocker)

        from commands.wizard.completion import _finish_wizard

        await _finish_wizard(state, interaction)

        mock_update.assert_not_called()
    finally:
        completion_module.SessionLocal = original_session_local


async def test_finish_wizard_edit_mode_sends_followup_on_success(
    mocker, session_factory, fighter_character
):
    """A successful edit must send a public followup embed via interaction.followup.send."""
    import commands.wizard.completion as completion_module

    original_session_local = completion_module.SessionLocal
    completion_module.SessionLocal = session_factory
    try:
        mocker.patch(
            "commands.wizard.completion.update_character_from_wizard",
            return_value=(fighter_character, None),
        )
        mocker.patch(
            "commands.wizard.completion._build_edit_complete_embed",
            return_value=discord.Embed(),
        )

        state = WizardState(
            user_discord_id="111",
            guild_discord_id="222",
            guild_name="Test Server",
            name="Aldric",
            edit_character_id=fighter_character.id,
        )
        interaction = make_interaction(mocker)

        from commands.wizard.completion import _finish_wizard

        await _finish_wizard(state, interaction)

        interaction.followup.send.assert_called_once()
        call_kwargs = interaction.followup.send.call_args.kwargs
        assert isinstance(call_kwargs.get("embed"), discord.Embed)
    finally:
        completion_module.SessionLocal = original_session_local


async def test_finish_wizard_edit_mode_sends_error_on_failure(
    mocker, session_factory
):
    """When update_character_from_wizard returns an error, _finish_wizard must send that error."""
    import commands.wizard.completion as completion_module

    original_session_local = completion_module.SessionLocal
    completion_module.SessionLocal = session_factory
    try:
        mocker.patch(
            "commands.wizard.completion.update_character_from_wizard",
            return_value=(None, Strings.ACTIVE_CHARACTER_NOT_FOUND),
        )

        state = WizardState(
            user_discord_id="111",
            guild_discord_id="222",
            guild_name="Test Server",
            name="Ghost",
            edit_character_id=999999,
        )
        interaction = make_interaction(mocker)

        from commands.wizard.completion import _finish_wizard

        await _finish_wizard(state, interaction)

        interaction.response.send_message.assert_called_once_with(
            Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
        )
    finally:
        completion_module.SessionLocal = original_session_local


# ---------------------------------------------------------------------------
# Fixture for weapon utils patching (avoids real HTTP calls)
# ---------------------------------------------------------------------------


@pytest.fixture
def mocker_patch_weapon_utils(mocker):
    """Patch weapon calculation utilities so tests don't need real weapon data."""
    from unittest.mock import MagicMock  # only for spec/type, not for test logic

    parsed_fields = mocker.Mock()
    parsed_fields.name = "Dagger"  # must be a plain str for SQLAlchemy bindings
    parsed_fields.properties = []
    parsed_fields.range_normal_float = 5.0
    parsed_fields.damage_dice = "1d4"
    parsed_fields.damage_type_name = "Piercing"
    parsed_fields.weapon_category = "Simple"
    parsed_fields.two_handed_damage = None
    parsed_fields.properties_json = "[]"

    mocker.patch(
        "commands.wizard.state.parse_weapon_fields",
        return_value=parsed_fields,
    )

    hit_result = mocker.Mock()
    hit_result.total = 2
    mocker.patch(
        "commands.wizard.state.calculate_weapon_hit_modifier",
        return_value=hit_result,
    )
