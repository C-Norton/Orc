"""Unit tests for utils.weapon_utils — hit modifier calculation and data parsing.

These tests use SimpleNamespace to stand in for Character objects so no
database session is needed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from enums.ruleset_edition import RulesetEdition
from utils.weapon_utils import (
    WeaponHitModifier,
    calculate_weapon_hit_modifier,
    extract_two_handed_damage,
    fetch_weapons,
    format_weapon_result_line,
    get_property_names,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(strength: int = 10, dexterity: int = 10, level: int = 1):
    """Return a minimal character-like namespace for hit-modifier tests."""
    return SimpleNamespace(strength=strength, dexterity=dexterity, level=level)


def _prop(name: str, detail: str = "") -> dict:
    """Build a minimal Open5e property entry."""
    return {"property": {"name": name, "desc": ""}, "detail": detail}


# ---------------------------------------------------------------------------
# calculate_weapon_hit_modifier
# ---------------------------------------------------------------------------


def test_standard_melee_uses_strength_modifier():
    """Non-finesse melee weapon uses STR modifier + proficiency bonus.

    STR 16 → mod +3, level 5 → prof +3, expected total = +6.
    """
    character = _make_character(strength=16, dexterity=14, level=5)
    result = calculate_weapon_hit_modifier(character, [], range_normal=0)
    assert result.total == 6
    assert result.ability_name == "STR"
    assert result.ability_modifier == 3
    assert result.proficiency_bonus == 3


def test_ranged_weapon_uses_dexterity_modifier():
    """Ranged weapon (range_normal > 0) uses DEX modifier + proficiency bonus.

    DEX 14 → mod +2, level 1 → prof +2, expected total = +4.
    """
    character = _make_character(strength=16, dexterity=14, level=1)
    result = calculate_weapon_hit_modifier(character, [], range_normal=80)
    assert result.total == 4
    assert result.ability_name == "DEX"
    assert result.ability_modifier == 2


def test_finesse_weapon_uses_dex_when_dex_is_higher():
    """Finesse weapon chooses DEX when DEX modifier exceeds STR modifier.

    STR 10 → mod 0, DEX 18 → mod +4, level 5 → prof +3, expected total = +7.
    """
    character = _make_character(strength=10, dexterity=18, level=5)
    properties = [_prop("Finesse")]
    result = calculate_weapon_hit_modifier(character, properties, range_normal=0)
    assert result.total == 7
    assert result.ability_name == "DEX"
    assert result.ability_modifier == 4


def test_finesse_weapon_uses_str_when_str_is_higher():
    """Finesse weapon chooses STR when STR modifier exceeds DEX modifier.

    STR 18 → mod +4, DEX 10 → mod 0, level 5 → prof +3, expected total = +7.
    """
    character = _make_character(strength=18, dexterity=10, level=5)
    properties = [_prop("Finesse")]
    result = calculate_weapon_hit_modifier(character, properties, range_normal=0)
    assert result.total == 7
    assert result.ability_name == "STR"
    assert result.ability_modifier == 4


def test_finesse_weapon_uses_str_when_modifiers_are_equal():
    """Finesse weapon prefers STR when both modifiers are equal (STR wins tie)."""
    character = _make_character(strength=14, dexterity=14, level=1)
    properties = [_prop("Finesse")]
    result = calculate_weapon_hit_modifier(character, properties, range_normal=0)
    assert result.ability_name == "STR"
    assert result.ability_modifier == 2


def test_thrown_property_uses_dexterity_modifier():
    """Thrown property on a melee weapon uses DEX modifier (ranged attack option).

    DEX 16 → mod +3, STR 12 → mod +1, level 4 → prof +2, expected total = +5.
    """
    character = _make_character(strength=12, dexterity=16, level=4)
    properties = [_prop("Thrown")]
    result = calculate_weapon_hit_modifier(character, properties, range_normal=0)
    assert result.total == 5
    assert result.ability_name == "DEX"
    assert result.ability_modifier == 3


def test_missing_stats_default_to_zero_modifier():
    """Character with all-None stats yields modifier 0 (equivalent to score 10).

    Level 1 → prof +2, ability mod 0, expected total = +2.
    """
    character = _make_character(strength=None, dexterity=None, level=1)
    result = calculate_weapon_hit_modifier(character, [], range_normal=0)
    assert result.total == 2
    assert result.ability_modifier == 0


def test_missing_str_stat_defaults_to_zero():
    """STR=None for a melee weapon: modifier treated as 0 (score 10)."""
    character = _make_character(strength=None, dexterity=14, level=1)
    result = calculate_weapon_hit_modifier(character, [], range_normal=0)
    assert result.ability_modifier == 0
    assert result.ability_name == "STR"


def test_breakdown_string_includes_ability_name_and_values():
    """Breakdown string contains ability name, ability mod, and proficiency."""
    character = _make_character(strength=16, dexterity=10, level=5)
    result = calculate_weapon_hit_modifier(character, [], range_normal=0)
    breakdown = result.breakdown
    assert "STR" in breakdown
    assert "+3" in breakdown  # ability mod
    assert "proficiency" in breakdown.lower()


def test_proficiency_bonus_scales_with_level():
    """Proficiency bonus is 2 at level 1 and 3 at level 5."""
    character_level_one = _make_character(strength=10, dexterity=10, level=1)
    character_level_five = _make_character(strength=10, dexterity=10, level=5)
    result_level_one = calculate_weapon_hit_modifier(
        character_level_one, [], range_normal=0
    )
    result_level_five = calculate_weapon_hit_modifier(
        character_level_five, [], range_normal=0
    )
    assert result_level_one.proficiency_bonus == 2
    assert result_level_five.proficiency_bonus == 3


# ---------------------------------------------------------------------------
# extract_two_handed_damage
# ---------------------------------------------------------------------------


def test_extract_two_handed_damage_returns_detail_for_versatile():
    """Versatile property with detail '1d10' returns '1d10'."""
    properties = [_prop("Versatile", "1d10")]
    result = extract_two_handed_damage(properties)
    assert result == "1d10"


def test_extract_two_handed_damage_returns_none_when_no_versatile():
    """Properties without Versatile return None."""
    properties = [_prop("Finesse"), _prop("Light")]
    result = extract_two_handed_damage(properties)
    assert result is None


def test_extract_two_handed_damage_returns_none_for_empty_properties():
    """Empty properties list returns None."""
    assert extract_two_handed_damage([]) is None


def test_extract_two_handed_damage_returns_none_when_detail_empty():
    """Versatile with empty detail string returns None."""
    properties = [_prop("Versatile", "")]
    result = extract_two_handed_damage(properties)
    assert result is None


# ---------------------------------------------------------------------------
# get_property_names
# ---------------------------------------------------------------------------


def test_get_property_names_returns_list_of_names():
    """Returns all property names from the properties array."""
    properties = [_prop("Finesse"), _prop("Light"), _prop("Thrown")]
    names = get_property_names(properties)
    assert names == ["Finesse", "Light", "Thrown"]


def test_get_property_names_returns_empty_list_for_no_properties():
    """Empty properties list returns empty list."""
    assert get_property_names([]) == []


def test_get_property_names_skips_entries_with_missing_name():
    """Entries where property name is absent or empty are skipped."""
    properties = [
        {"property": {}, "detail": ""},
        _prop("Versatile", "1d10"),
    ]
    names = get_property_names(properties)
    assert names == ["Versatile"]


# ---------------------------------------------------------------------------
# format_weapon_result_line
# ---------------------------------------------------------------------------


def test_format_line_includes_index_and_name():
    """Formatted line includes the 1-based index and weapon name."""
    weapon = {
        "name": "Longsword",
        "damage_dice": "1d8",
        "damage_type": {"name": "Slashing"},
        "is_simple": False,
        "range": 0.0,
        "properties": [_prop("Versatile", "1d10")],
    }
    line = format_weapon_result_line(1, weapon)
    assert "1." in line
    assert "Longsword" in line


def test_format_line_shows_martial_category_for_longsword():
    """A non-simple weapon is labelled 'Martial' (no range type shown)."""
    weapon = {
        "name": "Longsword",
        "damage_dice": "1d8",
        "damage_type": {"name": "Slashing"},
        "is_simple": False,
        "range": 0.0,
        "properties": [],
    }
    line = format_weapon_result_line(1, weapon)
    assert "Martial" in line
    assert "Melee" not in line


def test_format_line_shows_simple_category_for_club():
    """A simple weapon is labelled 'Simple' (no range type shown)."""
    weapon = {
        "name": "Club",
        "damage_dice": "1d4",
        "damage_type": {"name": "Bludgeoning"},
        "is_simple": True,
        "range": 0.0,
        "properties": [],
    }
    line = format_weapon_result_line(1, weapon)
    assert "Simple" in line
    assert "Ranged" not in line


def test_format_line_includes_versatile_damage():
    """Versatile weapons display their two-handed damage in the properties section."""
    weapon = {
        "name": "Longsword",
        "damage_dice": "1d8",
        "damage_type": {"name": "Slashing"},
        "is_simple": False,
        "range": 0.0,
        "properties": [_prop("Versatile", "1d10")],
    }
    line = format_weapon_result_line(1, weapon)
    assert "Versatile" in line
    assert "1d10" in line


def test_format_line_no_properties_section_when_empty():
    """When properties list is empty the '|' separator is absent."""
    weapon = {
        "name": "Club",
        "damage_dice": "1d4",
        "damage_type": {"name": "Bludgeoning"},
        "is_simple": True,
        "range": 0.0,
        "properties": [],
    }
    line = format_weapon_result_line(1, weapon)
    # Only one pipe separator (between range_type and damage), not a second one
    assert line.count("|") == 1


# ---------------------------------------------------------------------------
# RulesetEdition
# ---------------------------------------------------------------------------


def test_ruleset_edition_2024_value():
    """RULES_2024 has the Open5e document key 'srd-2024'."""
    assert RulesetEdition.RULES_2024.value == "srd-2024"


def test_ruleset_edition_2014_value():
    """RULES_2014 has the Open5e document key 'srd-2014'."""
    assert RulesetEdition.RULES_2014.value == "srd-2014"


def test_ruleset_edition_display_year_2024():
    """display_year returns '2024' for RULES_2024."""
    assert RulesetEdition.RULES_2024.display_year == "2024"


def test_ruleset_edition_display_year_2014():
    """display_year returns '2014' for RULES_2014."""
    assert RulesetEdition.RULES_2014.display_year == "2014"


# ---------------------------------------------------------------------------
# fetch_weapons
# ---------------------------------------------------------------------------


def _weapon(name: str, doc_key: str = "srd-2024", damage_dice: str = "1d8") -> dict:
    """Build a minimal Open5e weapon dict with a document key field."""
    return {
        "name": name,
        "damage_dice": damage_dice,
        "properties": [],
        "document": {"key": doc_key},
    }


# Mixed-edition fixture mirrors the real API response (both editions returned together)
_ALL_WEAPONS_FIXTURE = [
    _weapon("Rapier", "srd-2024"),
    _weapon("Rapier", "srd-2014"),
    _weapon("Battleaxe", "srd-2024"),
    _weapon("Battleaxe", "srd-2014"),
    _weapon("Dart", "srd-2024", "1d4"),
    _weapon("Longsword", "srd-2024"),
    _weapon("Longsword", "srd-2014"),
    _weapon("Shortsword", "srd-2024"),
    _weapon("Greatsword", "srd-2024"),
]


def _make_mock_http_session(weapons: list[dict]) -> MagicMock:
    """Return an aiohttp.ClientSession mock that yields *weapons* as API results."""
    json_response = AsyncMock(return_value={"results": weapons})
    response_cm = AsyncMock()
    response_cm.__aenter__ = AsyncMock(
        return_value=MagicMock(raise_for_status=MagicMock(), json=json_response)
    )
    response_cm.__aexit__ = AsyncMock(return_value=False)

    get_cm = MagicMock()
    get_cm.get = MagicMock(return_value=response_cm)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=get_cm)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return session_cm


@pytest.mark.asyncio
async def test_fetch_weapons_returns_rapier_for_rapier_query(mocker):
    """Rapier must appear in results when the query is 'rapier'.

    Regression test: the old implementation passed the query string directly
    to the Open5e ``search`` param, which performs full-text search on
    descriptions rather than name filtering — causing 'rapier' to return
    unrelated weapons like Battleaxe and Dart instead.
    """
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("rapier")
    names = [w["name"] for w in results]
    assert "Rapier" in names
    assert "Battleaxe" not in names
    assert "Dart" not in names


@pytest.mark.asyncio
async def test_fetch_weapons_filters_by_name_substring_case_insensitive(mocker):
    """Query 'sword' returns Longsword, Shortsword, and Greatsword (case-insensitive)."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("sword")
    names = [w["name"] for w in results]
    assert "Longsword" in names
    assert "Shortsword" in names
    assert "Greatsword" in names
    assert "Rapier" not in names
    assert "Battleaxe" not in names


