"""Tests for /weapon search and /weapon add commands.

/weapon search uses defer() + followup.send().
/weapon add uses response.send_message() directly.
"""

import time

import pytest

import commands.weapon_commands as weapon_commands_module
from models import Attack
from tests.commands.conftest import get_callback


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
# Session helper utilities
# ---------------------------------------------------------------------------


def _set_session(
    user_id: str = "111",
    guild_id: str = "222",
    weapons: list | None = None,
    ttl_offset: float = 300,
) -> None:
    """Directly insert weapon results into the module-level session dict."""
    if weapons is None:
        weapons = [LONGSWORD_DATA]
    weapon_commands_module._weapon_search_sessions[(user_id, guild_id)] = (
        weapons,
        time.time() + ttl_offset,
    )


def _clear_sessions() -> None:
    """Clear all weapon search sessions between tests."""
    weapon_commands_module._weapon_search_sessions.clear()


# ---------------------------------------------------------------------------
# /weapon search — results
# ---------------------------------------------------------------------------


async def test_weapon_search_displays_numbered_results(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search shows numbered weapon results via followup."""
    _clear_sessions()
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
    _clear_sessions()
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="longsword")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


async def test_weapon_search_stores_results_in_session(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search stores results under the correct session key."""
    _clear_sessions()
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        mocker.AsyncMock(return_value=[LONGSWORD_DATA, DAGGER_DATA]),
    )

    cb = get_callback(weapon_bot, "weapon", "search")
    await cb(interaction, query="sword")

    session_key = (str(interaction.user.id), str(interaction.guild_id))
    assert session_key in weapon_commands_module._weapon_search_sessions
    stored_weapons, _ = weapon_commands_module._weapon_search_sessions[session_key]
    assert len(stored_weapons) == 2


async def test_weapon_search_no_results_returns_ephemeral_error(
    weapon_bot, sample_character, interaction, mocker
):
    """/weapon search with no results returns an ephemeral error via followup."""
    _clear_sessions()
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
    _clear_sessions()
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
    _clear_sessions()
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


# ---------------------------------------------------------------------------
# /weapon add — success paths
# ---------------------------------------------------------------------------


async def test_weapon_add_creates_attack_record(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add creates an Attack record with all metadata fields populated."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.is_imported is True
    assert attack.damage_type == "Slashing"
    assert attack.weapon_category == "Martial"
    assert attack.two_handed_damage == "1d10"
    verify.close()


async def test_weapon_add_hit_modifier_melee_uses_strength(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add sets hit_modifier = STR mod + proficiency for a melee weapon.

    Aldric: STR 16 (+3), level 5 (prof +3) → expected hit_modifier = +6.
    """
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.hit_modifier == 6
    verify.close()


async def test_weapon_add_hit_modifier_ranged_uses_dexterity(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add sets hit_modifier = DEX mod + proficiency for a ranged weapon.

    Aldric: DEX 14 (+2), level 5 (prof +3) → expected hit_modifier = +5.
    """
    _clear_sessions()
    _set_session(weapons=[SHORTBOW_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Shortbow").first()
    assert attack is not None
    assert attack.hit_modifier == 5
    verify.close()


async def test_weapon_add_damage_formula_set_from_damage_dice(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add uses the weapon's damage_dice field as the damage_formula."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack.damage_formula == "1d8"
    verify.close()


async def test_weapon_add_success_message_not_ephemeral(
    weapon_bot, sample_character, interaction, db_session
):
    """/weapon add success message is public (not ephemeral)."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_weapon_add_success_message_contains_name_and_hit_modifier(
    weapon_bot, sample_character, interaction, db_session
):
    """/weapon add success message includes the weapon name and computed hit modifier."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Longsword" in msg
    assert "+6" in msg  # Aldric: STR +3 + prof +3


async def test_weapon_add_second_result_selected_by_number(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add with number=2 imports the second weapon from search results."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA, DAGGER_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=2)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Dagger").first()
    assert attack is not None
    verify.close()


# ---------------------------------------------------------------------------
# /weapon add — upsert (update existing)
# ---------------------------------------------------------------------------


async def test_weapon_add_updates_existing_attack(
    weapon_bot, sample_character, interaction, db_session, session_factory
):
    """/weapon add on an already-saved attack updates it rather than creating a duplicate."""
    _clear_sessions()
    existing = Attack(
        character_id=sample_character.id,
        name="Longsword",
        hit_modifier=2,
        damage_formula="1d8",
    )
    db_session.add(existing)
    db_session.commit()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attacks = verify.query(Attack).filter_by(name="Longsword").all()
    assert len(attacks) == 1
    assert attacks[0].hit_modifier == 6
    assert attacks[0].is_imported is True
    verify.close()


async def test_weapon_add_update_message_uses_updated_header(
    weapon_bot, sample_character, interaction, db_session
):
    """/weapon add on an existing attack uses the 'Updated' phrasing."""
    _clear_sessions()
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Longsword",
            hit_modifier=2,
            damage_formula="1d8",
        )
    )
    db_session.commit()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Updated" in msg


# ---------------------------------------------------------------------------
# /weapon add — error paths
# ---------------------------------------------------------------------------


async def test_weapon_add_expired_session_shows_error(
    weapon_bot, sample_character, interaction
):
    """/weapon add with an expired session returns an ephemeral error."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA], ttl_offset=-1)  # already expired

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_weapon_add_no_session_shows_error(
    weapon_bot, sample_character, interaction
):
    """/weapon add without a prior search returns an ephemeral error."""
    _clear_sessions()

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_weapon_add_invalid_index_too_high_shows_error(
    weapon_bot, sample_character, interaction
):
    """/weapon add with an index beyond the result count returns an ephemeral error."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])  # only 1 result

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_weapon_add_invalid_index_zero_shows_error(
    weapon_bot, sample_character, interaction
):
    """/weapon add with index 0 (below the valid range) returns an ephemeral error."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_weapon_add_respects_attack_limit(
    mocker, weapon_bot, sample_character, interaction, db_session
):
    """/weapon add is rejected when the character has reached the attack cap."""
    _clear_sessions()
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
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_weapon_add_no_character_returns_ephemeral_error(
    weapon_bot, sample_user, sample_server, interaction
):
    """/weapon add without an active character returns an ephemeral error."""
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_weapon_add_attack_limit_does_not_block_update(
    mocker, weapon_bot, sample_character, interaction, db_session, session_factory
):
    """Updating an existing attack is allowed even when the character is at the limit."""
    _clear_sessions()
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
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


# ---------------------------------------------------------------------------
# /weapon add — character with no stats
# ---------------------------------------------------------------------------


async def test_weapon_add_character_no_stats_uses_zero_modifier(
    weapon_bot, sample_character_no_stats, interaction, db_session, session_factory
):
    """/weapon add with a statless character defaults to modifier 0 + proficiency.

    No stats → all mods = 0, level 1 → prof +2, expected hit_modifier = +2.
    """
    _clear_sessions()
    _set_session(weapons=[LONGSWORD_DATA])

    cb = get_callback(weapon_bot, "weapon", "add")
    await cb(interaction, number=1)

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.hit_modifier == 2  # 0 (no STR) + 2 (prof level 1)
    verify.close()
