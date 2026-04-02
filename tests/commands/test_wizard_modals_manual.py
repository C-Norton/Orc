"""Tests for _WeaponSearchModal and _ManualSetupModal in commands/wizard/modals.py.

These are the two modal classes not covered by test_character_wizard.py.
"""

import pytest
import discord

from commands.wizard.modals import _WeaponSearchModal, _ManualSetupModal
from commands.wizard.state import WizardState
from enums.character_class import CharacterClass
from utils.strings import Strings
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_text_input(text_input: discord.ui.TextInput, value: str) -> None:
    """Inject a value into a TextInput as Discord would on modal submission."""
    text_input._value = value


def _make_weapons_view(mocker) -> discord.ui.View:
    """Return a minimal mock for _WeaponsWizardView."""
    view = mocker.Mock()
    view._build_embed = mocker.Mock(return_value=mocker.Mock(spec=discord.Embed))
    return view


def _make_weapon_state(
    user_id: int = 111,
    guild_id: int = 222,
) -> WizardState:
    """Return a WizardState suitable for weapon search tests."""
    return WizardState(
        user_discord_id=str(user_id),
        guild_discord_id=str(guild_id),
        guild_name="Test Server",
        name="Thalindra",
    )


# ---------------------------------------------------------------------------
# _WeaponSearchModal
# ---------------------------------------------------------------------------


async def test_weapon_search_modal_returns_results(mocker):
    """When fetch_weapons returns results the results view is displayed."""
    state = _make_weapon_state()
    weapons_view = _make_weapons_view(mocker)
    modal = _WeaponSearchModal(state, weapons_view)
    _set_text_input(modal.query_input, "longsword")

    fake_results = [{"name": "Longsword", "damage_dice": "1d8"}]
    mocker.patch("commands.wizard.modals.fetch_weapons", return_value=fake_results)

    # Mock _WeaponResultsView so we don't need real Discord buttons
    mock_results_view = mocker.Mock()
    mock_results_embed = mocker.Mock(spec=discord.Embed)
    mock_results_view._build_embed = mocker.Mock(return_value=mock_results_embed)
    mocker.patch(
        "commands.wizard.section_views._WeaponResultsView",
        return_value=mock_results_view,
    )

    interaction = make_interaction(mocker)
    interaction.edit_original_response = mocker.AsyncMock()

    await modal.on_submit(interaction)

    interaction.response.defer.assert_called_once()
    interaction.edit_original_response.assert_called_once_with(
        embed=mock_results_embed,
        view=mock_results_view,
    )


async def test_weapon_search_modal_no_results_returns_to_weapons_view(mocker):
    """When fetch_weapons returns an empty list the weapons view is restored."""
    state = _make_weapon_state()
    weapons_view = _make_weapons_view(mocker)
    modal = _WeaponSearchModal(state, weapons_view)
    _set_text_input(modal.query_input, "unobtanium blade")

    mocker.patch("commands.wizard.modals.fetch_weapons", return_value=[])

    interaction = make_interaction(mocker)
    interaction.edit_original_response = mocker.AsyncMock()

    await modal.on_submit(interaction)

    interaction.response.defer.assert_called_once()
    # Should call _build_embed with the failed query
    weapons_view._build_embed.assert_called_once_with(
        no_results_query="unobtanium blade"
    )
    interaction.edit_original_response.assert_called_once_with(
        embed=weapons_view._build_embed.return_value,
        view=weapons_view,
    )


async def test_weapon_search_modal_fetch_error_sends_ephemeral(mocker):
    """When fetch_weapons raises an exception an ephemeral error is sent."""
    state = _make_weapon_state()
    weapons_view = _make_weapons_view(mocker)
    modal = _WeaponSearchModal(state, weapons_view)
    _set_text_input(modal.query_input, "cursed item")

    mocker.patch(
        "commands.wizard.modals.fetch_weapons",
        side_effect=RuntimeError("API unavailable"),
    )

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once_with(
        Strings.WIZARD_WEAPONS_SEARCH_ERROR, ephemeral=True
    )


async def test_weapon_search_modal_query_is_stripped(mocker):
    """Whitespace around the query is stripped before the API call."""
    state = _make_weapon_state()
    weapons_view = _make_weapons_view(mocker)
    modal = _WeaponSearchModal(state, weapons_view)
    _set_text_input(modal.query_input, "  dagger  ")

    fetch_mock = mocker.patch(
        "commands.wizard.modals.fetch_weapons", return_value=[]
    )

    interaction = make_interaction(mocker)
    interaction.edit_original_response = mocker.AsyncMock()

    await modal.on_submit(interaction)

    fetch_mock.assert_called_once()
    called_query = fetch_mock.call_args[0][0]
    assert called_query == "dagger"


# ---------------------------------------------------------------------------
# _ManualSetupModal
# ---------------------------------------------------------------------------


async def test_manual_setup_modal_success_no_class(mocker, session_factory):
    """Submitting name only creates a character and edits the message."""
    mock_char = mocker.Mock()
    mock_char.id = 1
    mocker.patch(
        "commands.wizard.state.save_character_from_wizard",
        return_value=(mock_char, None),
    )
    mocker.patch("database.SessionLocal", new=session_factory)

    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Thalindra")
    _set_text_input(modal.class_input, "")
    _set_text_input(modal.level_input, "")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.edit_message.assert_called_once()
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert "Thalindra" in call_kwargs["content"]
    assert call_kwargs["embed"] is None
    assert call_kwargs["view"] is None


