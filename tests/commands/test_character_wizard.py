"""Tests for the character creation wizard (hub model).

Covers:
* ``save_character_from_wizard`` — DB validation and creation logic
* ``WizardState`` properties — character_class, level, total_level
* ``snapshot_section`` / ``restore_section`` — snapshot helpers
* Modal ``on_submit`` handlers — field validation and state transitions
* Section views — embed building, button behaviour, save/return/cancel
* ``HubView`` — button colours, enabled states
* ``/character create`` entry point — sends the wizard hub
* ``/character saves`` — button-based toggle view
"""

import pytest
import discord
from models import Attack, Character, CharacterSkill, ClassLevel
from enums.character_class import CharacterClass
from enums.skill_proficiency_status import SkillProficiencyStatus
from commands.wizard import start_character_creation
from commands.wizard.state import (
    WizardState,
    save_character_from_wizard,
    snapshot_section,
    restore_section,
)
from commands.wizard.modals import (
    _CharacterNameModal,
    _LevelForClassModal,
    _PhysicalStatsModal,
    _MentalStatsModal,
    _InitiativeModal,
    _ACModal,
    _HPModal,
)
from commands.wizard.buttons import (
    _SaveToggleButton,
    _SkillToggleButton,
    _ClassRemoveButton,
    _SaveReturnButton,
    _ReturnNoSaveButton,
    _CancelWizardButton,
    _WeaponSelectButton,
    _BackToWeaponsButton,
)
from commands.wizard.section_views import (
    _ClassLevelView,
    _StatsView,
    _ACView,
    _SavesView,
    _SkillsView,
    _HPView,
    _WeaponsWizardView,
    _WeaponResultsView,
)
from commands.wizard.hub_view import HubView
from utils.strings import Strings
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    mocker,
    name: str = "Thalindra",
    user_id: int = 111,
    guild_id: int = 222,
) -> tuple[WizardState, discord.Interaction]:
    """Return a minimal WizardState and matching mock interaction."""
    state = WizardState(
        user_discord_id=str(user_id),
        guild_discord_id=str(guild_id),
        guild_name="Test Server",
        name=name,
    )
    interaction = make_interaction(mocker, user_id=user_id, guild_id=guild_id)
    return state, interaction


def _set_text_input(text_input: discord.ui.TextInput, value: str) -> None:
    """Inject a value into a TextInput as Discord would on modal submission."""
    text_input._value = value


# ---------------------------------------------------------------------------
# save_character_from_wizard — core DB logic
# ---------------------------------------------------------------------------


async def test_save_wizard_creates_character(mocker, db_session, sample_user, sample_server):
    """A minimal state (name only) creates an active Character row."""
    state, interaction = _make_state(mocker)
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char is not None
    assert char.name == "Thalindra"
    assert char.is_active is True


async def test_save_wizard_deactivates_previous_character(
    mocker, db_session, sample_user, sample_server, sample_character
):
    """Creating a character deactivates any previously active character."""
    assert sample_character.is_active is True
    state, interaction = _make_state(mocker, name="Newbie")
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    db_session.refresh(sample_character)
    assert sample_character.is_active is False
    assert char.is_active is True


async def test_save_wizard_name_too_long(mocker, db_session):
    """A name longer than 100 characters returns a validation error."""
    state, interaction = _make_state(mocker, name="A" * 101)
    char, error = save_character_from_wizard(state, interaction, db_session)

    assert char is None
    assert error == Strings.CHAR_CREATE_NAME_LIMIT


async def test_save_wizard_duplicate_name(
    mocker, db_session, sample_user, sample_server, sample_character
):
    """A duplicate name returns CHAR_EXISTS error."""
    state, interaction = _make_state(mocker, name="Aldric")  # matches sample_character
    char, error = save_character_from_wizard(state, interaction, db_session)

    assert char is None
    assert "Aldric" in error


async def test_save_wizard_character_limit_exceeded(
    mocker, db_session, sample_user, sample_server, session_factory
):
    """Exceeding MAX_CHARACTERS_PER_USER returns a limit error."""
    from utils.limits import MAX_CHARACTERS_PER_USER

    # Fill up to limit
    for i in range(MAX_CHARACTERS_PER_USER):
        char = Character(
            name=f"Char{i}", user=sample_user, server=sample_server, is_active=False
        )
        db_session.add(char)
    db_session.commit()

    state, interaction = _make_state(mocker, name="OneMore")
    char, error = save_character_from_wizard(state, interaction, db_session)

    assert char is None
    assert error is not None


async def test_save_wizard_with_single_class_creates_class_level(
    mocker, db_session, sample_user, sample_server
):
    """Setting classes_and_levels with one entry creates the ClassLevel row."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 3)]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    class_levels = db_session.query(ClassLevel).filter_by(character_id=char.id).all()
    assert len(class_levels) == 1
    assert class_levels[0].class_name == "Fighter"
    assert class_levels[0].level == 3


async def test_save_wizard_with_multiple_classes_creates_multiple_class_levels(
    mocker, db_session, sample_user, sample_server
):
    """Multiclass: two classes each create their own ClassLevel row with correct levels."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.WIZARD, 3)]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    class_levels = db_session.query(ClassLevel).filter_by(character_id=char.id).all()
    assert len(class_levels) == 2
    level_map = {cl.class_name: cl.level for cl in class_levels}
    assert level_map["Fighter"] == 5
    assert level_map["Wizard"] == 3


async def test_save_wizard_multiclass_total_level_sums_correctly(
    mocker, db_session, sample_user, sample_server
):
    """Total level across multiclass entries sums correctly."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.PALADIN, 6), (CharacterClass.WARLOCK, 4)]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    class_levels = db_session.query(ClassLevel).filter_by(character_id=char.id).all()
    total = sum(cl.level for cl in class_levels)
    assert total == 10


async def test_save_wizard_first_class_gets_save_profs(
    mocker, db_session, sample_user, sample_server
):
    """A Fighter (first class) gets STR and CON save proficiencies automatically."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.st_prof_strength is True
    assert char.st_prof_constitution is True
    assert char.st_prof_dexterity is False


async def test_save_wizard_second_class_does_not_change_save_profs(
    mocker, db_session, sample_user, sample_server
):
    """Adding a second class (Wizard) does not grant its saves; only the first class's saves apply."""
    state, interaction = _make_state(mocker)
    # Fighter (STR, CON saves) + Wizard (INT, WIS saves)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.WIZARD, 3)]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    # Only Fighter's saves should be applied (first class)
    assert char.st_prof_strength is True
    assert char.st_prof_constitution is True
    # Wizard's saves should NOT be auto-applied
    assert char.st_prof_intelligence is False
    assert char.st_prof_wisdom is False


async def test_save_wizard_hp_override_used_when_set(
    mocker, db_session, sample_user, sample_server
):
    """hp_override is used as max_hp when set."""
    state, interaction = _make_state(mocker)
    state.hp_override = 42
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.max_hp == 42
    assert char.current_hp == 42


async def test_save_wizard_hp_override_takes_precedence_over_auto_calc(
    mocker, db_session, sample_user, sample_server
):
    """hp_override takes precedence over auto-calculated HP."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.constitution = 16  # CON mod +3; Fighter d10 → auto would be 13
    state.hp_override = 99
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.max_hp == 99  # override wins, not 13


async def test_save_wizard_hp_auto_calculated_with_class_and_con(
    mocker, db_session, sample_user, sample_server
):
    """max_hp is auto-calculated when both class and Constitution are set (no override)."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.constitution = 16  # CON mod +3; Fighter d10 → 10+3=13
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.max_hp == 13
    assert char.current_hp == 13


async def test_save_wizard_hp_not_calculated_without_class(
    mocker, db_session, sample_user, sample_server
):
    """max_hp stays at -1 when no class is set (cannot calculate without hit die)."""
    state, interaction = _make_state(mocker)
    state.constitution = 14
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.max_hp == -1


