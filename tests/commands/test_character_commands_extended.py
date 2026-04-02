"""Extended tests for commands/character_commands.py covering previously untested paths.

DO NOT duplicate tests from test_character_commands.py or test_character_wizard.py.
"""

import pytest
import discord
from discord import app_commands

from models import (
    Character,
    CharacterSkill,
    ClassLevel,
    Encounter,
    EncounterTurn,
    Attack,
)
from enums.skill_proficiency_status import SkillProficiencyStatus
from enums.encounter_status import EncounterStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback
from commands.character_commands import (
    _build_sheet_page1,
    _build_sheet_page2,
    _build_sheet_page3,
    CharacterSheetView,
    CharacterSavesEditView,
    _SaveEditToggleButton,
    _SaveChangesButton,
    _ConfirmCharacterDeleteView,
)
from utils.strings import Strings


# ---------------------------------------------------------------------------
# _build_sheet_page1 — stats NOT set returns early
# ---------------------------------------------------------------------------


async def test_build_sheet_page1_no_stats_returns_no_stats_field(
    sample_character_no_stats,
):
    """When no stats are set, page 1 should contain the CHAR_SHEET_NO_STATS message."""
    embed = _build_sheet_page1(sample_character_no_stats)

    field_values = [f.value for f in embed.fields]
    assert any(Strings.CHAR_SHEET_NO_STATS in v for v in field_values)


async def test_build_sheet_page1_no_stats_returns_early_without_stat_lines(
    sample_character_no_stats,
):
    """When no stats are set, page 1 should NOT contain STR/DEX/CON stat lines."""
    embed = _build_sheet_page1(sample_character_no_stats)

    combined = " ".join(f.value for f in embed.fields)
    assert "STR" not in combined
    assert "DEX" not in combined


# ---------------------------------------------------------------------------
# _build_sheet_page2 — expertise and jack_of_all_trades marks
# ---------------------------------------------------------------------------


async def test_build_sheet_page2_expertise_shows_expertise_mark(
    sample_character, db_session
):
    """A skill with EXPERTISE proficiency must display the ◉ mark."""
    db_session.add(
        CharacterSkill(
            character_id=sample_character.id,
            skill_name="Perception",
            proficiency=SkillProficiencyStatus.EXPERTISE,
        )
    )
    db_session.commit()
    db_session.refresh(sample_character)

    embed = _build_sheet_page2(sample_character)

    combined = " ".join(f.value for f in embed.fields)
    assert "◉" in combined


async def test_build_sheet_page2_jack_of_all_trades_shows_jack_mark(
    sample_character, db_session
):
    """A skill with JACK_OF_ALL_TRADES proficiency must display the ◗ mark."""
    db_session.add(
        CharacterSkill(
            character_id=sample_character.id,
            skill_name="Stealth",
            proficiency=SkillProficiencyStatus.JACK_OF_ALL_TRADES,
        )
    )
    db_session.commit()
    db_session.refresh(sample_character)

    embed = _build_sheet_page2(sample_character)

    combined = " ".join(f.value for f in embed.fields)
    assert "◗" in combined


# ---------------------------------------------------------------------------
# _build_sheet_page3 — with attacks
# ---------------------------------------------------------------------------


async def test_build_sheet_page3_with_attacks_shows_attack_names(
    sample_character, db_session
):
    """Page 3 should list each attack's name when the character has attacks."""
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=5,
            damage_formula="1d8+3",
        )
    )
    db_session.commit()
    db_session.refresh(sample_character)

    embed = _build_sheet_page3(sample_character)

    field_names = [f.name for f in embed.fields]
    assert "Longsword" in field_names


async def test_build_sheet_page3_with_attacks_shows_hit_modifier_and_damage(
    sample_character, db_session
):
    """Page 3 fields should include the hit modifier and damage formula."""
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Shortsword",
            hit_modifier=4,
            damage_formula="1d6+2",
        )
    )
    db_session.commit()
    db_session.refresh(sample_character)

    embed = _build_sheet_page3(sample_character)

    attack_field = next(f for f in embed.fields if f.name == "Shortsword")
    assert "+4" in attack_field.value
    assert "1d6+2" in attack_field.value


