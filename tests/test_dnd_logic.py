import pytest

from utils.dnd_logic import get_stat_modifier, get_proficiency_bonus, perform_roll
from models import CharacterSkill
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.hp_logic import set_max_hp, apply_damage, apply_healing, apply_temp_hp

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
    # STR 16 → +3; d20 fixed at 10 → total 13
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "strength", db_session)
    assert "Strength Check" in result
    assert "13" in result


@pytest.mark.asyncio
async def test_perform_roll_stat_abbreviation(mocker, sample_character, db_session):
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "str", db_session)
    assert "Strength Check" in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_not_proficient(
    mocker, sample_character, db_session
):
    # WIS 12 → +1; not proficient in WIS save; d20=10 → total 11
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "wisdom save", db_session)
    assert "Wisdom Save" in result
    assert "11" in result


@pytest.mark.asyncio
async def test_perform_roll_saving_throw_proficient(
    mocker, sample_character, db_session
):
    # STR 16 → +3; proficient (level 5 → prof +3); d20=10 → total 16
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "strength save", db_session)
    assert "Strength Save" in result
    assert "16" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_not_proficient(mocker, sample_character, db_session):
    # Perception → WIS → +1; no proficiency; d20=10 → total 11
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "Perception", db_session)
    assert "Perception" in result
    assert "11" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_proficient(mocker, sample_character, db_session):
    # Add Perception proficiency; WIS+1 + prof+3 = +4; d20=10 → 14
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "Perception", db_session)
    assert "14" in result


@pytest.mark.asyncio
async def test_perform_roll_skill_expertise(mocker, sample_character, db_session):
    # Expertise: WIS+1 + 2*prof+6 = +7; d20=10 → 17
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.EXPERTISE,
    )
    db_session.add(skill)
    db_session.commit()
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "Perception", db_session)
    assert "17" in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_dex_when_no_bonus(
    mocker, sample_character, db_session
):
    # No initiative_bonus set → uses DEX mod +2; d20=10 → 12
    sample_character.initiative_bonus = None
    db_session.commit()
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "initiative", db_session)
    assert "Initiative" in result
    assert "12" in result


@pytest.mark.asyncio
async def test_perform_roll_initiative_uses_override_bonus(
    mocker, sample_character, db_session
):
    # initiative_bonus=5 overrides dex mod; d20=10 → 15
    sample_character.initiative_bonus = 5
    db_session.commit()
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    result = await perform_roll(sample_character, "init", db_session)
    assert "15" in result


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


@pytest.mark.parametrize(
    "current,temp,damage,exp_current,exp_temp",
    [
        (30, 0, 10, 20, 0),  # plain damage
        (30, 5, 3, 30, 2),  # damage absorbed by temp HP
        (30, 5, 8, 27, 0),  # damage exceeds temp HP, bleeds into current
        (
            5,
            0,
            10,
            0,
            0,
        ),  # Damage exceeds current HP — clamped to 0 (massive damage check is in the command handler).
        (30, 0, 0, 30, 0),  # zero damage is a no-op
    ],
)
def test_apply_damage(current, temp, damage, exp_current, exp_temp):
    new_current, new_temp = apply_damage(current, temp, damage)
    assert new_current == exp_current
    assert new_temp == exp_temp


@pytest.mark.parametrize(
    "current,max_hp,heal,expected",
    [
        (20, 30, 5, 25),  # normal heal
        (20, 30, 20, 30),  # heal capped at max
        (0, 30, 30, 30),  # full heal from 0
    ],
)
def test_apply_healing(current, max_hp, heal, expected):
    assert apply_healing(current, max_hp, heal) == expected


def test_apply_temp_hp_replaces_lower():
    # Temp HP does not stack — take the higher value
    assert apply_temp_hp(current_temp=5, new_temp=10) == 10
    assert apply_temp_hp(current_temp=10, new_temp=5) == 10


def test_apply_temp_hp_cannot_be_negative():
    assert apply_temp_hp(current_temp=0, new_temp=-1) == 0
    assert apply_temp_hp(current_temp=5, new_temp=-1) == 5


def test_set_max_hp():
    assert set_max_hp(10) == 10
    with pytest.raises(ValueError):
        set_max_hp(0)
    with pytest.raises(ValueError):
        set_max_hp(-1)