async def test_save_wizard_weapons_created_as_attacks(
    mocker, db_session, sample_user, sample_server
):
    """Weapons in weapons_to_add are created as Attack records when saving."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.strength = 16
    state.weapons_to_add = [
        {
            "name": "Longsword",
            "damage_dice": "1d8",
            "damage_type": {"name": "slashing"},
            "is_simple": False,
            "range": 5,
            "properties": [],
        }
    ]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    attacks = db_session.query(Attack).filter_by(character_id=char.id).all()
    assert len(attacks) == 1
    assert attacks[0].name == "Longsword"


async def test_save_wizard_weapons_stops_at_max_attacks(
    mocker, db_session, sample_user, sample_server
):
    """weapons_to_add loop respects MAX_ATTACKS_PER_CHARACTER cap.

    Note: save_character_from_wizard checks the committed attack count before
    each weapon addition.  For a brand-new character the check acts as an upper
    bound: at most MAX_ATTACKS_PER_CHARACTER weapons are added when
    weapons_to_add contains more entries than that limit.
    """
    from utils.limits import MAX_ATTACKS_PER_CHARACTER

    exact_count = MAX_ATTACKS_PER_CHARACTER
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.strength = 16
    # Queue exactly at the limit — all should be created
    state.weapons_to_add = [
        {
            "name": f"Weapon{i}",
            "damage_dice": "1d6",
            "damage_type": {"name": "slashing"},
            "is_simple": True,
            "range": 5,
            "properties": [],
        }
        for i in range(exact_count)
    ]
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    attacks = db_session.query(Attack).filter_by(character_id=char.id).all()
    assert len(attacks) == exact_count


async def test_save_wizard_with_ability_scores(
    mocker, db_session, sample_user, sample_server
):
    """All six ability scores are persisted."""
    state, interaction = _make_state(mocker)
    state.strength = 16
    state.dexterity = 14
    state.constitution = 15
    state.intelligence = 10
    state.wisdom = 12
    state.charisma = 8
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.strength == 16
    assert char.dexterity == 14
    assert char.constitution == 15
    assert char.intelligence == 10
    assert char.wisdom == 12
    assert char.charisma == 8


async def test_save_wizard_with_initiative_bonus(
    mocker, db_session, sample_user, sample_server
):
    """initiative_bonus is stored when provided."""
    state, interaction = _make_state(mocker)
    state.initiative_bonus = 3
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.initiative_bonus == 3


async def test_save_wizard_with_ac(mocker, db_session, sample_user, sample_server):
    """AC is persisted."""
    state, interaction = _make_state(mocker)
    state.ac = 17
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.ac == 17


async def test_save_wizard_explicit_saves_override_class_defaults(
    mocker, db_session, sample_user, sample_server
):
    """When saves_explicitly_set is True, state.saving_throws overrides class defaults."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]  # normally STR + CON
    # User explicitly set only DEX prof
    state.saving_throws = {
        "strength": False,
        "dexterity": True,
        "constitution": False,
        "intelligence": False,
        "wisdom": False,
        "charisma": False,
    }
    state.saves_explicitly_set = True
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert char.st_prof_dexterity is True
    assert char.st_prof_strength is False
    assert char.st_prof_constitution is False


async def test_save_wizard_class_saves_not_overridden_when_not_explicit(
    mocker, db_session, sample_user, sample_server
):
    """When saves_explicitly_set is False, class defaults are used and not overridden."""
    state, interaction = _make_state(mocker)
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.saves_explicitly_set = False  # not overriding
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    # Fighter class profs: STR, CON
    assert char.st_prof_strength is True
    assert char.st_prof_constitution is True


async def test_save_wizard_with_proficient_skills(
    mocker, db_session, sample_user, sample_server
):
    """Toggled-on skills create CharacterSkill rows with PROFICIENT status."""
    state, interaction = _make_state(mocker)
    state.skills = {"Acrobatics": True, "Stealth": True, "History": False}
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    skill_rows = (
        db_session.query(CharacterSkill).filter_by(character_id=char.id).all()
    )
    skill_names = {s.skill_name for s in skill_rows}
    assert "Acrobatics" in skill_names
    assert "Stealth" in skill_names
    assert "History" not in skill_names  # False → not stored


async def test_save_wizard_auto_creates_user_and_server(
    mocker, db_session
):
    """save_character_from_wizard bootstraps User and Server rows when absent."""
    from models import User, Server

    assert db_session.query(User).count() == 0
    assert db_session.query(Server).count() == 0

    state, interaction = _make_state(mocker, user_id=999, guild_id=888)
    char, error = save_character_from_wizard(state, interaction, db_session)
    db_session.commit()

    assert error is None
    assert db_session.query(User).filter_by(discord_id="999").count() == 1
    assert db_session.query(Server).filter_by(discord_id="888").count() == 1


# ---------------------------------------------------------------------------
# WizardState property tests
# ---------------------------------------------------------------------------


def test_wizard_state_character_class_returns_first_class():
    """character_class property returns the first class in classes_and_levels."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.WIZARD, 3)]
    assert state.character_class == CharacterClass.FIGHTER


def test_wizard_state_character_class_returns_none_when_empty():
    """character_class property returns None when no classes set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.character_class is None


def test_wizard_state_level_returns_first_class_level():
    """level property returns the level of the first class."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.ROGUE, 7), (CharacterClass.FIGHTER, 3)]
    assert state.level == 7


def test_wizard_state_level_returns_none_when_empty():
    """level property returns None when no classes set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.level is None


def test_wizard_state_total_level_sums_all_class_levels():
    """total_level sums all class levels."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [
        (CharacterClass.FIGHTER, 5),
        (CharacterClass.WIZARD, 3),
        (CharacterClass.ROGUE, 2),
    ]
    assert state.total_level == 10


def test_wizard_state_total_level_zero_when_empty():
    """total_level is 0 when classes_and_levels is empty."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.total_level == 0


def test_wizard_state_sections_completed_starts_empty():
    """sections_completed is an empty set by default."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.sections_completed == set()


# ---------------------------------------------------------------------------
# snapshot_section / restore_section
# ---------------------------------------------------------------------------


def test_snapshot_section_captures_fields():
    """snapshot_section returns a dict with deep-copied field values."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.ac = 15
    snapshot = snapshot_section(state, "ac")

    assert snapshot["ac"] == 15
    # Mutation after snapshot must not affect the snapshot
    state.ac = 20
    assert snapshot["ac"] == 15


def test_snapshot_section_deep_copies_mutable_fields():
    """snapshot_section deep-copies list fields so mutations don't affect the snapshot."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5)]
    snapshot = snapshot_section(state, "class_level")

    # Mutate the list after snapshotting
    state.classes_and_levels.append((CharacterClass.ROGUE, 3))
    assert len(snapshot["classes_and_levels"]) == 1  # snapshot unchanged


def test_restore_section_restores_fields():
    """restore_section writes snapshot values back to state fields."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.ac = 15
    snapshot = snapshot_section(state, "ac")

    # Simulate a change in the section
    state.ac = 20
    restore_section(state, "ac", snapshot)

    assert state.ac == 15


def test_restore_section_restores_list_fields():
    """restore_section restores list fields, discarding in-section mutations."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5)]
    snapshot = snapshot_section(state, "class_level")

    state.classes_and_levels.append((CharacterClass.ROGUE, 3))
    restore_section(state, "class_level", snapshot)

    assert len(state.classes_and_levels) == 1
    assert state.classes_and_levels[0][0] == CharacterClass.FIGHTER


# ---------------------------------------------------------------------------
# _LevelForClassModal — on_submit
# ---------------------------------------------------------------------------


async def test_level_for_class_modal_new_class_added(mocker):
    """A valid level for a new class appends it to classes_and_levels."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "5"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert len(state.classes_and_levels) == 1
    assert state.classes_and_levels[0] == (CharacterClass.FIGHTER, 5)
    interaction.response.edit_message.assert_called_once()


