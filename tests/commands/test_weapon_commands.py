"""Tests for /weapon search command and WeaponAddButton / WeaponSearchView.

/weapon search uses defer() + followup.send() with a WeaponSearchView.
Buttons in the view handle the import; no separate /weapon add command exists.
"""

import pytest
import discord
from types import SimpleNamespace

from models import Attack
from commands.weapon_commands import (
    WeaponAddButton,
    WeaponSearchView,
    WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS,
    _build_weapon_add_message,
    _import_weapon_to_character,
)
from utils.weapon_utils import WeaponHitModifier
from tests.commands.conftest import get_callback
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Sample weapon data matching the Open5e v2 API format
# ---------------------------------------------------------------------------

LONGSWORD_DATA = {
    "name": "Longsword",
    "damage_dice": "1d8",
    "damage_type": {"name": "Slashing"},
    "is_simple": False,
    "range": 0.0,
    "long_range": 0.0,
    "properties": [{"property": {"name": "Versatile", "desc": ""}, "detail": "1d10"}],
}

SHORTBOW_DATA = {
    "name": "Shortbow",
    "damage_dice": "1d6",
    "damage_type": {"name": "Piercing"},
    "is_simple": False,
    "range": 80.0,
    "long_range": 320.0,
    "properties": [],
}

DAGGER_DATA = {
    "name": "Dagger",
    "damage_dice": "1d4",
    "damage_type": {"name": "Piercing"},
    "is_simple": True,
    "range": 0.0,
    "long_range": 0.0,
    "properties": [
        {"property": {"name": "Finesse", "desc": ""}, "detail": ""},
        {"property": {"name": "Light", "desc": ""}, "detail": ""},
        {"property": {"name": "Thrown", "desc": ""}, "detail": ""},
    ],
}


# ---------------------------------------------------------------------------
# /weapon search — results
# ---------------------------------------------------------------------------


