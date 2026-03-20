"""Unit tests for utils/class_data.py — HP calculation and save prof assignment."""

import pytest
from unittest.mock import MagicMock

from enums.character_class import CharacterClass
from utils.class_data import (
    CLASS_HIT_DICE,
    CLASS_SAVE_PROFS,
    calculate_max_hp,
    apply_class_save_profs,
    get_class_save_profs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_char(
    constitution: int | None, class_levels: list[tuple[str, int]]
) -> MagicMock:
    """Build a lightweight Character mock.

    *class_levels* is a list of ``(class_name, level)`` tuples in insertion order.
    Each tuple becomes a ``ClassLevel`` mock with an auto-incremented ``id``.
    """
    char = MagicMock()
    char.constitution = constitution

    cl_mocks = []
    for idx, (cls_name, lvl) in enumerate(class_levels):
        cl = MagicMock()
        cl.id = idx + 1
        cl.class_name = cls_name
        cl.level = lvl
        cl_mocks.append(cl)

    char.class_levels = cl_mocks

    # Saving throw attributes
    for stat in [
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ]:
        setattr(char, f"st_prof_{stat}", False)

    return char


# ---------------------------------------------------------------------------
# CLASS_HIT_DICE coverage
# ---------------------------------------------------------------------------


class TestClassHitDice:
    def test_all_classes_present(self):
        """Every CharacterClass entry must have a hit die."""
        for cls in CharacterClass:
            assert cls in CLASS_HIT_DICE, f"{cls} missing from CLASS_HIT_DICE"

    def test_barbarian_d12(self):
        assert CLASS_HIT_DICE[CharacterClass.BARBARIAN] == 12

    def test_fighter_d10(self):
        assert CLASS_HIT_DICE[CharacterClass.FIGHTER] == 10

    def test_paladin_d10(self):
        assert CLASS_HIT_DICE[CharacterClass.PALADIN] == 10

    def test_ranger_d10(self):
        assert CLASS_HIT_DICE[CharacterClass.RANGER] == 10

    def test_sorcerer_d6(self):
        assert CLASS_HIT_DICE[CharacterClass.SORCERER] == 6

    def test_wizard_d6(self):
        assert CLASS_HIT_DICE[CharacterClass.WIZARD] == 6


# ---------------------------------------------------------------------------
# CLASS_SAVE_PROFS coverage
# ---------------------------------------------------------------------------


class TestClassSaveProfs:
    def test_all_classes_present(self):
        """Every CharacterClass entry must have save prof data."""
        for cls in CharacterClass:
            assert cls in CLASS_SAVE_PROFS, f"{cls} missing from CLASS_SAVE_PROFS"

    def test_standard_classes_have_two_saves(self):
        """Every standard (non-homebrew) class has exactly 2 save profs."""
        from enums.character_class import CharacterClass as CC

        for cls in CC:
            if cls == CC.OTHER:
                continue
            assert len(CLASS_SAVE_PROFS[cls]) == 2, (
                f"{cls} should have exactly 2 save profs"
            )

    def test_homebrew_class_has_no_automatic_saves(self):
        assert CLASS_SAVE_PROFS[CharacterClass.OTHER] == []

    def test_barbarian_str_con(self):
        assert CLASS_SAVE_PROFS[CharacterClass.BARBARIAN] == [
            "strength",
            "constitution",
        ]

    def test_bard_dex_cha(self):
        assert CLASS_SAVE_PROFS[CharacterClass.BARD] == ["dexterity", "charisma"]

    def test_cleric_wis_cha(self):
        assert CLASS_SAVE_PROFS[CharacterClass.CLERIC] == ["wisdom", "charisma"]

    def test_druid_int_wis(self):
        assert CLASS_SAVE_PROFS[CharacterClass.DRUID] == ["intelligence", "wisdom"]

    def test_fighter_str_con(self):
        assert CLASS_SAVE_PROFS[CharacterClass.FIGHTER] == ["strength", "constitution"]

    def test_monk_str_dex(self):
        assert CLASS_SAVE_PROFS[CharacterClass.MONK] == ["strength", "dexterity"]

    def test_paladin_wis_cha(self):
        assert CLASS_SAVE_PROFS[CharacterClass.PALADIN] == ["wisdom", "charisma"]

    def test_ranger_str_dex(self):
        assert CLASS_SAVE_PROFS[CharacterClass.RANGER] == ["strength", "dexterity"]

    def test_rogue_dex_int(self):
        assert CLASS_SAVE_PROFS[CharacterClass.ROGUE] == ["dexterity", "intelligence"]

    def test_sorcerer_con_cha(self):
        assert CLASS_SAVE_PROFS[CharacterClass.SORCERER] == ["constitution", "charisma"]

    def test_warlock_wis_cha(self):
        assert CLASS_SAVE_PROFS[CharacterClass.WARLOCK] == ["wisdom", "charisma"]

    def test_wizard_int_wis(self):
        assert CLASS_SAVE_PROFS[CharacterClass.WIZARD] == ["intelligence", "wisdom"]


# ---------------------------------------------------------------------------
# calculate_max_hp — edge cases
# ---------------------------------------------------------------------------


class TestCalculateMaxHpEdgeCases:
    def test_returns_negative_one_when_con_not_set(self):
        char = _make_char(constitution=None, class_levels=[("Fighter", 1)])
        assert calculate_max_hp(char) == -1

    def test_returns_negative_one_when_no_class_levels(self):
        char = _make_char(constitution=10, class_levels=[])
        assert calculate_max_hp(char) == -1

    def test_minimum_one_hp_per_level_with_extreme_negative_con(self):
        """CON 1 = -5 mod; even d6+(-5) = 1 minimum."""
        char = _make_char(constitution=1, class_levels=[("Wizard", 3)])
        hp = calculate_max_hp(char)
        # Each of the 3 levels must contribute at least 1 HP
        assert hp >= 3


# ---------------------------------------------------------------------------
# calculate_max_hp — single class
# ---------------------------------------------------------------------------


class TestCalculateMaxHpSingleClass:
    def test_fighter_level_1_con_10(self):
        """Level 1 Fighter, CON 10 (mod 0): 10 + 0 = 10."""
        char = _make_char(constitution=10, class_levels=[("Fighter", 1)])
        assert calculate_max_hp(char) == 10

    def test_fighter_level_1_con_15(self):
        """Level 1 Fighter, CON 15 (mod +2): 10 + 2 = 12."""
        char = _make_char(constitution=15, class_levels=[("Fighter", 1)])
        assert calculate_max_hp(char) == 12

    def test_sorcerer_level_1_con_10(self):
        """Level 1 Sorcerer, CON 10 (mod 0): 6."""
        char = _make_char(constitution=10, class_levels=[("Sorcerer", 1)])
        assert calculate_max_hp(char) == 6

    def test_fighter_level_5_con_15(self):
        """Fighter 5, CON +2.
        Lvl 1: 10+2=12
        Lvls 2-5: 4 × (6+2)=32
        Total: 44
        """
        char = _make_char(constitution=15, class_levels=[("Fighter", 5)])
        assert calculate_max_hp(char) == 44

    def test_barbarian_level_3_con_14(self):
        """Barbarian 3, CON +2.
        Lvl 1: 12+2=14
        Lvls 2-3: 2 × (7+2)=18
        Total: 32
        """
        char = _make_char(constitution=14, class_levels=[("Barbarian", 3)])
        assert calculate_max_hp(char) == 32

    def test_wizard_level_2_con_12(self):
        """Wizard 2, CON +1.
        Lvl 1: 6+1=7
        Lvl 2: 4+1=5
        Total: 12
        """
        char = _make_char(constitution=12, class_levels=[("Wizard", 2)])
        assert calculate_max_hp(char) == 12


# ---------------------------------------------------------------------------
# calculate_max_hp — multiclass
# ---------------------------------------------------------------------------


class TestCalculateMaxHpMulticlass:
    def test_fighter3_rogue2_con_12(self):
        """Fighter 3 / Rogue 2, CON +1 (mod from 12).
        Fighter first (lower id).
        Lvl 1 Fighter: 10+1=11
        Lvls 2-3 Fighter: 2 × (6+1)=14
        Lvls 4-5 Rogue: 2 × (5+1)=12
        Total: 37
        """
        char = _make_char(constitution=12, class_levels=[("Fighter", 3), ("Rogue", 2)])
        assert calculate_max_hp(char) == 37

    def test_multiclass_first_level_uses_first_class_die(self):
        """Wizard 1 / Barbarian 1: first class is Wizard (id=1), so d6 first.
        Lvl 1 Wizard: 6+0=6
        Lvl 1 Barbarian: 7+0=7
        Total: 13 with CON 10.
        """
        char = _make_char(
            constitution=10, class_levels=[("Wizard", 1), ("Barbarian", 1)]
        )
        assert calculate_max_hp(char) == 13

    def test_multiclass_second_level_not_max_die(self):
        """Even the second level of the first class is NOT the max die."""
        char = _make_char(constitution=10, class_levels=[("Fighter", 2)])
        # Lvl 1: 10, Lvl 2: 6  — NOT 10+10
        assert calculate_max_hp(char) == 16


# ---------------------------------------------------------------------------
# apply_class_save_profs
# ---------------------------------------------------------------------------


class TestApplyClassSaveProfs:
    def test_fighter_sets_str_con_true_rest_false(self):
        char = _make_char(constitution=10, class_levels=[])
        apply_class_save_profs(char, CharacterClass.FIGHTER)

        assert char.st_prof_strength is True
        assert char.st_prof_constitution is True
        assert char.st_prof_dexterity is False
        assert char.st_prof_intelligence is False
        assert char.st_prof_wisdom is False
        assert char.st_prof_charisma is False

    def test_rogue_sets_dex_int_true_rest_false(self):
        char = _make_char(constitution=10, class_levels=[])
        apply_class_save_profs(char, CharacterClass.ROGUE)

        assert char.st_prof_dexterity is True
        assert char.st_prof_intelligence is True
        assert char.st_prof_strength is False
        assert char.st_prof_constitution is False
        assert char.st_prof_wisdom is False
        assert char.st_prof_charisma is False

    def test_overwrites_existing_profs(self):
        char = _make_char(constitution=10, class_levels=[])
        # Pre-set some conflicting profs
        char.st_prof_strength = True
        char.st_prof_charisma = True

        apply_class_save_profs(char, CharacterClass.BARD)  # DEX, CHA

        assert char.st_prof_strength is False
        assert char.st_prof_dexterity is True
        assert char.st_prof_charisma is True

    def test_standard_classes_set_exactly_two_profs(self):
        for cls in CharacterClass:
            if cls == CharacterClass.OTHER:
                continue
            char = _make_char(constitution=10, class_levels=[])
            apply_class_save_profs(char, cls)
            all_stats = [
                "strength",
                "dexterity",
                "constitution",
                "intelligence",
                "wisdom",
                "charisma",
            ]
            prof_count = sum(getattr(char, f"st_prof_{s}") for s in all_stats)
            assert prof_count == 2, (
                f"{cls} should grant exactly 2 save profs, got {prof_count}"
            )

    def test_homebrew_class_sets_zero_profs(self):
        char = _make_char(constitution=10, class_levels=[])
        # Pre-set some profs that should be cleared
        char.st_prof_strength = True
        apply_class_save_profs(char, CharacterClass.OTHER)
        all_stats = [
            "strength",
            "dexterity",
            "constitution",
            "intelligence",
            "wisdom",
            "charisma",
        ]
        prof_count = sum(getattr(char, f"st_prof_{s}") for s in all_stats)
        assert prof_count == 0


# ---------------------------------------------------------------------------
# get_class_save_profs
# ---------------------------------------------------------------------------


class TestGetClassSaveProfs:
    def test_returns_list_for_every_class(self):
        for cls in CharacterClass:
            result = get_class_save_profs(cls)
            assert isinstance(result, list)

    def test_standard_classes_return_two_saves(self):
        for cls in CharacterClass:
            if cls == CharacterClass.OTHER:
                continue
            assert len(get_class_save_profs(cls)) == 2

    def test_homebrew_returns_empty_list(self):
        assert get_class_save_profs(CharacterClass.OTHER) == []