async def test_level_for_class_modal_existing_class_updated(mocker):
    """When existing_index is not None, the class level is updated in place."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 3)]
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, 0, parent_view)
    modal.level_input._value = "10"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.classes_and_levels[0] == (CharacterClass.FIGHTER, 10)
    interaction.response.edit_message.assert_called_once()


async def test_level_for_class_modal_invalid_non_numeric_sends_error(mocker):
    """A non-numeric level sends an ephemeral error."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "abc"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert len(state.classes_and_levels) == 0


async def test_level_for_class_modal_level_zero_rejected(mocker):
    """Level 0 is below the minimum and must be rejected."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "0"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert len(state.classes_and_levels) == 0


async def test_level_for_class_modal_level_21_rejected(mocker):
    """Level 21 exceeds the maximum and must be rejected."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "21"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert len(state.classes_and_levels) == 0


async def test_level_for_class_modal_total_level_would_exceed_20(mocker):
    """Adding a level that pushes total above 20 must be rejected."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 15)]
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.WIZARD, None, parent_view)
    modal.level_input._value = "10"  # 15 + 10 = 25 > 20

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert len(state.classes_and_levels) == 1  # unchanged


async def test_level_for_class_modal_first_class_autofills_saving_throws(mocker):
    """First class addition auto-fills saving_throws when saves_explicitly_set=False."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    assert state.saves_explicitly_set is False
    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, None, parent_view)
    modal.level_input._value = "1"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # Fighter gets STR + CON
    assert state.saving_throws["strength"] is True
    assert state.saving_throws["constitution"] is True
    assert state.saving_throws["dexterity"] is False


async def test_level_for_class_modal_second_class_does_not_change_saving_throws(mocker):
    """Adding a second class does NOT change saving_throws."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5)]
    # Fighter has STR + CON saves already
    state.saving_throws = {s: s in ("strength", "constitution") for s in
                           ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}

    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.WIZARD, None, parent_view)
    modal.level_input._value = "3"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # Saving throws should still be Fighter's (STR + CON), not Wizard's (INT + WIS)
    assert state.saving_throws["strength"] is True
    assert state.saving_throws["constitution"] is True
    assert state.saving_throws["intelligence"] is False
    assert state.saving_throws["wisdom"] is False


async def test_level_for_class_modal_re_editing_first_class_does_not_reapply_saves(mocker):
    """Re-editing first class level does NOT re-apply save profs when saves_explicitly_set."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 3)]
    state.saves_explicitly_set = True  # user manually set saves
    state.saving_throws = {s: s == "dexterity" for s in
                           ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}

    parent_view = _ClassLevelView(state)
    modal = _LevelForClassModal(state, CharacterClass.FIGHTER, 0, parent_view)
    modal.level_input._value = "7"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # saves_explicitly_set remains True, saves unchanged
    assert state.saves_explicitly_set is True
    assert state.saving_throws["dexterity"] is True
    assert state.saving_throws["strength"] is False


# ---------------------------------------------------------------------------
# _ClassRemoveButton — callback
# ---------------------------------------------------------------------------


async def test_class_remove_button_removes_class(mocker):
    """Clicking _ClassRemoveButton removes the class from classes_and_levels."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.ROGUE, 3)]
    parent_view = _ClassLevelView(state)
    button = _ClassRemoveButton(state, CharacterClass.ROGUE, parent_view, row=1)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    assert len(state.classes_and_levels) == 1
    assert state.classes_and_levels[0][0] == CharacterClass.FIGHTER


async def test_class_remove_button_first_class_updates_saves_when_not_explicit(mocker):
    """When first class is removed and saves not explicitly set, saving_throws updated to new first class."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.CLERIC, 3)]
    # Fighter saves auto-applied
    state.saving_throws = {s: s in ("strength", "constitution") for s in
                           ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}
    state.saves_explicitly_set = False

    parent_view = _ClassLevelView(state)
    button = _ClassRemoveButton(state, CharacterClass.FIGHTER, parent_view, row=1)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    # After removing Fighter, Cleric becomes first class
    # Cleric gets WIS + CHA saves
    assert state.classes_and_levels[0][0] == CharacterClass.CLERIC
    assert state.saving_throws["wisdom"] is True
    assert state.saving_throws["charisma"] is True
    assert state.saving_throws["strength"] is False


async def test_class_remove_button_first_class_removed_all_saves_cleared_when_no_remaining(mocker):
    """When first class is removed and no remaining classes, saving_throws all False."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5)]
    state.saving_throws = {s: s in ("strength", "constitution") for s in
                           ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}
    state.saves_explicitly_set = False

    parent_view = _ClassLevelView(state)
    button = _ClassRemoveButton(state, CharacterClass.FIGHTER, parent_view, row=1)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    assert len(state.classes_and_levels) == 0
    assert all(v is False for v in state.saving_throws.values())


async def test_class_remove_button_saves_explicitly_set_not_changed(mocker):
    """When saves_explicitly_set=True, removing first class does NOT change saving_throws."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.ROGUE, 2)]
    state.saves_explicitly_set = True
    # User custom saves: only DEX
    state.saving_throws = {s: s == "dexterity" for s in
                           ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}

    parent_view = _ClassLevelView(state)
    button = _ClassRemoveButton(state, CharacterClass.FIGHTER, parent_view, row=1)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    # saves_explicitly_set means saving_throws unchanged
    assert state.saving_throws["dexterity"] is True
    assert state.saving_throws["strength"] is False


# ---------------------------------------------------------------------------
# _ClassLevelView tests
# ---------------------------------------------------------------------------


async def test_class_level_view_on_class_selected_opens_modal(mocker):
    """Selecting a class from the dropdown opens a _LevelForClassModal."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    view = _ClassLevelView(state)
    view._class_select._values = ["Fighter"]

    interaction = make_interaction(mocker)
    await view._on_class_selected(interaction)

    interaction.response.send_modal.assert_called_once()
    modal = interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, _LevelForClassModal)
    assert modal.class_enum == CharacterClass.FIGHTER


async def test_class_level_view_on_class_selected_max_classes_sends_error(mocker):
    """Selecting a new class when already at _MAX_CLASSES sends an error."""
    from commands.wizard.state import _MAX_CLASSES

    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    # Fill to max (5 distinct classes)
    all_classes = list(CharacterClass)
    state.classes_and_levels = [(cls, 4) for cls in all_classes[:_MAX_CLASSES]]

    view = _ClassLevelView(state)
    # Try to add a new class that is not already in the list
    new_class = all_classes[_MAX_CLASSES]  # 6th class
    view._class_select._values = [new_class.value]

    interaction = make_interaction(mocker)
    await view._on_class_selected(interaction)

    interaction.response.send_message.assert_called_once()


async def test_class_level_view_on_class_selected_existing_class_finds_index(mocker):
    """Selecting an existing class passes its index to the modal (existing_index is not None)."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5)]
    view = _ClassLevelView(state)
    view._class_select._values = ["Fighter"]

    interaction = make_interaction(mocker)
    await view._on_class_selected(interaction)

    interaction.response.send_modal.assert_called_once()
    modal = interaction.response.send_modal.call_args.args[0]
    assert modal.existing_index == 0


def test_class_level_view_build_embed_shows_classes_and_total_level():
    """_build_embed shows all classes and total level when classes are set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 5), (CharacterClass.WIZARD, 3)]
    view = _ClassLevelView(state)
    embed = view._build_embed()

    # Should contain a field about total level
    total_level_field = next(
        (f for f in embed.fields if "8" in f.name or "total" in f.name.lower()), None
    )
    assert total_level_field is not None or any("Fighter" in f.value for f in embed.fields)


async def test_class_level_view_refresh_rebuilds_items(mocker):
    """_refresh rebuilds items and calls edit_message."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    view = _ClassLevelView(state)
    interaction = make_interaction(mocker)

    await view._refresh(interaction)

    interaction.response.edit_message.assert_called_once()