async def test_weapon_search_displays_numbered_results(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search shows numbered weapon results via followup."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    interaction.followup.send.assert_called_once()
    msg = interaction.followup.send.call_args.args[0]
    assert "Longsword" in msg
    assert "1." in msg


async def test_weapon_search_message_is_ephemeral(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search results are sent as an ephemeral message."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


async def test_weapon_search_sends_view_with_buttons(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search attaches a WeaponSearchView with one button per result."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA, SHORTBOW_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="sword")

    sent_view = interaction.followup.send.call_args.kwargs.get("view")
    assert isinstance(sent_view, WeaponSearchView)
    assert len(sent_view.children) == 2
    button_labels = [b.label for b in sent_view.children]
    assert "Longsword" in button_labels
    assert "Shortbow" in button_labels


async def test_weapon_search_stores_message_on_view(
    weapon_bot, sample_character, interaction, mocker
):
    """The message returned by followup.send is stored on the view for timeout editing."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    sent_view = interaction.followup.send.call_args.kwargs.get("view")
    # interaction.followup.send returns mock_message from the fixture
    assert sent_view.message is interaction.followup.send.return_value


async def test_weapon_search_no_results_returns_ephemeral_error(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search with no results returns an ephemeral error via followup."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="xyzzy_nonexistent")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert "xyzzy_nonexistent" in msg


async def test_weapon_search_no_character_returns_ephemeral_error(
    weapon_bot, sample_user, sample_server, interaction, mocker
):
    """/weapon search without an active character returns an ephemeral error."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


async def test_weapon_search_api_error_returns_ephemeral_error(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search propagates API failures as an ephemeral error."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(side_effect=Exception("Connection refused")),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


async def test_weapon_search_multiple_results_all_shown(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search displays all returned weapons with sequential indices."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA, SHORTBOW_DATA, DAGGER_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="weapon")

    msg = interaction.followup.send.call_args.args[0]
    assert "1." in msg
    assert "2." in msg
    assert "3." in msg
    assert "Longsword" in msg
    assert "Shortbow" in msg
    assert "Dagger" in msg


async def test_weapon_search_header_includes_ruleset(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search header shows the ruleset year used."""
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword", ruleset="2014")

    msg = interaction.followup.send.call_args.args[0]
    assert "2014" in msg


# ---------------------------------------------------------------------------
# WeaponAddButton — success paths
# ---------------------------------------------------------------------------


async def test_button_creates_attack_record(
    weapon_bot, sample_character, mocker, db_session, session_factory
):
    """Clicking the Add button creates an Attack record with all metadata."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    button = view.children[0]

    await button.callback(button_interaction)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.is_imported is True
    assert attack.damage_type == "Slashing"
    assert attack.weapon_category == "Martial"
    assert attack.two_handed_damage == "1d10"
    verify.close()


async def test_button_hit_modifier_melee_uses_strength(
    weapon_bot, sample_character, mocker, db_session, session_factory
):
    """Melee weapon button sets hit_modifier = STR mod + proficiency.

    Aldric: STR 16 (+3), level 5 (prof +3) → expected hit_modifier = +6.
    """
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])

    await view.children[0].callback(button_interaction)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack.hit_modifier == 6
    verify.close()


async def test_button_hit_modifier_ranged_uses_dexterity(
    weapon_bot, sample_character, mocker, db_session, session_factory
):
    """Ranged weapon button sets hit_modifier = DEX mod + proficiency.

    Aldric: DEX 14 (+2), level 5 (prof +3) → expected hit_modifier = +5.
    """
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([SHORTBOW_DATA])

    await view.children[0].callback(button_interaction)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Shortbow").first()
    assert attack.hit_modifier == 5
    verify.close()


async def test_button_damage_formula_set_from_damage_dice(
    weapon_bot, sample_character, mocker, db_session, session_factory
):
    """Button uses weapon's damage_dice field as the damage_formula."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])

    await view.children[0].callback(button_interaction)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack.damage_formula == "1d8"
    verify.close()


async def test_button_sends_public_confirmation(
    weapon_bot, sample_character, mocker, db_session
):
    """Button sends a public (non-ephemeral) confirmation via followup."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])

    await view.children[0].callback(button_interaction)

    button_interaction.followup.send.assert_called_once()
    kwargs = button_interaction.followup.send.call_args.kwargs
    assert kwargs.get("ephemeral") is not True


async def test_button_confirmation_contains_name_and_hit_modifier(
    weapon_bot, sample_character, mocker, db_session
):
    """Button confirmation message includes weapon name and computed modifier."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])

    await view.children[0].callback(button_interaction)

    msg = button_interaction.followup.send.call_args.args[0]
    assert "Longsword" in msg
    assert "+6" in msg  # Aldric: STR +3 + prof +3


async def test_button_disables_itself_on_success(
    weapon_bot, sample_character, mocker, db_session
):
    """After a successful import the clicked button is disabled and turns green."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    button = view.children[0]

    await button.callback(button_interaction)

    assert button.disabled is True
    assert button.style == discord.ButtonStyle.success


async def test_button_calls_edit_message_to_update_view(
    weapon_bot, sample_character, mocker, db_session
):
    """After success the button updates the original search message via edit_message."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])

    await view.children[0].callback(button_interaction)

    button_interaction.response.edit_message.assert_called_once_with(view=view)


# ---------------------------------------------------------------------------
# WeaponAddButton — upsert (update existing)
# ---------------------------------------------------------------------------


async def test_button_updates_existing_attack(
    weapon_bot, sample_character, mocker, db_session, session_factory
):
    """Button on a weapon already saved updates it rather than creating a duplicate."""
    existing = Attack(
        character_id=sample_character.id,
        name="Longsword",
        hit_modifier=2,
        damage_formula="1d8",
    )
    db_session.add(existing)
    db_session.commit()

    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    verify = session_factory()
    attacks = verify.query(Attack).filter_by(name="Longsword").all()
    assert len(attacks) == 1
    assert attacks[0].hit_modifier == 6
    assert attacks[0].is_imported is True
    verify.close()


async def test_button_update_message_uses_updated_header(
    weapon_bot, sample_character, mocker, db_session
):
    """Button on an existing attack uses the 'Updated' phrasing in confirmation."""
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=2,
            damage_formula="1d8",
        )
    )
    db_session.commit()

    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    msg = button_interaction.followup.send.call_args.args[0]
    assert "Updated" in msg


# ---------------------------------------------------------------------------
# WeaponAddButton — error paths
# ---------------------------------------------------------------------------


async def test_button_respects_attack_limit(
    mocker, weapon_bot, sample_character, db_session
):
    """Button is rejected when the character has reached the attack cap."""
    mocker.patch("commands.weapon_commands.MAX_ATTACKS_PER_CHARACTER", 1)
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Existing Attack",
            hit_modifier=0,
            damage_formula="1d4",
        )
    )
    db_session.commit()

    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    button_interaction.response.send_message.assert_called_once()
    kwargs = button_interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    msg = button_interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_button_attack_limit_does_not_block_update(
    mocker, weapon_bot, sample_character, db_session, session_factory
):
    """Updating an existing attack via button is allowed even when at the limit."""
    mocker.patch("commands.weapon_commands.MAX_ATTACKS_PER_CHARACTER", 1)
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=2,
            damage_formula="1d8",
        )
    )
    db_session.commit()

    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    # Should have called edit_message (success path), not send_message (error path)
    button_interaction.response.edit_message.assert_called_once()


async def test_button_no_character_returns_ephemeral_error(
    weapon_bot, sample_user, sample_server, mocker
):
    """Button without an active character returns an ephemeral error."""
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    button_interaction.response.send_message.assert_called_once()
    assert (
        button_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


async def test_button_character_no_stats_uses_zero_modifier(
    weapon_bot, sample_character_no_stats, mocker, db_session, session_factory
):
    """Button on a statless character defaults to modifier 0 + proficiency.

    No stats → all mods = 0, level 1 → prof +2, expected hit_modifier = +2.
    """
    button_interaction = make_interaction(mocker)
    view = WeaponSearchView([LONGSWORD_DATA])
    await view.children[0].callback(button_interaction)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.hit_modifier == 2
    verify.close()


# ---------------------------------------------------------------------------
# WeaponSearchView — timeout / GC behaviour
# ---------------------------------------------------------------------------


async def test_view_on_timeout_disables_all_buttons(mocker):
    """on_timeout disables every button in the view."""
    mock_message = mocker.AsyncMock()
    view = WeaponSearchView([LONGSWORD_DATA, SHORTBOW_DATA])
    view.message = mock_message

    await view.on_timeout()

    assert all(item.disabled for item in view.children)


async def test_view_on_timeout_edits_message(mocker):
    """on_timeout calls message.edit to reflect the expired state in Discord."""
    mock_message = mocker.AsyncMock()
    view = WeaponSearchView([LONGSWORD_DATA])
    view.message = mock_message

    await view.on_timeout()

    mock_message.edit.assert_called_once_with(view=view)


async def test_view_on_timeout_handles_missing_message_gracefully():
    """on_timeout does not raise when message is None (e.g. bot restart)."""
    view = WeaponSearchView([LONGSWORD_DATA])
    view.message = None
    await view.on_timeout()  # Should not raise


async def test_view_on_timeout_handles_not_found_gracefully(mocker):
    """on_timeout ignores discord.NotFound so a deleted message does not crash."""
    mock_message = mocker.AsyncMock()
    mock_message.edit.side_effect = discord.NotFound(mocker.Mock(), "Not Found")
    view = WeaponSearchView([LONGSWORD_DATA])
    view.message = mock_message

    await view.on_timeout()  # Should not raise


def test_view_timeout_matches_constant():
    """WeaponSearchView.timeout equals WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS."""
    view = WeaponSearchView([LONGSWORD_DATA])
    assert view.timeout == WEAPON_SEARCH_VIEW_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# _import_weapon_to_character
# ---------------------------------------------------------------------------


def test_import_weapon_creates_new_attack(sample_character, db_session):
    """_import_weapon_to_character creates an Attack and returns is_new=True."""
    is_new, hit_mod = _import_weapon_to_character(LONGSWORD_DATA, sample_character, db_session)
    db_session.commit()

    assert is_new is True
    attack = db_session.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.is_imported is True


def test_import_weapon_returns_false_for_existing(sample_character, db_session):
    """_import_weapon_to_character returns is_new=False when attack already exists."""
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=0,
            damage_formula="1d8",
        )
    )
    db_session.commit()

    is_new, _ = _import_weapon_to_character(LONGSWORD_DATA, sample_character, db_session)

    assert is_new is False


def test_import_weapon_updates_existing_record(sample_character, db_session):
    """_import_weapon_to_character overwrites the existing attack's fields on update."""
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=0,
            damage_formula="1d4",
        )
    )
    db_session.commit()

    _import_weapon_to_character(LONGSWORD_DATA, sample_character, db_session)
    db_session.commit()

    attack = db_session.query(Attack).filter_by(name="Longsword").first()
    assert attack.damage_formula == "1d8"
    assert attack.hit_modifier == 6  # Aldric STR+3 + prof+3


def test_import_weapon_returns_hit_modifier(sample_character, db_session):
    """_import_weapon_to_character returns a WeaponHitModifier with the correct total."""
    _, hit_mod = _import_weapon_to_character(LONGSWORD_DATA, sample_character, db_session)

    assert isinstance(hit_mod, WeaponHitModifier)
    assert hit_mod.total == 6  # Aldric STR+3 + prof+3


# ---------------------------------------------------------------------------
# _build_weapon_add_message
# ---------------------------------------------------------------------------


def _make_hit_mod(total: int = 6) -> WeaponHitModifier:
    return WeaponHitModifier(
        total=total, ability_name="STR", ability_modifier=3, proficiency_bonus=3
    )


def _make_char(name: str = "Aldric"):
    return SimpleNamespace(name=name)


def test_build_message_new_weapon_uses_added_header():
    """New weapon message contains 'Added' (not 'Updated')."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), True, _make_hit_mod())
    assert "Added" in msg
    assert "Updated" not in msg


def test_build_message_existing_weapon_uses_updated_header():
    """Updated weapon message contains 'Updated' (not 'Added')."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), False, _make_hit_mod())
    assert "Updated" in msg
    assert "Added" not in msg


def test_build_message_includes_weapon_name():
    """Confirmation message contains the weapon name."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), True, _make_hit_mod())
    assert "Longsword" in msg


def test_build_message_includes_hit_modifier():
    """Confirmation message contains the formatted hit modifier."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), True, _make_hit_mod(5))
    assert "+5" in msg


def test_build_message_includes_damage_dice_and_type():
    """Confirmation message contains damage dice and damage type."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), True, _make_hit_mod())
    assert "1d8" in msg
    assert "Slashing" in msg


def test_build_message_includes_versatile_suffix_when_present():
    """Confirmation message shows two-handed damage for Versatile weapons."""
    msg = _build_weapon_add_message(LONGSWORD_DATA, _make_char(), True, _make_hit_mod())
    assert "1d10" in msg
    assert "two-handed" in msg


def test_build_message_no_versatile_suffix_for_non_versatile():
    """Non-versatile weapons do not show a two-handed damage entry."""
    msg = _build_weapon_add_message(SHORTBOW_DATA, _make_char(), True, _make_hit_mod())
    assert "two-handed" not in msg


def test_build_message_includes_properties_when_present():
    """Confirmation message lists all weapon properties."""
    msg = _build_weapon_add_message(DAGGER_DATA, _make_char(), True, _make_hit_mod())
    assert "Finesse" in msg
    assert "Light" in msg
    assert "Thrown" in msg


def test_build_message_no_properties_line_when_empty():
    """Confirmation message has no Properties line when weapon has no properties."""
    msg = _build_weapon_add_message(SHORTBOW_DATA, _make_char(), True, _make_hit_mod())
    assert "Properties" not in msg