# ---------------------------------------------------------------------------
# CharacterSheetView.on_timeout
# ---------------------------------------------------------------------------


async def test_character_sheet_view_on_timeout_disables_all_buttons(
    sample_character, mocker
):
    """on_timeout should set disabled=True on every child button."""
    view = CharacterSheetView(owner_id=111, char_id=sample_character.id)
    view.message = mocker.AsyncMock()

    await view.on_timeout()

    for item in view.children:
        assert item.disabled is True  # type: ignore[union-attr]


async def test_character_sheet_view_on_timeout_with_message_calls_edit(
    sample_character, mocker
):
    """on_timeout should call message.edit when self.message is set."""
    view = CharacterSheetView(owner_id=111, char_id=sample_character.id)
    view.message = mocker.AsyncMock()

    await view.on_timeout()

    view.message.edit.assert_called_once()


async def test_character_sheet_view_on_timeout_no_message_does_not_edit(
    sample_character, mocker
):
    """on_timeout should skip the edit call entirely when self.message is None."""
    view = CharacterSheetView(owner_id=111, char_id=sample_character.id)
    view.message = None

    await view.on_timeout()

    # No message object means nothing to edit — the loop should still have run
    # and disabled all buttons, but no network call should have been attempted.
    for item in view.children:
        assert item.disabled is True  # type: ignore[union-attr]


async def test_character_sheet_view_on_timeout_swallows_http_exception(
    sample_character, mocker
):
    """on_timeout should silently catch discord.HTTPException on message.edit."""
    view = CharacterSheetView(owner_id=111, char_id=sample_character.id)
    mock_message = mocker.AsyncMock()
    mock_message.edit.side_effect = discord.HTTPException(
        mocker.MagicMock(), "some error"
    )
    view.message = mock_message

    # Should not raise even though edit raises
    await view.on_timeout()


# ---------------------------------------------------------------------------
# _CharacterSheetPageButton.callback — character not found
# ---------------------------------------------------------------------------


async def test_character_sheet_page_button_callback_char_deleted(
    char_bot, sample_character, db_session, interaction, mocker
):
    """When the character has been deleted, the page button should edit the message
    with ACTIVE_CHARACTER_NOT_FOUND and remove the view."""
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")

    # Delete the character from the DB before clicking a button
    char = db_session.get(Character, sample_character.id)
    db_session.delete(char)
    db_session.commit()

    stats_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Stats"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = interaction.user.id
    btn_interaction.response = mocker.AsyncMock()

    await stats_btn.callback(btn_interaction)

    btn_interaction.response.edit_message.assert_called_once()
    call_kwargs = btn_interaction.response.edit_message.call_args.kwargs
    assert call_kwargs.get("content") == Strings.ACTIVE_CHARACTER_NOT_FOUND
    assert call_kwargs.get("view") is None


# ---------------------------------------------------------------------------
# _SaveEditToggleButton.callback — toggles the save proficiency
# ---------------------------------------------------------------------------


async def test_save_edit_toggle_button_false_to_true(sample_character, mocker):
    """Clicking a toggle button on a currently-False save should flip it to True."""
    view = CharacterSavesEditView(
        char_id=sample_character.id,
        char_name=sample_character.name,
        current_saves={
            "strength": False,
            "dexterity": False,
            "constitution": False,
            "intelligence": False,
            "wisdom": False,
            "charisma": False,
        },
    )
    # Grab the Strength toggle button
    toggle_btn = next(
        item
        for item in view.children
        if isinstance(item, _SaveEditToggleButton) and item.stat == "strength"
    )

    mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
    mock_interaction.response = mocker.AsyncMock()

    await toggle_btn.callback(mock_interaction)

    assert view.saves["strength"] is True


async def test_save_edit_toggle_button_true_to_false(sample_character, mocker):
    """Clicking a toggle button on a currently-True save should flip it to False."""
    view = CharacterSavesEditView(
        char_id=sample_character.id,
        char_name=sample_character.name,
        current_saves={
            "strength": True,
            "dexterity": False,
            "constitution": False,
            "intelligence": False,
            "wisdom": False,
            "charisma": False,
        },
    )
    toggle_btn = next(
        item
        for item in view.children
        if isinstance(item, _SaveEditToggleButton) and item.stat == "strength"
    )

    mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
    mock_interaction.response = mocker.AsyncMock()

    await toggle_btn.callback(mock_interaction)

    assert view.saves["strength"] is False