# ---------------------------------------------------------------------------
# _HPModal tests
# ---------------------------------------------------------------------------


async def test_hp_modal_valid_hp_stored(mocker):
    """A valid HP value is stored in state.hp_override."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _HPView(state)
    modal = _HPModal(state, parent_view)
    modal.hp_input._value = "55"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.hp_override == 55
    interaction.response.edit_message.assert_called_once()


async def test_hp_modal_non_numeric_sends_error(mocker):
    """A non-numeric HP sends an ephemeral error."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _HPView(state)
    modal = _HPModal(state, parent_view)
    modal.hp_input._value = "lots"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.hp_override is None


async def test_hp_modal_zero_rejected(mocker):
    """HP of 0 is out of range and must be rejected."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _HPView(state)
    modal = _HPModal(state, parent_view)
    modal.hp_input._value = "0"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.hp_override is None


async def test_hp_modal_1000_rejected(mocker):
    """HP of 1000 is out of the valid range (max 999) and must be rejected."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _HPView(state)
    modal = _HPModal(state, parent_view)
    modal.hp_input._value = "1000"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.hp_override is None


async def test_hp_modal_view_refreshed_after_valid_submission(mocker):
    """View is refreshed (edit_message) after a valid HP submission."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    parent_view = _HPView(state)
    modal = _HPModal(state, parent_view)
    modal.hp_input._value = "40"

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.edit_message.assert_called_once()


# ---------------------------------------------------------------------------
# _HPView tests
# ---------------------------------------------------------------------------


def test_hp_view_build_embed_shows_override_when_set():
    """_build_embed shows the hp_override value when set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.hp_override = 45
    view = _HPView(state)
    embed = view._build_embed()

    field_values = [f.value for f in embed.fields]
    assert any("45" in v for v in field_values)


def test_hp_view_build_embed_shows_will_auto_calc_hint_when_class_and_con_set():
    """_build_embed shows 'will auto-calc' hint when class and CON are set but no override."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    state.constitution = 14
    view = _HPView(state)
    embed = view._build_embed()

    field_values = [f.value for f in embed.fields]
    assert any(Strings.WIZARD_HP_WILL_AUTO_CALC in v for v in field_values)


def test_hp_view_build_embed_shows_cannot_auto_calc_when_no_class():
    """_build_embed shows 'cannot auto-calc' hint when no class is set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.constitution = 14
    # No class
    view = _HPView(state)
    embed = view._build_embed()

    field_values = [f.value for f in embed.fields]
    assert any(Strings.WIZARD_HP_CANNOT_AUTO_CALC in v for v in field_values)


def test_hp_view_build_embed_shows_cannot_auto_calc_when_no_con():
    """_build_embed shows 'cannot auto-calc' hint when CON is not set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    # No CON
    view = _HPView(state)
    embed = view._build_embed()

    field_values = [f.value for f in embed.fields]
    assert any(Strings.WIZARD_HP_CANNOT_AUTO_CALC in v for v in field_values)


# ---------------------------------------------------------------------------
# _WeaponSelectButton tests
# ---------------------------------------------------------------------------


async def test_weapon_select_button_adds_weapon_to_state(mocker):
    """Clicking a weapon adds it to state.weapons_to_add."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    weapons_view = _WeaponsWizardView(state)
    weapon_data = {"name": "Longsword", "damage_dice": "1d8"}
    button = _WeaponSelectButton(state, weapon_data, weapons_view)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    assert len(state.weapons_to_add) == 1
    assert state.weapons_to_add[0]["name"] == "Longsword"
    interaction.response.edit_message.assert_called_once()


async def test_weapon_select_button_already_queued_sends_error(mocker):
    """Clicking a weapon already in weapons_to_add sends an ephemeral error."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222",
        guild_name="Test", name="Hero",
    )
    weapon_data = {"name": "Shortsword", "damage_dice": "1d6"}
    state.weapons_to_add = [weapon_data]

    weapons_view = _WeaponsWizardView(state)
    button = _WeaponSelectButton(state, weapon_data, weapons_view)

    interaction = make_interaction(mocker)
    await button.callback(interaction)

    interaction.response.send_message.assert_called_once()
    assert len(state.weapons_to_add) == 1  # not added twice


# ---------------------------------------------------------------------------
# _WeaponResultsView tests
# ---------------------------------------------------------------------------


def test_weapon_results_view_build_embed_contains_result_select_string():
    """_build_embed contains WIZARD_WEAPONS_RESULT_SELECT in a field."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    weapons_view = _WeaponsWizardView(state)
    results = [{"name": "Dagger"}, {"name": "Handaxe"}]
    results_view = _WeaponResultsView(state, results, weapons_view)
    embed = results_view._build_embed()

    field_names = [f.name for f in embed.fields]
    assert Strings.WIZARD_WEAPONS_RESULT_SELECT in field_names


def test_weapon_results_view_contains_one_button_per_result():
    """_WeaponResultsView contains one _WeaponSelectButton per result."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    weapons_view = _WeaponsWizardView(state)
    results = [{"name": "Dagger"}, {"name": "Handaxe"}, {"name": "Longsword"}]
    results_view = _WeaponResultsView(state, results, weapons_view)

    select_buttons = [
        item for item in results_view.children
        if isinstance(item, _WeaponSelectButton)
    ]
    assert len(select_buttons) == 3


def test_weapon_results_view_contains_back_to_weapons_button():
    """_WeaponResultsView contains a _BackToWeaponsButton."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    weapons_view = _WeaponsWizardView(state)
    results = [{"name": "Dagger"}]
    results_view = _WeaponResultsView(state, results, weapons_view)

    back_buttons = [
        item for item in results_view.children
        if isinstance(item, _BackToWeaponsButton)
    ]
    assert len(back_buttons) == 1


# ---------------------------------------------------------------------------
# _WeaponsWizardView tests
# ---------------------------------------------------------------------------


def test_weapons_wizard_view_build_embed_shows_queued_weapons():
    """_build_embed shows queued weapons when weapons_to_add is not empty."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.weapons_to_add = [{"name": "Longsword"}, {"name": "Shield"}]
    view = _WeaponsWizardView(state)
    embed = view._build_embed()

    field_values = [f.value for f in embed.fields]
    assert any("Longsword" in v for v in field_values)


def test_weapons_wizard_view_build_embed_shows_no_results_query():
    """_build_embed shows a no-results message when no_results_query is provided."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    view = _WeaponsWizardView(state)
    embed = view._build_embed(no_results_query="zzz invalid weapon")

    field_names = [f.name for f in embed.fields]
    assert Strings.WIZARD_WEAPONS_NO_RESULTS_TITLE in field_names


def test_weapons_wizard_view_build_embed_no_queued_section_when_empty():
    """_build_embed does NOT show queued weapons section when weapons_to_add is empty."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    view = _WeaponsWizardView(state)
    embed = view._build_embed()

    field_names = [f.name for f in embed.fields]
    assert not any("Queued" in n for n in field_names)


# ---------------------------------------------------------------------------
# _SkillsView tests
# ---------------------------------------------------------------------------


def test_skills_view_nav_buttons_on_row_4():
    """Nav buttons (SaveReturn, ReturnNoSave, Cancel) are on row 4 in _SkillsView."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    view = _SkillsView(state)

    nav_buttons = [
        item for item in view.children
        if isinstance(item, discord.ui.Button) and item.row == 4
    ]
    assert len(nav_buttons) >= 2  # At least SaveReturn and ReturnNoSave


# ---------------------------------------------------------------------------
# _CharacterNameModal — on_submit
# ---------------------------------------------------------------------------