@pytest.mark.asyncio
async def test_fetch_weapons_returns_empty_list_when_no_name_matches(mocker):
    """Query that matches no weapon name returns an empty list."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("xyzzy")
    assert results == []


@pytest.mark.asyncio
async def test_fetch_weapons_caps_results_at_max_search_results(mocker):
    """At most MAX_SEARCH_RESULTS (5) weapons are returned even when more match."""
    many_swords = [_weapon(f"Sword{i}", "srd-2024") for i in range(10)]
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(many_swords))
    results = await fetch_weapons("sword")
    assert len(results) == 5


@pytest.mark.asyncio
async def test_fetch_weapons_defaults_to_2024_edition(mocker):
    """Without explicit ruleset, only srd-2024 weapons are returned."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("rapier")
    assert len(results) == 1
    assert results[0]["document"]["key"] == "srd-2024"


@pytest.mark.asyncio
async def test_fetch_weapons_2014_edition_returns_2014_rapier(mocker):
    """Specifying RULES_2014 returns only the srd-2014 Rapier, not the 2024 one."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("rapier", RulesetEdition.RULES_2014)
    assert len(results) == 1
    assert results[0]["document"]["key"] == "srd-2014"


@pytest.mark.asyncio
async def test_fetch_weapons_edition_filter_excludes_other_edition(mocker):
    """2024 search for 'battleaxe' excludes the srd-2014 Battleaxe entry."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results_2024 = await fetch_weapons("battleaxe", RulesetEdition.RULES_2024)
    results_2014 = await fetch_weapons("battleaxe", RulesetEdition.RULES_2014)
    assert all(w["document"]["key"] == "srd-2024" for w in results_2024)
    assert all(w["document"]["key"] == "srd-2014" for w in results_2014)


@pytest.mark.asyncio
async def test_fetch_weapons_weapon_only_in_2024_not_found_in_2014(mocker):
    """Dart exists only in srd-2024 in the fixture; searching 2014 returns empty."""
    mocker.patch("utils.weapon_utils.aiohttp.ClientSession", return_value=_make_mock_http_session(_ALL_WEAPONS_FIXTURE))
    results = await fetch_weapons("dart", RulesetEdition.RULES_2014)
    assert results == []