async def test_manual_setup_modal_success_with_class_and_level(
    mocker, session_factory
):
    """Submitting name + class + level creates a character with saving throws applied."""
    captured_state: list[WizardState] = []

    def _fake_save(state, interaction, db):
        captured_state.append(state)
        mock_char = mocker.Mock()
        mock_char.id = 1
        return mock_char, None

    mocker.patch("commands.wizard.state.save_character_from_wizard", side_effect=_fake_save)
    mocker.patch("database.SessionLocal", new=session_factory)

    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Gromash")
    _set_text_input(modal.class_input, "Fighter")
    _set_text_input(modal.level_input, "3")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.edit_message.assert_called_once()
    state = captured_state[0]
    assert state.name == "Gromash"
    assert len(state.classes_and_levels) == 1
    assert state.classes_and_levels[0] == (CharacterClass.FIGHTER, 3)
    # Saving throws should be auto-applied for the class
    assert any(state.saving_throws.values())


async def test_manual_setup_modal_empty_name_sends_error(mocker):
    """Submitting a blank name sends WIZARD_NAME_REQUIRED ephemerally."""
    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "   ")
    _set_text_input(modal.class_input, "")
    _set_text_input(modal.level_input, "")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.WIZARD_NAME_REQUIRED, ephemeral=True
    )
    interaction.response.edit_message.assert_not_called()


async def test_manual_setup_modal_invalid_class_sends_error(mocker):
    """Submitting an unrecognised class name sends WIZARD_CLASS_INVALID ephemerally."""
    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Zara")
    _set_text_input(modal.class_input, "Necromancer")
    _set_text_input(modal.level_input, "")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once()
    call_args = interaction.response.send_message.call_args
    sent_content = call_args[0][0]
    assert "Necromancer" in sent_content
    assert call_args.kwargs.get("ephemeral") is True


async def test_manual_setup_modal_non_numeric_level_sends_error(mocker):
    """A non-numeric level sends WIZARD_LEVEL_INVALID ephemerally."""
    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Zara")
    _set_text_input(modal.class_input, "Rogue")
    _set_text_input(modal.level_input, "abc")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.WIZARD_LEVEL_INVALID, ephemeral=True
    )


async def test_manual_setup_modal_level_out_of_range_sends_error(mocker):
    """A level outside 1–20 sends CHAR_LEVEL_LIMIT ephemerally."""
    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Zara")
    _set_text_input(modal.class_input, "Rogue")
    _set_text_input(modal.level_input, "21")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.CHAR_LEVEL_LIMIT, ephemeral=True
    )


async def test_manual_setup_modal_save_error_sends_error_message(mocker, session_factory):
    """When save_character_from_wizard returns an error string it is sent ephemerally."""
    mocker.patch(
        "commands.wizard.state.save_character_from_wizard",
        return_value=(None, "Character already exists."),
    )
    mocker.patch("database.SessionLocal", new=session_factory)

    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Duplicate")
    _set_text_input(modal.class_input, "")
    _set_text_input(modal.level_input, "")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        "Character already exists.", ephemeral=True
    )
    interaction.response.edit_message.assert_not_called()


async def test_manual_setup_modal_db_exception_sends_generic_error(
    mocker, session_factory
):
    """An unexpected DB exception rolls back and sends ERROR_GENERIC ephemerally."""
    mocker.patch(
        "commands.wizard.state.save_character_from_wizard",
        side_effect=RuntimeError("DB exploded"),
    )
    mocker.patch("database.SessionLocal", new=session_factory)

    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Borked")
    _set_text_input(modal.class_input, "")
    _set_text_input(modal.level_input, "")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.ERROR_GENERIC, ephemeral=True
    )
    interaction.response.edit_message.assert_not_called()


async def test_manual_setup_modal_level_zero_sends_error(mocker):
    """Level 0 is below the minimum and sends CHAR_LEVEL_LIMIT ephemerally."""
    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Lowbie")
    _set_text_input(modal.class_input, "Bard")
    _set_text_input(modal.level_input, "0")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_called_once_with(
        Strings.CHAR_LEVEL_LIMIT, ephemeral=True
    )


async def test_manual_setup_modal_class_input_case_insensitive(
    mocker, session_factory
):
    """Class input is title-cased before lookup so 'fighter' and 'FIGHTER' are valid."""
    captured_state: list[WizardState] = []

    def _fake_save(state, interaction, db):
        captured_state.append(state)
        mock_char = mocker.Mock()
        mock_char.id = 1
        return mock_char, None

    mocker.patch("commands.wizard.state.save_character_from_wizard", side_effect=_fake_save)
    mocker.patch("database.SessionLocal", new=session_factory)

    modal = _ManualSetupModal(
        user_discord_id="111",
        guild_discord_id="222",
        guild_name="Test Server",
    )
    _set_text_input(modal.name_input, "Grumble")
    _set_text_input(modal.class_input, "fighter")  # lowercase — should still work
    _set_text_input(modal.level_input, "1")

    interaction = make_interaction(mocker)

    await modal.on_submit(interaction)

    interaction.response.edit_message.assert_called_once()
    state = captured_state[0]
    assert state.classes_and_levels[0][0] == CharacterClass.FIGHTER