# ---------------------------------------------------------------------------
# CharacterSavesEditView._refresh
# ---------------------------------------------------------------------------


async def test_saves_edit_view_refresh_calls_edit_message(sample_character, mocker):
    """_refresh should call interaction.response.edit_message with the rebuilt embed and view."""
    view = CharacterSavesEditView(
        char_id=sample_character.id,
        char_name=sample_character.name,
        current_saves={
            "strength": False,
            "dexterity": False,
            "constitution": False,
            "intelligence": False,
            "wisdom": False,
            "charisma": False,
        },
    )
    mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
    mock_interaction.response = mocker.AsyncMock()

    await view._refresh(mock_interaction)

    mock_interaction.response.edit_message.assert_called_once()
    call_kwargs = mock_interaction.response.edit_message.call_args.kwargs
    assert isinstance(call_kwargs.get("embed"), discord.Embed)
    assert call_kwargs.get("view") is view


async def test_saves_edit_view_refresh_reflects_updated_state(sample_character, mocker):
    """_refresh rebuilds buttons using the mutated saves dict, so a toggled save
    changes the corresponding button's style from secondary to success."""
    view = CharacterSavesEditView(
        char_id=sample_character.id,
        char_name=sample_character.name,
        current_saves={
            "strength": False,
            "dexterity": False,
            "constitution": False,
            "intelligence": False,
            "wisdom": False,
            "charisma": False,
        },
    )

    # Mutate state directly to simulate a toggle having fired
    view.saves["strength"] = True

    mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
    mock_interaction.response = mocker.AsyncMock()

    await view._refresh(mock_interaction)

    # After refresh, the Strength toggle button should now be success (green)
    str_btn = next(
        item
        for item in view.children
        if isinstance(item, _SaveEditToggleButton) and item.stat == "strength"
    )
    assert str_btn.style == discord.ButtonStyle.success


# ---------------------------------------------------------------------------
# _SaveChangesButton.callback — character not found path
# ---------------------------------------------------------------------------


async def test_save_changes_button_char_deleted(
    sample_character, db_session, mocker, session_factory
):
    """If the character no longer exists, save-changes should edit with ERROR_CHAR_NO_LONGER_EXISTS."""
    # Patch SessionLocal so the button uses our test DB
    import commands.character_commands as char_cmds

    original = char_cmds.SessionLocal
    char_cmds.SessionLocal = session_factory
    try:
        view = CharacterSavesEditView(
            char_id=sample_character.id,
            char_name=sample_character.name,
            current_saves={
                "strength": False,
                "dexterity": False,
                "constitution": False,
                "intelligence": False,
                "wisdom": False,
                "charisma": False,
            },
        )
        save_btn = next(
            item for item in view.children if isinstance(item, _SaveChangesButton)
        )

        # Delete the character before the button is clicked
        char = db_session.get(Character, sample_character.id)
        db_session.delete(char)
        db_session.commit()

        mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
        mock_interaction.response = mocker.AsyncMock()

        await save_btn.callback(mock_interaction)

        mock_interaction.response.edit_message.assert_called_once()
        call_kwargs = mock_interaction.response.edit_message.call_args.kwargs
        assert call_kwargs.get("content") == Strings.ERROR_CHAR_NO_LONGER_EXISTS
        assert call_kwargs.get("view") is None
    finally:
        char_cmds.SessionLocal = original


# ---------------------------------------------------------------------------
# _ConfirmCharacterDeleteView.confirm — character no longer exists
# ---------------------------------------------------------------------------


