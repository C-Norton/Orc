import pytest
from unittest.mock import patch

from utils.dnd_logic import get_stat_modifier, get_proficiency_bonus, perform_roll
from models import CharacterSkill
from enums.skill_proficiency_status import SkillProficiencyStatus


# ---------------------------------------------------------------------------
# get_stat_modifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (1,  -5),
    (8,  -1),
    (9,  -1),
    (10,  0),
    (11,  0),
    (12,  1),
    (13,  1),
    (20,  5),
    (30, 10),
])
def test_get_stat_modifier(score, expected):
    assert get_stat_modifier(score) == expected


def test_get_stat_modifier_none_returns_zero():
    assert get_stat_modifier(None) == 0


# ---------------------------------------------------------------------------
# get_proficiency_bonus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,expected", [
    (1,  2),
    (4,  2),
    (5,  3),
    (8,  3),
    (9,  4),
    (12, 4),
    (13, 5),
    (16, 5),
    (17, 6),
    (20, 6),
])
def test_get_proficiency_bonus(level, expected):
    assert get_proficiency_bonus(level) == expected


# ---------------------------------------------------------------------------
# perform_roll  (sample_character: level 5, STR 16/+3, DEX 14/+2, WIS 12/+1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_perform_roll_raw_dice(sample_character, db_session):
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "1d20", db_session)
    assert "1d20" in result
    assert "10" in result


@pytest.mark.asyncio
async def test_perform_roll_stat_check(sample_character, db_session):
    # STR 16 → +3; d20 fixed at 10 → total 13
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "strength", db_session)
    assert "Strength Check" in result
    assert "13" in result


@pytest.mark.asyncio
async def test_perform_roll_stat_abbreviation(sample_character, db_session):
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "str", db_session)
    assert "Strength Check" in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_not_proficient(sample_character, db_session):
    # WIS 12 → +1; not proficient in WIS save; d20=10 → total 11
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "wisdom save", db_session)
    assert "Wisdom Save" in result
    assert "11" in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_proficient(sample_character, db_session):
    # STR 16 → +3; proficient (level 5 → prof +3); d20=10 → total 16
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "strength save", db_session)
    assert "Strength Save" in result
    assert "16" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_not_proficient(sample_character, db_session):
    # Perception → WIS → +1; no proficiency; d20=10 → total 11
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "Perception", db_session)
    assert "Perception" in result
    assert "11" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_proficient(sample_character, db_session):
    # Add Perception proficiency; WIS+1 + prof+3 = +4; d20=10 → 14
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "Perception", db_session)
    assert "14" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_expertise(sample_character, db_session):
    # Expertise: WIS+1 + 2*prof+6 = +7; d20=10 → 17
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.EXPERTISE,
    )
    db_session.add(skill)
    db_session.commit()
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "Perception", db_session)
    assert "17" in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_dex_when_no_bonus(sample_character, db_session):
    # No initiative_bonus set → uses DEX mod +2; d20=10 → 12
    sample_character.initiative_bonus = None
    db_session.commit()
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "initiative", db_session)
    assert "Initiative" in result
    assert "12" in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_override_bonus(sample_character, db_session):
    # initiative_bonus=5 overrides dex mod; d20=10 → 15
    sample_character.initiative_bonus = 5
    db_session.commit()
    with patch("utils.dnd_logic.random.randint", return_value=10):
        result = await perform_roll(sample_character, "init", db_session)
    assert "15" in result


@pytest.mark.asyncio
async def test_perform_roll_invalid_notation_returns_error(sample_character, db_session):
    result = await perform_roll(sample_character, "notadice", db_session)
    assert "Error" in result