async def test_name_modal_valid_name_returns_to_hub(mocker):
    """A valid name saves to state and calls edit_message to show the hub."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
    )
    modal = _CharacterNameModal(state)
    _set_text_input(modal.name_input, "Thalindra")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.name == "Thalindra"
    # _show_hub calls interaction.response.edit_message
    interaction.response.edit_message.assert_called_once()


async def test_name_modal_empty_name_sends_error(mocker):
    """An empty (whitespace-only) name sends an ephemeral error."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
    )
    modal = _CharacterNameModal(state)
    _set_text_input(modal.name_input, "   ")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.name == ""


async def test_name_modal_does_not_navigate_to_class_view(mocker):
    """After submitting a valid name, the hub is shown (not _ClassLevelView)."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
    )
    modal = _CharacterNameModal(state)
    _set_text_input(modal.name_input, "Aria")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # edit_message is used (hub), not send_modal
    interaction.response.edit_message.assert_called_once()
    # The view passed should be HubView, not _ClassLevelView
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert isinstance(call_kwargs.get("view"), HubView)


# ---------------------------------------------------------------------------
# _PhysicalStatsModal — on_submit (STR / DEX / CON only)
# ---------------------------------------------------------------------------


async def test_primary_stats_modal_valid_stats_stored(mocker):
    """Valid STR/DEX/CON are stored in state and the stats view is refreshed."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _PhysicalStatsModal(state, parent_view)
    _set_text_input(modal.str_input, "16")
    _set_text_input(modal.dex_input, "14")
    _set_text_input(modal.con_input, "15")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.strength == 16
    assert state.dexterity == 14
    assert state.constitution == 15
    interaction.response.edit_message.assert_called_once()


async def test_primary_stats_modal_non_number_rejected(mocker):
    """A non-numeric STR/DEX/CON value sends an error and nothing is stored."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _PhysicalStatsModal(state, parent_view)
    _set_text_input(modal.str_input, "abc")
    _set_text_input(modal.dex_input, "14")
    _set_text_input(modal.con_input, "15")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.strength is None


async def test_primary_stats_modal_out_of_range_rejected(mocker):
    """A STR/DEX/CON stat above 30 sends an error."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _PhysicalStatsModal(state, parent_view)
    _set_text_input(modal.str_input, "31")
    _set_text_input(modal.dex_input, "14")
    _set_text_input(modal.con_input, "15")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.strength is None


async def test_primary_stats_modal_zero_rejected(mocker):
    """A STR/DEX/CON stat of 0 is out of range (minimum is 1)."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _PhysicalStatsModal(state, parent_view)
    _set_text_input(modal.str_input, "0")
    _set_text_input(modal.dex_input, "14")
    _set_text_input(modal.con_input, "15")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.strength is None


# ---------------------------------------------------------------------------
# _MentalStatsModal — on_submit (INT / WIS / CHA)
# ---------------------------------------------------------------------------


async def test_mental_stats_modal_valid_stores_and_advances(mocker):
    """Valid INT/WIS/CHA are stored; the view refreshes the stats step."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _MentalStatsModal(state, parent_view)
    _set_text_input(modal.wis_input, "12")
    _set_text_input(modal.cha_input, "8")
    _set_text_input(modal.int_input, "10")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.wisdom == 12
    assert state.charisma == 8
    assert state.intelligence == 10
    interaction.response.edit_message.assert_called_once()


async def test_mental_stats_modal_invalid_wis_sends_error(mocker):
    """A non-numeric WIS value sends an error."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _MentalStatsModal(state, parent_view)
    _set_text_input(modal.wis_input, "abc")
    _set_text_input(modal.cha_input, "8")
    _set_text_input(modal.int_input, "10")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.wisdom is None


async def test_mental_stats_modal_invalid_cha_sends_error(mocker):
    """A non-numeric CHA value sends an error."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _StatsView(state)
    modal = _MentalStatsModal(state, parent_view)
    _set_text_input(modal.wis_input, "12")
    _set_text_input(modal.cha_input, "zz")
    _set_text_input(modal.int_input, "10")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.charisma is None


# ---------------------------------------------------------------------------
# _InitiativeModal — on_submit
# ---------------------------------------------------------------------------


async def test_initiative_modal_valid_stores_bonus(mocker):
    """A valid positive initiative bonus is stored and returns to hub."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    modal = _InitiativeModal(state)
    _set_text_input(modal.init_input, "+3")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.initiative_bonus == 3
    interaction.response.edit_message.assert_called_once()


async def test_initiative_modal_negative_stores_bonus(mocker):
    """A valid negative initiative bonus is stored correctly."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    modal = _InitiativeModal(state)
    _set_text_input(modal.init_input, "-2")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.initiative_bonus == -2
    interaction.response.edit_message.assert_called_once()


async def test_initiative_modal_invalid_sends_error(mocker):
    """A non-numeric initiative value sends an error and initiative_bonus remains None."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    modal = _InitiativeModal(state)
    _set_text_input(modal.init_input, "fast")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.initiative_bonus is None


# ---------------------------------------------------------------------------
# _ACModal — on_submit
# ---------------------------------------------------------------------------


async def test_ac_modal_valid_stores_and_advances(mocker):
    """A valid AC is stored and the view refreshes the current AC step."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _ACView(state)
    modal = _ACModal(state, parent_view)
    _set_text_input(modal.ac_input, "17")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.ac == 17
    interaction.response.edit_message.assert_called_once()


async def test_ac_modal_non_number_sends_error(mocker):
    """A non-numeric AC sends an error."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _ACView(state)
    modal = _ACModal(state, parent_view)
    _set_text_input(modal.ac_input, "high")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.ac is None


async def test_ac_modal_out_of_range_sends_error(mocker):
    """AC of 31 is out of range and must be rejected."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    parent_view = _ACView(state)
    modal = _ACModal(state, parent_view)
    _set_text_input(modal.ac_input, "31")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    assert state.ac is None


# ---------------------------------------------------------------------------
# Save toggle button
# ---------------------------------------------------------------------------


async def test_save_toggle_flips_proficiency(mocker):
    """Clicking a save toggle flips its value in state.saving_throws."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    assert state.saving_throws["strength"] is False

    view = _SavesView(state)
    interaction = make_interaction(mocker)

    # Find the STR Save toggle button and trigger it
    str_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button) and "STR" in (item.label or "")
    )
    await str_button.callback(interaction)

    assert state.saving_throws["strength"] is True
    assert state.saves_explicitly_set is True


async def test_save_toggle_sets_explicitly_set_flag(mocker):
    """Toggling any save sets saves_explicitly_set on the state."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    view = _SavesView(state)
    interaction = make_interaction(mocker)

    wis_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button) and "WIS" in (item.label or "")
    )
    await wis_button.callback(interaction)

    assert state.saves_explicitly_set is True


# ---------------------------------------------------------------------------
# Skill toggle button
# ---------------------------------------------------------------------------


async def test_skill_toggle_marks_proficient(mocker):
    """Clicking a skill toggle marks it proficient in state.skills."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    view = _SkillsView(state)
    interaction = make_interaction(mocker)

    acro_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button) and item.label == "Acrobatics"
    )
    await acro_button.callback(interaction)

    assert state.skills.get("Acrobatics") is True


async def test_skill_toggle_twice_toggles_back(mocker):
    """Toggling the same skill twice returns it to not-proficient."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    view = _SkillsView(state)
    interaction = make_interaction(mocker)

    stealth_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button) and item.label == "Stealth"
    )
    # First click: proficient
    await stealth_button.callback(interaction)
    # Second click: not proficient
    await stealth_button.callback(interaction)

    assert state.skills.get("Stealth") is False


# ---------------------------------------------------------------------------
# HubView — button colours and enable/disable state
# ---------------------------------------------------------------------------