async def test_confirm_delete_view_char_already_gone(
    sample_character, db_session, mocker, session_factory
):
    """If the character is gone when confirm is clicked, edit with ERROR_CHAR_NO_LONGER_EXISTS."""
    import commands.character_commands as char_cmds

    original = char_cmds.SessionLocal
    char_cmds.SessionLocal = session_factory
    try:
        view = _ConfirmCharacterDeleteView(
            char_id=sample_character.id, char_name=sample_character.name
        )
        confirm_btn = next(
            item for item in view.children if getattr(item, "label", "") == "Delete"
        )

        # Remove the character before clicking confirm
        char = db_session.get(Character, sample_character.id)
        db_session.delete(char)
        db_session.commit()

        mock_interaction = mocker.AsyncMock(spec=discord.Interaction)
        mock_interaction.response = mocker.AsyncMock()

        await confirm_btn.callback(mock_interaction)

        mock_interaction.response.edit_message.assert_called_once()
        call_kwargs = mock_interaction.response.edit_message.call_args.kwargs
        assert call_kwargs.get("content") == Strings.ERROR_CHAR_NO_LONGER_EXISTS
        assert call_kwargs.get("view") is None
    finally:
        char_cmds.SessionLocal = original


# ---------------------------------------------------------------------------
# Delete confirm — active encounter turn index edge cases
# ---------------------------------------------------------------------------


async def test_delete_confirm_only_character_in_encounter_sets_turn_index_to_zero(
    mocker, char_bot, db_session, sample_character, sample_active_party, session_factory
):
    """When the deleted character is the ONLY turn in the encounter,
    current_turn_index should be reset to 0."""
    encounter = Encounter(
        name="Solo Battle",
        party_id=sample_active_party.id,
        server_id=sample_active_party.server_id,
        status=EncounterStatus.ACTIVE,
        current_turn_index=0,
        round_number=1,
    )
    db_session.add(encounter)
    db_session.flush()
    char_turn = EncounterTurn(
        encounter_id=encounter.id,
        character_id=sample_character.id,
        initiative_roll=15,
        order_position=0,
    )
    db_session.add(char_turn)
    db_session.commit()
    encounter_id = encounter.id

    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()

    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    updated_encounter = verify.get(Encounter, encounter_id)
    assert updated_encounter.current_turn_index == 0
    verify.close()


async def test_delete_confirm_earlier_turn_decrements_current_turn_index(
    mocker,
    char_bot,
    db_session,
    sample_character,
    sample_active_party,
    sample_user,
    sample_server,
    session_factory,
):
    """Deleting a turn at index LESS THAN current_turn_index should decrement the index."""
    # Create a second character to be the "other" turn
    second_char = Character(
        name="Beren",
        user=sample_user,
        server=sample_server,
        is_active=False,
    )
    db_session.add(second_char)
    db_session.flush()

    encounter = Encounter(
        name="Two-Turn Battle",
        party_id=sample_active_party.id,
        server_id=sample_active_party.server_id,
        status=EncounterStatus.ACTIVE,
        current_turn_index=1,  # currently Beren's turn
        round_number=1,
    )
    db_session.add(encounter)
    db_session.flush()

    # Aldric at position 0, Beren at position 1; we are on Beren's turn (index 1)
    aldric_turn = EncounterTurn(
        encounter_id=encounter.id,
        character_id=sample_character.id,
        initiative_roll=20,
        order_position=0,
    )
    beren_turn = EncounterTurn(
        encounter_id=encounter.id,
        character_id=second_char.id,
        initiative_roll=10,
        order_position=1,
    )
    db_session.add_all([aldric_turn, beren_turn])
    db_session.commit()
    encounter_id = encounter.id

    interaction = make_interaction(mocker)
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")  # delete position 0 while index is 1

    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()

    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    updated_encounter = verify.get(Encounter, encounter_id)
    # Index was 1, deleted_index was 0 (< current), so index should now be 0
    assert updated_encounter.current_turn_index == 0
    verify.close()


# ---------------------------------------------------------------------------
# Autocomplete functions
# ---------------------------------------------------------------------------


async def test_character_view_autocomplete_returns_own_characters(
    char_bot, sample_character, interaction
):
    """character_view_autocomplete should include the user's own characters."""
    view_cmd = char_bot.tree.get_command("character").get_command("view")
    autocomplete_fn = view_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    names = [c.value for c in choices]
    assert "Aldric" in names


