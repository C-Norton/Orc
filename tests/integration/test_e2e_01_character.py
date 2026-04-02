"""
E2E integration tests — Sections 2–5: Character Creation, Stats, Saves, Multi-class.

Runs first in the integration suite. Creates Aldric (Fighter 3 with full stats,
AC 17, skill proficiencies) which subsequent test files depend on.

Run the full suite together:
    pytest tests/integration/ -v
"""

import pytest
from sqlalchemy.orm import sessionmaker

from models import Character, CharacterSkill, ClassLevel
from enums.character_class import CharacterClass
from enums.skill_proficiency_status import SkillProficiencyStatus
from commands.character_commands import register_character_commands
from commands.wizard.state import WizardState, save_character_from_wizard
from commands.wizard.completion import _finish_wizard
from tests.integration.conftest import (
    PLAYER_A_ID,
    GUILD_ID,
    make_bot,
    make_e2e_interaction,
    get_callback,
    patch_session_locals,
)


# ---------------------------------------------------------------------------
# Section 2: Character Creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_2_01_character_create_sends_ephemeral_response(
    int_session_factory,
    mocker,
) -> None:
    """§2.1: /character create sends an ephemeral response (wizard hub view)."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "create")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_2_07_wizard_creates_aldric(
    int_session_factory,
    mocker,
) -> None:
    """§2.7: Wizard completion creates 'Aldric' as Fighter 3, active character.

    Calls _finish_wizard directly with a pre-populated WizardState — the same
    pattern used in test_character_wizard.py — so we bypass the Discord modal
    flow entirely and test DB persistence directly.
    """
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )

    wizard_state = WizardState(
        user_discord_id=PLAYER_A_ID,
        guild_discord_id=GUILD_ID,
        guild_name="Integration Test Server",
        name="Aldric",
        classes_and_levels=[(CharacterClass.FIGHTER, 3)],
    )

    interaction = make_e2e_interaction(mocker, PLAYER_A_ID, username="PlayerA")
    # _finish_wizard calls response.edit_message and followup.send —
    # make sure the mock is set up to handle edit_message gracefully.
    interaction.response.edit_message = mocker.AsyncMock()

    # Call _finish_wizard which uses the patched SessionLocal internally.
    await _finish_wizard(wizard_state, interaction)

    # Verify DB state in a fresh session.
    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        assert aldric is not None, "Aldric was not created in the DB"
        assert aldric.is_active is True

        fighter_class_level = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Fighter")
            .first()
        )
        assert fighter_class_level is not None, "Fighter ClassLevel row not found"
        assert fighter_class_level.level == 3
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_2_08_character_list_shows_aldric(
    int_session_factory,
    mocker,
) -> None:
    """§2.8: /character list shows 'Aldric' in the response embed."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "list")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    call_kwargs = interaction.response.send_message.call_args.kwargs
    embed = call_kwargs.get("embed")
    assert embed is not None
    # At least one embed field should contain "Aldric".
    field_names = [field.name for field in embed.fields]
    assert any("Aldric" in name for name in field_names)