def test_hub_view_name_button_is_danger_when_no_name():
    """HubView name button is red (danger style) when no name is set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name=""
    )
    view = HubView(state)

    name_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_NAME_BUTTON
    )
    assert name_button.style == discord.ButtonStyle.danger


def test_hub_view_name_button_is_success_when_name_set():
    """HubView name button is green (success style) when a name is set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Aria"
    )
    view = HubView(state)

    name_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_NAME_BUTTON
    )
    assert name_button.style == discord.ButtonStyle.success


def test_hub_view_save_exit_disabled_when_no_name():
    """HubView Save & Exit button is disabled when no name is set."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name=""
    )
    view = HubView(state)

    save_exit_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_SAVE_EXIT
    )
    assert save_exit_button.disabled is True


def test_hub_view_save_exit_enabled_when_name_set():
    """HubView Save & Exit button is enabled when a name has been entered."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Aria"
    )
    view = HubView(state)

    save_exit_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_SAVE_EXIT
    )
    assert save_exit_button.disabled is False


def test_hub_view_section_buttons_are_danger_when_not_completed():
    """Section buttons in HubView are red (danger) when section is not in sections_completed."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    # No sections completed
    view = HubView(state)

    section_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_CLASS_LEVEL_BUTTON
    )
    assert section_button.style == discord.ButtonStyle.danger


def test_hub_view_section_button_is_success_when_completed():
    """Section buttons in HubView are green (success) when the section is completed."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.sections_completed.add("class_level")
    view = HubView(state)

    section_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_CLASS_LEVEL_BUTTON
    )
    assert section_button.style == discord.ButtonStyle.success


def test_hub_view_all_section_buttons_initially_danger():
    """All section buttons are danger (red) when sections_completed is empty."""
    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    view = HubView(state)

    section_labels = {
        Strings.WIZARD_HUB_CLASS_LEVEL_BUTTON,
        Strings.WIZARD_HUB_ABILITY_SCORES_BUTTON,
        Strings.WIZARD_HUB_AC_BUTTON,
        Strings.WIZARD_HUB_SAVING_THROWS_BUTTON,
        Strings.WIZARD_HUB_SKILLS_BUTTON,
        Strings.WIZARD_HUB_HP_BUTTON,
        Strings.WIZARD_HUB_WEAPONS_BUTTON,
    }
    section_buttons = [
        item for item in view.children
        if isinstance(item, discord.ui.Button) and item.label in section_labels
    ]
    assert len(section_buttons) == 7
    for button in section_buttons:
        assert button.style == discord.ButtonStyle.danger


# ---------------------------------------------------------------------------
# Section _save_and_return / _return_no_save / _cancel_wizard
# ---------------------------------------------------------------------------


async def test_save_and_return_marks_section_complete_and_shows_hub(mocker):
    """_save_and_return adds the section key to sections_completed and shows hub."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    view = _ACView(state)
    state.ac = 17

    interaction = make_interaction(mocker)
    await view._save_and_return(interaction)

    assert "ac" in state.sections_completed
    interaction.response.edit_message.assert_called_once()


async def test_return_no_save_restores_snapshot_and_shows_hub(mocker):
    """_return_no_save restores the pre-entry snapshot and shows the hub."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    state.ac = 10  # value before entering the section
    view = _ACView(state)  # snapshot taken here: ac=10

    # Simulate a change during the section
    state.ac = 25

    interaction = make_interaction(mocker)
    await view._return_no_save(interaction)

    # Snapshot should restore the original value
    assert state.ac == 10
    interaction.response.edit_message.assert_called_once()



async def test_hub_cancel_button_edits_message_with_cancelled_embed(mocker):
    """Clicking the HubView cancel button shows a cancellation embed with view=None."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    view = HubView(state)
    interaction = make_interaction(mocker)

    cancel_button = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.WIZARD_HUB_CANCEL
    )
    await cancel_button.callback(interaction)

    interaction.response.edit_message.assert_called_once()
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert call_kwargs.get("view") is None
    embed = call_kwargs.get("embed")
    assert embed is not None
    assert embed.title == Strings.WIZARD_CANCELLED


async def test_saves_view_save_and_return_marks_saves_explicitly_set(mocker):
    """_SavesView._save_and_return sets saves_explicitly_set=True."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    view = _SavesView(state)
    interaction = make_interaction(mocker)

    await view._save_and_return(interaction)

    assert state.saves_explicitly_set is True
    assert "saving_throws" in state.sections_completed


# ---------------------------------------------------------------------------
# /character create entry point
# ---------------------------------------------------------------------------


async def test_character_create_sends_wizard_hub(wizard_bot, interaction):
    """``/character create`` sends an ephemeral message with the wizard hub embed."""
    cb = get_callback(wizard_bot, "character", "create")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert isinstance(view, HubView)


# ---------------------------------------------------------------------------
# /character saves — button-based view
# ---------------------------------------------------------------------------


async def test_character_saves_sends_toggle_view(
    wizard_bot, interaction, sample_user, sample_server, sample_character
):
    """``/character saves`` sends an ephemeral message with a CharacterSavesEditView."""
    from commands.character_commands import CharacterSavesEditView

    cb = get_callback(wizard_bot, "character", "saves")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert isinstance(view, CharacterSavesEditView)


async def test_character_saves_no_active_character_sends_error(
    wizard_bot, interaction, sample_user, sample_server
):
    """``/character saves`` returns an error when there is no active character."""
    cb = get_callback(wizard_bot, "character", "saves")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert Strings.CHARACTER_NOT_FOUND in msg


async def test_saves_edit_view_save_changes_persists(
    mocker, session_factory, sample_user, sample_server, sample_character
):
    """Clicking Save Changes in CharacterSavesEditView writes saves to the DB."""
    from commands.character_commands import CharacterSavesEditView

    char_id = sample_character.id

    current = {
        "strength": False, "dexterity": False, "constitution": False,
        "intelligence": False, "wisdom": False, "charisma": False,
    }
    view = CharacterSavesEditView(
        char_id=char_id,
        char_name=sample_character.name,
        current_saves=current,
    )
    # Toggle STR on
    view.saves["strength"] = True

    # Patch SessionLocal in character_commands to use the test session factory
    import commands.character_commands as cc_mod
    original = cc_mod.SessionLocal
    cc_mod.SessionLocal = session_factory

    try:
        save_btn = next(
            item for item in view.children
            if isinstance(item, discord.ui.Button)
            and item.label == Strings.BUTTON_SAVE_CHANGES
        )
        interaction = make_interaction(mocker)
        await save_btn.callback(interaction)
    finally:
        cc_mod.SessionLocal = original

    # Verify via a fresh session so we don't rely on the closed test session
    verify_session = session_factory()
    try:
        from models import Character as CharacterModel
        refreshed = verify_session.get(CharacterModel, char_id)
        assert refreshed.st_prof_strength is True
        assert refreshed.st_prof_dexterity is False
    finally:
        verify_session.close()


async def test_saves_edit_view_cancel_makes_no_changes(
    mocker, db_session, sample_user, sample_server, sample_character
):
    """Clicking Cancel leaves the character's saves unchanged."""
    from commands.character_commands import CharacterSavesEditView

    current = {
        "strength": True, "dexterity": False, "constitution": True,
        "intelligence": False, "wisdom": False, "charisma": False,
    }
    view = CharacterSavesEditView(
        char_id=sample_character.id,
        char_name=sample_character.name,
        current_saves=current,
    )

    cancel_btn = next(
        item for item in view.children
        if isinstance(item, discord.ui.Button)
        and item.label == Strings.BUTTON_CANCEL
    )
    interaction = make_interaction(mocker)
    await cancel_btn.callback(interaction)

    # DB unchanged — sample_character still has the original saves
    db_session.refresh(sample_character)
    assert sample_character.st_prof_strength is True


