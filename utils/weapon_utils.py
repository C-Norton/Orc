"""Utility functions for weapon data parsing and hit modifier calculation.

Supports the ``/weapon search`` and ``/weapon add`` workflow.  Data is pulled
from the Open5e v2 API and attack hit modifiers are computed from character
stats following 5e 2024 rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from enums.ruleset_edition import RulesetEdition
from utils.dnd_logic import get_proficiency_bonus, get_stat_modifier
from utils.logging_config import get_logger

if TYPE_CHECKING:
    from models import Character

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN5E_WEAPONS_URL = "https://api.open5e.com/v2/weapons/"
OPEN5E_SRD_2024_KEY = "srd-2024"
MAX_SEARCH_RESULTS = 5
OPEN5E_ALL_WEAPONS_LIMIT = 200  # Fetch full catalogue in one request; srd-2024 has ~75
REQUEST_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ParsedWeaponFields:
    """All fields extracted from a raw Open5e weapon API dict.

    Used to avoid re-parsing the same weapon dict in multiple places
    (import, upsert, and confirmation message building).
    """

    name: str
    damage_dice: str
    damage_type_name: str
    weapon_category: str
    range_normal_float: float
    properties: list[dict]
    property_names: list[str]
    two_handed_damage: str | None
    properties_json: str | None


def parse_weapon_fields(weapon_data: dict) -> "ParsedWeaponFields":
    """Extract and normalise all fields from a raw Open5e weapon API dict.

    Centralises the repeated field-extraction pattern used when importing
    weapons and building confirmation messages.
    """
    # Basic identity fields
    name = weapon_data.get("name", "Unknown")
    damage_dice = weapon_data.get("damage_dice", "1d4")
    # damage_type is a nested object: {"name": "Slashing", ...}
    damage_type_object = weapon_data.get("damage_type") or {}
    damage_type_name = damage_type_object.get("name", "")
    # Derive display category from the is_simple flag
    is_simple = weapon_data.get("is_simple", True)
    weapon_category = "Simple" if is_simple else "Martial"
    range_normal_float = float(weapon_data.get("range", 0) or 0)
    # Properties are a list of dicts; extract names and versatile damage separately
    properties = weapon_data.get("properties", [])
    property_names = get_property_names(properties)
    two_handed_damage = extract_two_handed_damage(properties)
    # Serialise property names for DB storage; None when empty
    properties_json = json.dumps(property_names) if property_names else None

    return ParsedWeaponFields(
        name=name,
        damage_dice=damage_dice,
        damage_type_name=damage_type_name,
        weapon_category=weapon_category,
        range_normal_float=range_normal_float,
        properties=properties,
        property_names=property_names,
        two_handed_damage=two_handed_damage,
        properties_json=properties_json,
    )


@dataclass
class WeaponHitModifier:
    """Result of computing the to-hit modifier for a weapon and character pair."""

    total: int
    ability_name: str
    ability_modifier: int
    proficiency_bonus: int

    @property
    def breakdown(self) -> str:
        """Human-readable explanation of the modifier components.

        Example: ``"STR mod +3 + proficiency +2"``
        """
        return (
            f"{self.ability_name} mod {self.ability_modifier:+d} + "
            f"proficiency {self.proficiency_bonus:+d}"
        )


# ---------------------------------------------------------------------------
# Property parsing helpers
# ---------------------------------------------------------------------------


def get_property_names(properties: list[dict]) -> list[str]:
    """Return a list of property name strings from an Open5e weapon properties array.

    Each element in *properties* is expected to have the shape::

        {"property": {"name": "Finesse", "desc": "..."}, "detail": ""}
    """
    names = []
    for property_entry in properties:
        property_object = property_entry.get("property") or {}
        name = property_object.get("name", "")
        if name:
            names.append(name)
    return names


def extract_two_handed_damage(properties: list[dict]) -> str | None:
    """Return the two-handed damage dice for a Versatile weapon, or ``None``.

    For a Longsword the Versatile entry looks like::

        {"property": {"name": "Versatile", "desc": "..."}, "detail": "1d10"}

    Returns ``"1d10"`` in that case, or ``None`` if no Versatile property is
    present or if the detail field is empty.
    """
    for property_entry in properties:
        property_object = property_entry.get("property") or {}
        if property_object.get("name") == "Versatile":
            detail = property_entry.get("detail", "")
            return detail if detail else None
    return None


# ---------------------------------------------------------------------------
# Hit modifier calculation
# ---------------------------------------------------------------------------


def calculate_weapon_hit_modifier(
    character: "Character",
    properties: list[dict],
    range_normal: float,
) -> WeaponHitModifier:
    """Calculate the to-hit modifier for a weapon equipped by a given character.

    Follows 5e 2024 rules:

    - **Finesse** → ``max(STR mod, DEX mod)``
    - **Ranged** (``range_normal > 0``) or **Thrown** → DEX mod
    - Otherwise → STR mod

    The proficiency bonus is always added.

    .. note::
        Weapon type proficiency is not yet tracked in the data model.  This
        function assumes the character is proficient with all weapons and always
        adds the proficiency bonus.  When per-class weapon proficiency tracking
        is added, gate the proficiency bonus behind a proficiency check here.

    Falls back gracefully when stats are ``None`` — ``get_stat_modifier``
    treats ``None`` as score 10, yielding modifier 0.
    """
    property_names = get_property_names(properties)
    is_finesse = "Finesse" in property_names
    is_thrown = "Thrown" in property_names
    is_ranged = range_normal > 0

    strength_modifier = get_stat_modifier(character.strength)
    dexterity_modifier = get_stat_modifier(character.dexterity)
    proficiency = get_proficiency_bonus(character.level)

    if is_finesse:
        if strength_modifier >= dexterity_modifier:
            ability_name = "STR"
            ability_modifier = strength_modifier
        else:
            ability_name = "DEX"
            ability_modifier = dexterity_modifier
    elif is_ranged or is_thrown:
        ability_name = "DEX"
        ability_modifier = dexterity_modifier
    else:
        ability_name = "STR"
        ability_modifier = strength_modifier

    logger.debug(
        f"calculate_weapon_hit_modifier: {ability_name} mod {ability_modifier:+d} "
        f"+ prof {proficiency:+d} = {ability_modifier + proficiency:+d}"
    )

    return WeaponHitModifier(
        total=ability_modifier + proficiency,
        ability_name=ability_name,
        ability_modifier=ability_modifier,
        proficiency_bonus=proficiency,
    )


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------


def format_weapon_result_line(index: int, weapon: dict) -> str:
    """Format a single weapon search result line for the ``/weapon search`` response.

    Example output::

        1. Longsword — Martial Melee | 1d8 Slashing | Versatile (1d10)
        2. Short Sword — Martial Melee | 1d6 Piercing | Finesse, Light
    """
    parsed = parse_weapon_fields(weapon)
    damage_type = weapon.get("damage_type", {}).get("name", "?")

    # Build property display tokens, surfacing Versatile's two-handed damage.
    display_properties: list[str] = []
    if parsed.two_handed_damage:
        display_properties.append(f"Versatile ({parsed.two_handed_damage})")
    for property_name in parsed.property_names:
        if property_name != "Versatile":
            display_properties.append(property_name)

    properties_suffix = (
        f" | {', '.join(display_properties)}" if display_properties else ""
    )

    return (
        f"{index}. **{parsed.name}** — {parsed.weapon_category} | "
        f"{parsed.damage_dice} {damage_type}{properties_suffix}"
    )


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------


async def fetch_weapons(
    query: str,
    ruleset_edition: RulesetEdition = RulesetEdition.RULES_2024,
) -> list[dict]:
    """Fetch up to 5 weapons from the Open5e v2 API whose name contains *query*.

    The Open5e v2 ``search`` parameter performs full-text search across
    description text rather than filtering by name, so it returns unrelated
    results (e.g. searching "rapier" returns all weapons alphabetically).
    Additionally, the ``document__key`` filter on the API is broken and always
    returns weapons from both editions regardless of the value passed.

    Instead, this function fetches the full weapon catalogue in one request
    and filters client-side by:

    1. Case-insensitive name substring match against *query*.
    2. Exact ``document.key`` match against *ruleset_edition*.

    Returns an empty list when no weapons match.

    Raises :class:`aiohttp.ClientError` on network failures so callers can
    surface a user-friendly error message.
    """
    params = {
        "limit": OPEN5E_ALL_WEAPONS_LIMIT,
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    logger.debug(
        f"fetch_weapons: fetching all weapons to filter for "
        f"{query!r} in {ruleset_edition.value!r}"
    )
    async with aiohttp.ClientSession(timeout=timeout) as http_session:
        async with http_session.get(OPEN5E_WEAPONS_URL, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            all_weapons = data.get("results", [])

    query_lower = query.lower()
    matches = [
        weapon
        for weapon in all_weapons
        if query_lower in weapon.get("name", "").lower()
        and weapon.get("document", {}).get("key") == ruleset_edition.value
    ]
    results = matches[:MAX_SEARCH_RESULTS]
    logger.debug(
        f"fetch_weapons: {len(matches)} match(es) for {query!r} "
        f"in {ruleset_edition.value!r}, returning {len(results)}"
    )
    return results
