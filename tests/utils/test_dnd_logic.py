"""Unit tests for utils.dnd_logic — stat modifiers, proficiency, and perform_roll.

Tests cover boundary cases for ability scores, JACK_OF_ALL_TRADES, EXPERTISE,
and edge cases in the perform_roll dispatcher.
"""

import pytest

from models import Character, ClassLevel, CharacterSkill
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.dnd_logic import get_stat_modifier, get_proficiency_bonus, perform_roll


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_character(db_session, sample_user, sample_server):
    """Level-5 character with all stats set to 10 (modifier 0).

    Useful for tests where a non-zero stat modifier would obscure the result
    (e.g. JOAT half-proficiency calculations where the stat mod should be 0).
    """
    char = Character(
        name="Tester",
        user=sample_user,
        server=sample_server,
        is_active=False,  # sample_character (Aldric) is already active on this user/server
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Fighter", level=5))
    db_session.commit()
    db_session.refresh(char)
    return char


# ---------------------------------------------------------------------------
# get_stat_modifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (1, -5),
        (8, -1),
        (9, -1),
        (10, 0),
        (11, 0),
        (12, 1),
        (13, 1),
        (20, 5),
        (30, 10),
    ],
)
def test_get_stat_modifier(score, expected):
    assert get_stat_modifier(score) == expected


def test_get_stat_modifier_none_returns_zero():
    assert get_stat_modifier(None) == 0


# ---------------------------------------------------------------------------
# get_proficiency_bonus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected",
    [
        (1, 2),
        (4, 2),
        (5, 3),
        (8, 3),
        (9, 4),
        (12, 4),
        (13, 5),
        (16, 5),
        (17, 6),
        (20, 6),
    ],
)
def test_get_proficiency_bonus(level, expected):
    assert get_proficiency_bonus(level) == expected


@pytest.mark.parametrize("level", [0, -1, 21, 100])
def test_get_proficiency_bonus_invalid_level_raises(level):
    """Levels outside 1–20 must raise ValueError."""
    with pytest.raises(ValueError):
        get_proficiency_bonus(level)


def test_get_proficiency_bonus_boundary_level_1():
    """Level 1 is the minimum valid level and must not raise."""
    assert get_proficiency_bonus(1) == 2


def test_get_proficiency_bonus_boundary_level_20():
    """Level 20 is the maximum valid level and must not raise."""
    assert get_proficiency_bonus(20) == 6


# ---------------------------------------------------------------------------
# perform_roll  (sample_character: level 5, STR 16/+3, DEX 14/+2, WIS 12/+1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perform_roll_raw_dice(mocker, sample_character, db_session):
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "1d20", db_session)
    assert "1d20" in result
    assert "10" in result


@pytest.mark.asyncio
async def test_perform_roll_stat_check(mocker, sample_character, db_session):
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "strength", db_session)
    assert "Strength Check" in result
    expected = mocked_d20 + get_stat_modifier(sample_character.strength)
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_stat_abbreviation(mocker, sample_character, db_session):
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "str", db_session)
    assert "Strength Check" in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_not_proficient(
    mocker, sample_character, db_session
):
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "wisdom save", db_session)
    assert "Wisdom Save" in result
    # sample_character has no WIS save proficiency
    expected = mocked_d20 + get_stat_modifier(sample_character.wisdom)
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_proficient(
    mocker, sample_character, db_session
):
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "strength save", db_session)
    assert "Strength Save" in result
    # sample_character has STR save proficiency (st_prof_strength=True)
    expected = (
        mocked_d20
        + get_stat_modifier(sample_character.strength)
        + get_proficiency_bonus(sample_character.level)
    )
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_skill_not_proficient(mocker, sample_character, db_session):
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "Perception", db_session)
    assert "Perception" in result
    # Perception uses WIS; sample_character has no Perception proficiency
    expected = mocked_d20 + get_stat_modifier(sample_character.wisdom)
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_skill_proficient(mocker, sample_character, db_session):
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "Perception", db_session)
    expected = (
        mocked_d20
        + get_stat_modifier(sample_character.wisdom)
        + get_proficiency_bonus(sample_character.level)
    )
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_skill_expertise(mocker, sample_character, db_session):
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.EXPERTISE,
    )
    db_session.add(skill)
    db_session.commit()
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "Perception", db_session)
    # expertise = 2 × proficiency bonus
    expected = (
        mocked_d20
        + get_stat_modifier(sample_character.wisdom)
        + 2 * get_proficiency_bonus(sample_character.level)
    )
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_joat_half_proficiency(mocker, base_character, db_session):
    """JACK_OF_ALL_TRADES applies floor(proficiency / 2) to an untrained skill.

    base_character: WIS=10 (modifier 0), level 5 (prof +3).
    Expected: d20(10) + WIS mod(0) + floor(3/2)=1 = 11.
    """
    char_skill = CharacterSkill(
        character_id=base_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.JACK_OF_ALL_TRADES,
    )
    db_session.add(char_skill)
    db_session.commit()
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)

    result = await perform_roll(base_character, "Perception", db_session)

    proficiency_bonus = get_proficiency_bonus(base_character.level)
    wis_modifier = get_stat_modifier(base_character.wisdom)
    expected_total = 10 + wis_modifier + proficiency_bonus // 2
    assert str(expected_total) in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_dex_when_no_bonus(
    mocker, sample_character, db_session
):
    sample_character.initiative_bonus = None
    db_session.commit()
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "initiative", db_session)
    assert "Initiative" in result
    # initiative_bonus=None → falls back to DEX modifier
    expected = mocked_d20 + get_stat_modifier(sample_character.dexterity)
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_zero_bonus_overrides_dex(
    mocker, sample_character, db_session
):
    """initiative_bonus=0 is an explicit override — uses +0, not DEX modifier."""
    sample_character.initiative_bonus = 0
    db_session.commit()
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "initiative", db_session)
    assert "Initiative" in result
    # initiative_bonus=0 wins over DEX mod (+2); total = d20 + 0
    expected = mocked_d20 + sample_character.initiative_bonus
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_override_bonus(
    mocker, sample_character, db_session
):
    sample_character.initiative_bonus = 5
    db_session.commit()
    mocked_d20 = 10
    mocker.patch("utils.dnd_logic.random.randint", return_value=mocked_d20)
    result = await perform_roll(sample_character, "init", db_session)
    expected = mocked_d20 + sample_character.initiative_bonus
    assert str(expected) in result


@pytest.mark.asyncio
async def test_perform_roll_invalid_notation_returns_error(
    sample_character, db_session
):
    result = await perform_roll(sample_character, "notadice", db_session)
    assert "Error" in result


@pytest.mark.asyncio
async def test_perform_roll_invalid_skill_returns_error(sample_character, db_session):
    result = await perform_roll(sample_character, "notaskill", db_session)
    assert "Error" in result


@pytest.mark.asyncio
async def test_perform_roll_character_all_none_stats_raw_dice(
    mocker, sample_character_no_stats, db_session
):
    """A character with no stats configured can still roll raw dice notation."""
    mocker.patch("utils.dnd_logic.random.randint", return_value=4)
    result = await perform_roll(sample_character_no_stats, "1d6", db_session)
    assert "4" in result