@pytest.mark.asyncio
async def test_2_09_character_view_sends_response(
    int_session_factory,
    mocker,
) -> None:
    """§2.9: /character view sends a response (paginated embed)."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_2_10_wizard_creates_mira(
    int_session_factory,
    mocker,
) -> None:
    """§2.10: Wizard completion creates 'Mira' as Wizard level 1 for Player A."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )

    wizard_state = WizardState(
        user_discord_id=PLAYER_A_ID,
        guild_discord_id=GUILD_ID,
        guild_name="Integration Test Server",
        name="Mira",
        classes_and_levels=[(CharacterClass.WIZARD, 1)],
    )

    interaction = make_e2e_interaction(mocker, PLAYER_A_ID, username="PlayerA")
    interaction.response.edit_message = mocker.AsyncMock()

    await _finish_wizard(wizard_state, interaction)

    verify_session = int_session_factory()
    try:
        mira = verify_session.query(Character).filter_by(name="Mira").first()
        assert mira is not None, "Mira was not created in the DB"
        wizard_class_level = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=mira.id, class_name="Wizard")
            .first()
        )
        assert wizard_class_level is not None, (
            "Wizard ClassLevel row not found for Mira"
        )
        assert wizard_class_level.level == 1
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_2_11_character_list_shows_aldric_and_mira(
    int_session_factory,
    mocker,
) -> None:
    """§2.11: /character list shows both 'Aldric' and 'Mira'."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "list")
    await callback(interaction)

    call_kwargs = interaction.response.send_message.call_args.kwargs
    embed = call_kwargs.get("embed")
    assert embed is not None
    field_names = [field.name for field in embed.fields]
    # Both characters must appear.
    assert any("Aldric" in name for name in field_names), "Aldric not found in list"
    assert any("Mira" in name for name in field_names), "Mira not found in list"


@pytest.mark.asyncio
async def test_2_12_switch_to_mira_makes_mira_active(
    int_session_factory,
    mocker,
) -> None:
    """§2.12: /character switch name:Mira — Mira is active, Aldric is not."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "switch")
    await callback(interaction, name="Mira")

    verify_session = int_session_factory()
    try:
        mira = verify_session.query(Character).filter_by(name="Mira").first()
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        assert mira.is_active is True, "Mira should be active after switch"
        assert aldric.is_active is False, (
            "Aldric should be inactive after switch to Mira"
        )
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_2_13_switch_back_to_aldric_makes_aldric_active(
    int_session_factory,
    mocker,
) -> None:
    """§2.13: /character switch name:Aldric — Aldric is active again."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "switch")
    await callback(interaction, name="Aldric")

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        mira = verify_session.query(Character).filter_by(name="Mira").first()
        assert aldric.is_active is True, "Aldric should be active after switch back"
        assert mira.is_active is False, "Mira should be inactive after switch to Aldric"
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_2_14_character_create_sends_ephemeral_response(
    int_session_factory,
    mocker,
) -> None:
    """§2.14: /character create sends an ephemeral response (wizard hub)."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "create")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# Section 3: Character Stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_3_01_set_stats_persists_all_stats(
    int_session_factory,
    mocker,
) -> None:
    """§3.1: /character stats sets all six ability scores on Aldric.

    Verifies that all stat values are persisted and max_hp is recalculated.
    Fighter level 3 with CON 15 (+2 mod):
        Level 1: 10 + 2 = 12, Levels 2–3: 2 × (6 + 2) = 16 → total 28.
    """
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "stats")
    await callback(
        interaction,
        strength=16,
        dexterity=14,
        constitution=15,
        intelligence=10,
        wisdom=12,
        charisma=8,
    )

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        assert aldric.strength == 16
        assert aldric.dexterity == 14
        assert aldric.constitution == 15
        assert aldric.intelligence == 10
        assert aldric.wisdom == 12
        assert aldric.charisma == 8
        # Fighter 3 with CON +2: level 1 max die (10) + 2*(6+2) = 12 + 16 = 28.
        assert aldric.max_hp == 28
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_3_02_character_view_sends_response_after_stats(
    int_session_factory,
    mocker,
) -> None:
    """§3.2: /character view sends a response after stats are set."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_3_03_set_ac_persists_ac(
    int_session_factory,
    mocker,
) -> None:
    """§3.3: /character ac ac:17 — AC is persisted to 17 in the DB."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "ac")
    await callback(interaction, ac=17)

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        assert aldric.ac == 17
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_3_04_character_view_sends_response_after_ac(
    int_session_factory,
    mocker,
) -> None:
    """§3.4: /character view sends a response after AC is set."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_3_05_partial_stat_update_only_changes_strength(
    int_session_factory,
    mocker,
) -> None:
    """§3.5: /character stats strength:18 updates only strength; dexterity stays 14."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "stats")
    await callback(interaction, strength=18)

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        assert aldric.strength == 18, "Strength should have been updated to 18"
        assert aldric.dexterity == 14, "Dexterity should remain unchanged at 14"
        assert aldric.constitution == 15, "Constitution should remain unchanged at 15"
    finally:
        verify_session.close()