# ---------------------------------------------------------------------------
# _PrimaryStatsButton and _WisChaButton dynamic styles
# ---------------------------------------------------------------------------


def test_primary_stats_button_is_danger_when_physical_stats_incomplete():
    """_PrimaryStatsButton is danger when any of STR, DEX, or CON is missing."""
    from commands.wizard.buttons import _PrimaryStatsButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    # Only STR set — DEX and CON are None
    state.strength = 16
    parent_view = _StatsView(state)

    button = _PrimaryStatsButton(state, parent_view, row=0)

    assert button.style == discord.ButtonStyle.danger


def test_primary_stats_button_is_success_when_all_physical_stats_set():
    """_PrimaryStatsButton is success when STR, DEX, and CON are all set."""
    from commands.wizard.buttons import _PrimaryStatsButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.strength = 16
    state.dexterity = 14
    state.constitution = 15
    parent_view = _StatsView(state)

    button = _PrimaryStatsButton(state, parent_view, row=0)

    assert button.style == discord.ButtonStyle.success


def test_wischa_button_is_danger_when_mental_stats_incomplete():
    """_WisChaButton is danger when any of INT, WIS, or CHA is missing."""
    from commands.wizard.buttons import _WisChaButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    # Only WIS set — INT and CHA are None
    state.wisdom = 12
    parent_view = _StatsView(state)

    button = _WisChaButton(state, parent_view, row=1)

    assert button.style == discord.ButtonStyle.danger


def test_wischa_button_is_success_when_all_mental_stats_set():
    """_WisChaButton is success when INT, WIS, and CHA are all set."""
    from commands.wizard.buttons import _WisChaButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.intelligence = 10
    state.wisdom = 12
    state.charisma = 8
    parent_view = _StatsView(state)

    button = _WisChaButton(state, parent_view, row=1)

    assert button.style == discord.ButtonStyle.success


# ---------------------------------------------------------------------------
# _StatsView._refresh() rebuilds button styles
# ---------------------------------------------------------------------------


async def test_stats_view_refresh_turns_physical_button_green_after_all_set(mocker):
    """After setting all physical stats via modal, _StatsView._refresh rebuilds the
    STR/DEX/CON button as success (green)."""
    from commands.wizard.buttons import _PrimaryStatsButton
    from commands.wizard.modals import _PhysicalStatsModal

    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    parent_view = _StatsView(state)

    # Confirm the button starts red (no stats set)
    physical_btn_before = next(
        item for item in parent_view.children
        if isinstance(item, _PrimaryStatsButton)
    )
    assert physical_btn_before.style == discord.ButtonStyle.danger

    # Submit the physical stats modal (which calls parent_view._refresh)
    modal = _PhysicalStatsModal(state, parent_view)
    _set_text_input(modal.str_input, "18")
    _set_text_input(modal.dex_input, "14")
    _set_text_input(modal.con_input, "16")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # _refresh was called — find the updated button
    physical_btn_after = next(
        item for item in parent_view.children
        if isinstance(item, _PrimaryStatsButton)
    )
    assert physical_btn_after.style == discord.ButtonStyle.success


async def test_stats_view_refresh_turns_mental_button_green_after_all_set(mocker):
    """After setting all mental stats via modal, _StatsView._refresh rebuilds the
    INT/WIS/CHA button as success (green)."""
    from commands.wizard.buttons import _WisChaButton
    from commands.wizard.modals import _MentalStatsModal

    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    parent_view = _StatsView(state)

    # Confirm the button starts red (no stats set)
    mental_btn_before = next(
        item for item in parent_view.children
        if isinstance(item, _WisChaButton)
    )
    assert mental_btn_before.style == discord.ButtonStyle.danger

    # Submit the mental stats modal (which calls parent_view._refresh)
    modal = _MentalStatsModal(state, parent_view)
    _set_text_input(modal.int_input, "10")
    _set_text_input(modal.wis_input, "12")
    _set_text_input(modal.cha_input, "8")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    # _refresh was called — find the updated button
    mental_btn_after = next(
        item for item in parent_view.children
        if isinstance(item, _WisChaButton)
    )
    assert mental_btn_after.style == discord.ButtonStyle.success


# ---------------------------------------------------------------------------
# _HubInitiativeButton styles
# ---------------------------------------------------------------------------


def test_hub_initiative_button_is_danger_when_no_bonus_and_no_dexterity():
    """_HubInitiativeButton is danger when both initiative_bonus and dexterity are None."""
    from commands.wizard.buttons import _HubInitiativeButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    # Both initiative_bonus and dexterity default to None
    button = _HubInitiativeButton(state, row=0)

    assert button.style == discord.ButtonStyle.danger


def test_hub_initiative_button_is_primary_when_dexterity_set_but_no_override():
    """_HubInitiativeButton is primary (blue) when dexterity is set but no explicit bonus."""
    from commands.wizard.buttons import _HubInitiativeButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.dexterity = 14  # will auto-calc from DEX mod
    button = _HubInitiativeButton(state, row=0)

    assert button.style == discord.ButtonStyle.primary


def test_hub_initiative_button_is_success_when_initiative_bonus_explicitly_set():
    """_HubInitiativeButton is success (green) when an explicit initiative_bonus is set."""
    from commands.wizard.buttons import _HubInitiativeButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.initiative_bonus = 3
    button = _HubInitiativeButton(state, row=0)

    assert button.style == discord.ButtonStyle.success


def test_hub_initiative_button_success_overrides_dexterity_when_both_set():
    """When both initiative_bonus and dexterity are set, success (green) takes priority."""
    from commands.wizard.buttons import _HubInitiativeButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test", name="Hero"
    )
    state.dexterity = 16
    state.initiative_bonus = 5  # explicit override wins
    button = _HubInitiativeButton(state, row=0)

    assert button.style == discord.ButtonStyle.success


# ---------------------------------------------------------------------------
# _section_button_style — auto-calculated sections
# ---------------------------------------------------------------------------


def test_section_button_style_saving_throws_danger_when_no_class_and_not_explicit():
    """saving_throws section is danger when no class is set and saves_explicitly_set is False."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.character_class is None
    assert state.saves_explicitly_set is False

    style = _section_button_style("saving_throws", state)

    assert style == discord.ButtonStyle.danger


def test_section_button_style_saving_throws_primary_when_class_set_but_not_explicit():
    """saving_throws section is primary (auto from class) when class is set but saves_explicitly_set is False."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.FIGHTER, 1)]
    # classes_and_levels being set makes character_class return the first class
    assert state.saves_explicitly_set is False

    style = _section_button_style("saving_throws", state)

    assert style == discord.ButtonStyle.primary


def test_section_button_style_saving_throws_success_when_explicitly_set():
    """saving_throws section is success when saves_explicitly_set is True."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.saves_explicitly_set = True

    style = _section_button_style("saving_throws", state)

    assert style == discord.ButtonStyle.success


def test_section_button_style_hp_danger_when_no_class_and_no_override():
    """hp section is danger when no class and no hp_override are set."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    assert state.character_class is None
    assert state.hp_override is None

    style = _section_button_style("hp", state)

    assert style == discord.ButtonStyle.danger


def test_section_button_style_hp_primary_when_class_and_constitution_set_but_no_override():
    """hp section is primary when class and constitution are both set but no hp_override."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.BARBARIAN, 1)]
    state.constitution = 16
    # hp_override remains None — HP will be auto-calculated

    style = _section_button_style("hp", state)

    assert style == discord.ButtonStyle.primary


def test_section_button_style_hp_success_when_hp_override_explicitly_set():
    """hp section is success when hp_override is explicitly set."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.hp_override = 42

    style = _section_button_style("hp", state)

    assert style == discord.ButtonStyle.success