async def test_character_view_autocomplete_filters_by_current(
    char_bot, sample_character, interaction
):
    """character_view_autocomplete should filter by the current partial input."""
    view_cmd = char_bot.tree.get_command("character").get_command("view")
    autocomplete_fn = view_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="Xyz")
    assert choices == []


async def test_character_view_autocomplete_includes_party_members(
    char_bot,
    sample_character,
    sample_active_party,
    db_session,
    sample_server,
    interaction,
):
    """character_view_autocomplete should label party characters with '(party)'."""
    from models import User as U

    other_user = U(discord_id="555")
    db_session.add(other_user)
    db_session.flush()
    party_char = Character(
        name="Zara", user=other_user, server=sample_server, is_active=True
    )
    db_session.add(party_char)
    db_session.flush()
    sample_active_party.characters.append(party_char)
    db_session.commit()

    view_cmd = char_bot.tree.get_command("character").get_command("view")
    autocomplete_fn = view_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    choice_names = [c.name for c in choices]
    assert "Zara (party)" in choice_names


async def test_character_view_autocomplete_no_duplicate_for_own_in_party(
    char_bot, sample_character, sample_active_party, db_session, interaction
):
    """Own character already in party list should not appear twice."""
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    view_cmd = char_bot.tree.get_command("character").get_command("view")
    autocomplete_fn = view_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="Aldric")
    aldric_choices = [c for c in choices if "Aldric" in c.name]
    # Should appear exactly once (as own character, not with "(party)" suffix)
    assert len(aldric_choices) == 1
    assert aldric_choices[0].name == "Aldric"


async def test_character_switch_autocomplete_returns_own_characters(
    char_bot, sample_character, interaction
):
    """character_switch_autocomplete should return choices for the user's own characters."""
    switch_cmd = char_bot.tree.get_command("character").get_command("switch")
    autocomplete_fn = switch_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    names = [c.value for c in choices]
    assert "Aldric" in names


async def test_character_switch_autocomplete_filters_by_current(
    char_bot, sample_character, interaction
):
    """character_switch_autocomplete should filter results by the partial input."""
    switch_cmd = char_bot.tree.get_command("character").get_command("switch")
    autocomplete_fn = switch_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="Xyz")
    assert choices == []


async def test_character_delete_autocomplete_returns_own_characters(
    char_bot, sample_character, interaction
):
    """character_delete_autocomplete should return choices for the user's own characters."""
    delete_cmd = char_bot.tree.get_command("character").get_command("delete")
    autocomplete_fn = delete_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    names = [c.value for c in choices]
    assert "Aldric" in names


async def test_character_delete_autocomplete_filters_by_current(
    char_bot, sample_character, interaction
):
    """character_delete_autocomplete should filter results by the partial input."""
    delete_cmd = char_bot.tree.get_command("character").get_command("delete")
    autocomplete_fn = delete_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="Xyz")
    assert choices == []


async def test_character_autocomplete_no_characters_returns_empty_list(
    char_bot, sample_user, sample_server, interaction
):
    """Autocomplete should return [] when the user has no characters on this server."""
    view_cmd = char_bot.tree.get_command("character").get_command("view")
    autocomplete_fn = view_cmd._params["name"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    assert choices == []


# ---------------------------------------------------------------------------
# /character stats — initiative_bonus update
# ---------------------------------------------------------------------------


async def test_set_stats_initiative_bonus_persists(
    char_bot, sample_character, interaction, session_factory
):
    """Providing initiative_bonus should persist it on the character."""
    cb = get_callback(char_bot, "character", "stats")
    await cb(interaction, initiative_bonus=3)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.initiative_bonus == 3
    verify.close()


# ---------------------------------------------------------------------------
# /character stats — constitution recalculation
# ---------------------------------------------------------------------------


async def test_set_stats_constitution_update_recalculates_max_hp(
    char_bot, sample_character, interaction, session_factory
):
    """Changing constitution on a character with class levels should recalculate max_hp."""
    cb = get_callback(char_bot, "character", "stats")
    # Change CON from 15 (+2) to 18 (+4); Fighter 5 HP:
    # Lvl1: 10+4=14, Lvls2-5: 4*(6+4)=40 → 54
    await cb(interaction, constitution=18)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.max_hp == 54
    verify.close()