# ---------------------------------------------------------------------------
# Section 4: Saves & Skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4_01_character_saves_sends_ephemeral_view(
    int_session_factory,
    mocker,
) -> None:
    """§4.1: /character saves sends an ephemeral response with toggle buttons."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "saves")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    call_kwargs = interaction.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True
    assert call_kwargs.get("view") is not None


@pytest.mark.asyncio
async def test_4_03_skill_athletics_proficient_creates_row(
    int_session_factory,
    mocker,
) -> None:
    """§4.3: /character skill skill:Athletics status:Proficient — creates CharacterSkill row."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "skill")
    await callback(interaction, skill="Athletics", status="proficient")

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        athletics_skill = (
            verify_session.query(CharacterSkill)
            .filter_by(character_id=aldric.id, skill_name="Athletics")
            .first()
        )
        assert athletics_skill is not None, "Athletics CharacterSkill row not found"
        assert athletics_skill.proficiency == SkillProficiencyStatus.PROFICIENT
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_4_04_skill_perception_expertise_creates_row(
    int_session_factory,
    mocker,
) -> None:
    """§4.4: /character skill skill:Perception status:Expertise — creates CharacterSkill row."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "skill")
    await callback(interaction, skill="Perception", status="expertise")

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        perception_skill = (
            verify_session.query(CharacterSkill)
            .filter_by(character_id=aldric.id, skill_name="Perception")
            .first()
        )
        assert perception_skill is not None, "Perception CharacterSkill row not found"
        assert perception_skill.proficiency == SkillProficiencyStatus.EXPERTISE
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_4_05_skill_stealth_jack_of_all_trades_creates_row(
    int_session_factory,
    mocker,
) -> None:
    """§4.5: /character skill skill:Stealth status:Jack_Of_All_Trades — creates CharacterSkill row."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "skill")
    await callback(interaction, skill="Stealth", status="jack_of_all_trades")

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        stealth_skill = (
            verify_session.query(CharacterSkill)
            .filter_by(character_id=aldric.id, skill_name="Stealth")
            .first()
        )
        assert stealth_skill is not None, "Stealth CharacterSkill row not found"
        assert stealth_skill.proficiency == SkillProficiencyStatus.JACK_OF_ALL_TRADES
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_4_06_character_view_sends_response_after_skills(
    int_session_factory,
    mocker,
) -> None:
    """§4.6: /character view sends a response after skills are set."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_4_07_character_view_sends_response_second_call(
    int_session_factory,
    mocker,
) -> None:
    """§4.7: /character view sends a response on a second call (re-verify)."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Section 5: Multi-Class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5_01_class_add_rogue_creates_class_level_row(
    int_session_factory,
    mocker,
) -> None:
    """§5.1: /character class_add class:Rogue level:2 — ClassLevel row created, total level 5."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "class_add")
    await callback(interaction, character_class="Rogue", level=2)

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        rogue_class_level = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Rogue")
            .first()
        )
        assert rogue_class_level is not None, "Rogue ClassLevel row not found"
        assert rogue_class_level.level == 2
        # Fighter 3 + Rogue 2 = total level 5.
        assert aldric.level == 5, f"Expected total level 5, got {aldric.level}"
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_5_02_character_view_sends_response_after_multiclass(
    int_session_factory,
    mocker,
) -> None:
    """§5.2: /character view sends a response after multiclassing."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "view")
    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_5_03_class_add_barbarian_16_exceeds_cap_and_db_unchanged(
    int_session_factory,
    mocker,
) -> None:
    """§5.3: /character class_add class:Barbarian level:16 — error; total level still 5."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "class_add")
    await callback(interaction, character_class="Barbarian", level=16)

    # Command should have responded with an ephemeral error.
    call_kwargs = interaction.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True

    # DB must be unchanged — Aldric should still be at level 5 with no Barbarian row.
    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        barbarian_row = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Barbarian")
            .first()
        )
        assert barbarian_row is None, "Barbarian ClassLevel row should not exist"
        assert aldric.level == 5, f"Total level should still be 5, got {aldric.level}"
    finally:
        verify_session.close()


@pytest.mark.asyncio
async def test_5_04_class_remove_rogue_deletes_class_level_row(
    int_session_factory,
    mocker,
) -> None:
    """§5.4: /character class_remove class:Rogue — Rogue row deleted, total level back to 3."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "class_remove")
    await callback(interaction, character_class="Rogue")

    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        rogue_row = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Rogue")
            .first()
        )
        assert rogue_row is None, "Rogue ClassLevel row should have been deleted"
        assert aldric.level == 3, f"Total level should be back to 3, got {aldric.level}"
    finally:
        verify_session.close()


@pytest.mark.xfail(
    strict=True,
    reason="Implementation does not yet guard against removing the last class (§5.5).",
)
@pytest.mark.asyncio
async def test_5_05_class_remove_fighter_last_class_returns_error(
    int_session_factory,
    mocker,
) -> None:
    """§5.5: /character class_remove class:Fighter — error; can't remove the only class.

    NOTE: This test documents the desired behavior per the E2E spec. The current
    implementation does not guard against removing the last class. This test will
    fail until the guard is added to character_class_remove in character_commands.py.
    """
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.character_commands",
        "commands.wizard.completion",
    )
    bot = make_bot()
    register_character_commands(bot)
    interaction = make_e2e_interaction(mocker, PLAYER_A_ID)

    callback = get_callback(bot, "character", "class_remove")
    await callback(interaction, character_class="Fighter")

    # Must respond with an ephemeral error — not a success message.
    call_kwargs = interaction.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True

    # Fighter ClassLevel row must still exist — the class was NOT removed.
    verify_session = int_session_factory()
    try:
        aldric = verify_session.query(Character).filter_by(name="Aldric").first()
        fighter_row = (
            verify_session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Fighter")
            .first()
        )
        assert fighter_row is not None, (
            "Fighter ClassLevel row should NOT have been deleted"
        )
        assert aldric.level == 3, f"Total level should still be 3, got {aldric.level}"
    finally:
        verify_session.close()


def test_5_06_restore_fighter_class_after_xfail(
    int_session_factory: sessionmaker,
) -> None:
    """Ensure Aldric has Fighter 3 regardless of test_5_05 outcome.

    Because test_5_05 is xfail (implementation missing the guard), the
    class_remove command may actually delete Fighter.  This test restores
    the row so subsequent integration files start from a clean state.
    """
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name="Aldric").first()
        assert aldric is not None, "Aldric must exist before this cleanup step"
        fighter_row = (
            session.query(ClassLevel)
            .filter_by(character_id=aldric.id, class_name="Fighter")
            .first()
        )
        if not fighter_row:
            session.add(
                ClassLevel(character_id=aldric.id, class_name="Fighter", level=3)
            )
            session.commit()
    finally:
        session.close()

    verify = int_session_factory()
    try:
        aldric = verify.query(Character).filter_by(name="Aldric").first()
        assert aldric.level == 3, (
            f"Aldric level must be 3 after restore, got {aldric.level}"
        )
    finally:
        verify.close()