def test_section_button_style_hp_danger_when_class_set_but_constitution_missing():
    """hp section is danger when class is set but constitution is None (cannot auto-calc without CON)."""
    from commands.wizard.hub_view import _section_button_style

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    state.classes_and_levels = [(CharacterClass.WIZARD, 1)]
    # constitution is None — cannot auto-calc HP

    style = _section_button_style("hp", state)

    assert style == discord.ButtonStyle.danger


# ---------------------------------------------------------------------------
# Cancel button placement — section views have no cancel; hub has exactly one
# ---------------------------------------------------------------------------


def test_section_views_have_no_cancel_button():
    """Section views must not contain any _CancelWizardButton."""
    from commands.wizard.buttons import _CancelWizardButton
    from commands.wizard.section_views import (
        _ACView,
        _ClassLevelView,
        _HPView,
        _SavesView,
        _SkillsView,
        _StatsView,
        _WeaponsWizardView,
    )

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    section_views = [
        _StatsView(state),
        _ClassLevelView(state),
        _ACView(state),
        _SavesView(state),
        _SkillsView(state),
        _HPView(state),
        _WeaponsWizardView(state),
    ]
    for view in section_views:
        cancel_buttons = [
            item for item in view.children if isinstance(item, _CancelWizardButton)
        ]
        assert cancel_buttons == [], (
            f"{type(view).__name__} unexpectedly contains a _CancelWizardButton"
        )


def test_weapon_results_view_has_no_cancel_button():
    """_WeaponResultsView must not contain any _CancelWizardButton."""
    from commands.wizard.buttons import _CancelWizardButton
    from commands.wizard.section_views import _WeaponResultsView, _WeaponsWizardView

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    weapons_view = _WeaponsWizardView(state)
    # Pass an empty results list so no _WeaponSelectButton items are added
    view = _WeaponResultsView(state, results=[], weapons_view=weapons_view)
    cancel_buttons = [
        item for item in view.children if isinstance(item, _CancelWizardButton)
    ]
    assert cancel_buttons == []


def test_hub_view_has_cancel_button():
    """HubView must contain exactly one _HubCancelButton."""
    from commands.wizard.hub_view import HubView, _HubCancelButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    view = HubView(state)
    hub_cancel_buttons = [
        item for item in view.children if isinstance(item, _HubCancelButton)
    ]
    assert len(hub_cancel_buttons) == 1


# ---------------------------------------------------------------------------
# _InitiativeModal — blank input clears the bonus
# ---------------------------------------------------------------------------


async def test_initiative_modal_blank_clears_bonus(mocker):
    """Submitting a blank initiative clears any existing override and returns to hub."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    state.initiative_bonus = 5
    modal = _InitiativeModal(state)
    _set_text_input(modal.init_input, "")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.initiative_bonus is None
    interaction.response.edit_message.assert_called_once()


async def test_initiative_modal_blank_when_already_none_stays_none(mocker):
    """Submitting blank when initiative_bonus is already None keeps it None and returns to hub."""
    state = WizardState(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test",
        name="Hero",
    )
    assert state.initiative_bonus is None
    modal = _InitiativeModal(state)
    _set_text_input(modal.init_input, "")

    interaction = make_interaction(mocker)
    await modal.on_submit(interaction)

    assert state.initiative_bonus is None
    interaction.response.edit_message.assert_called_once()


# ---------------------------------------------------------------------------
# HubView — Quick Setup button removed
# ---------------------------------------------------------------------------


def test_hub_view_has_no_quick_setup_button():
    """HubView must not contain any _QuickSetupButton."""
    from commands.wizard.hub_view import HubView, _QuickSetupButton

    state = WizardState(
        user_discord_id="1", guild_discord_id="2", guild_name="Test"
    )
    view = HubView(state)
    quick_setup_buttons = [
        item for item in view.children if isinstance(item, _QuickSetupButton)
    ]
    assert quick_setup_buttons == []


# HubView — on_timeout robustness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hub_view_on_timeout_does_not_raise_when_message_absent(mocker):
    """on_timeout must not raise AttributeError when discord.py hasn't set .message."""
    state = WizardState(
        user_discord_id="111", guild_discord_id="222", guild_name="Test", name="Hero"
    )
    view = HubView(state)
    # Ensure the attribute is absent (simulate the discord.py build that never sets it)
    if hasattr(view, "message"):
        delattr(view, "message")

    # Should complete without raising
    await view.on_timeout()

    # State reference must be cleared
    assert view.wizard_state is None


# ---------------------------------------------------------------------------
# _finish_wizard — completion behaviour (ephemeral dismiss + public followup)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_wizard_success_dismisses_ephemeral_message(mocker, db_session):
    """On success, edit_message is called with the dismissal string, embed=None, view=None.

    This verifies the ephemeral wizard message is replaced with a brief
    confirmation rather than the full completion embed.
    """
    state, interaction = _make_state(mocker)
    fake_char = mocker.Mock(spec=Character)
    fake_char.name = "Thalindra"
    fake_char.max_hp = 10
    mocker.patch(
        "commands.wizard.completion.save_character_from_wizard",
        return_value=(fake_char, None),
    )
    mocker.patch("commands.wizard.completion.SessionLocal", return_value=db_session)

    from commands.wizard import _finish_wizard

    await _finish_wizard(state, interaction)

    interaction.response.edit_message.assert_called_once_with(
        content=Strings.WIZARD_COMPLETE_EPHEMERAL_DISMISS,
        embed=None,
        view=None,
    )


@pytest.mark.asyncio
async def test_finish_wizard_success_sends_public_followup_with_embed(mocker, db_session):
    """On success, followup.send is called with ephemeral=False and a discord.Embed."""
    state, interaction = _make_state(mocker)
    fake_char = mocker.Mock(spec=Character)
    fake_char.name = "Thalindra"
    fake_char.max_hp = 10
    mocker.patch(
        "commands.wizard.completion.save_character_from_wizard",
        return_value=(fake_char, None),
    )
    mocker.patch("commands.wizard.completion.SessionLocal", return_value=db_session)

    from commands.wizard import _finish_wizard

    await _finish_wizard(state, interaction)

    interaction.followup.send.assert_called_once()
    call_kwargs = interaction.followup.send.call_args.kwargs
    assert call_kwargs.get("ephemeral") is False
    assert isinstance(call_kwargs.get("embed"), discord.Embed)


@pytest.mark.asyncio
async def test_finish_wizard_success_does_not_pass_embed_to_edit_message(mocker, db_session):
    """Regression: the completion embed must NOT be passed to edit_message.

    The old behaviour sent the embed via edit_message (keeping it ephemeral).
    The new behaviour sends it only via followup.send (making it public).
    """
    state, interaction = _make_state(mocker)
    fake_char = mocker.Mock(spec=Character)
    fake_char.name = "Thalindra"
    fake_char.max_hp = 10
    mocker.patch(
        "commands.wizard.completion.save_character_from_wizard",
        return_value=(fake_char, None),
    )
    mocker.patch("commands.wizard.completion.SessionLocal", return_value=db_session)

    from commands.wizard import _finish_wizard

    await _finish_wizard(state, interaction)

    # edit_message must not have received a non-None embed
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert call_kwargs.get("embed") is None


@pytest.mark.asyncio
async def test_finish_wizard_error_stays_ephemeral_no_followup(mocker, db_session):
    """When save_character_from_wizard returns an error, the error message is
    sent ephemerally and followup.send is never called."""
    state, interaction = _make_state(mocker)
    mocker.patch(
        "commands.wizard.completion.save_character_from_wizard",
        return_value=(None, Strings.CHAR_CREATE_NAME_LIMIT),
    )
    mocker.patch("commands.wizard.completion.SessionLocal", return_value=db_session)

    from commands.wizard import _finish_wizard

    await _finish_wizard(state, interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.CHAR_CREATE_NAME_LIMIT, ephemeral=True
    )
    interaction.followup.send.assert_not_called()
