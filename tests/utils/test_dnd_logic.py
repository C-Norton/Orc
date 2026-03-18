"""Unit tests for utils.dnd_logic — stat modifiers, proficiency, and perform_roll.

Tests cover boundary cases for ability scores, JACK_OF_ALL_TRADES, EXPERTISE,
and edge cases in the perform_roll dispatcher.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User, Server, Character, ClassLevel, CharacterSkill
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.dnd_logic import get_stat_modifier, get_proficiency_bonus, perform_roll


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def base_character(db):
    """Level-5 character with all stats set to 10 (modifier 0)."""
    user = User(discord_id="10")
    server = Server(discord_id="20", name="S")
    db.add_all([user, server])
    db.flush()
    char = Character(
        name="Tester",
        user=user,
        server=server,
        is_active=True,
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db.add(char)
    db.flush()
    db.add(ClassLevel(character_id=char.id, class_name="Fighter", level=5))
    db.commit()
    db.refresh(char)
    return char


# ---------------------------------------------------------------------------
# get_stat_modifier — boundary values
# ---------------------------------------------------------------------------


def test_perform_roll_stat_boundary_1():
    """STR=1 → modifier=-5 (lowest possible ability score)."""
    assert get_stat_modifier(1) == -5


def test_perform_roll_stat_boundary_30():
    """STR=30 → modifier=+10 (maximum ability score in 5e)."""
    assert get_stat_modifier(30) == 10


def test_get_stat_modifier_10_is_zero():
    """STR=10 → modifier=0 (baseline)."""
    assert get_stat_modifier(10) == 0


def test_get_stat_modifier_none_returns_zero():
    """None ability score → modifier=0 (character stat not configured)."""
    assert get_stat_modifier(None) == 0


# ---------------------------------------------------------------------------
# get_proficiency_bonus — level thresholds
# ---------------------------------------------------------------------------


def test_get_proficiency_bonus_level_1():
    """Level 1 → proficiency bonus +2."""
    assert get_proficiency_bonus(1) == 2


def test_get_proficiency_bonus_level_5():
    """Level 5 → proficiency bonus +3."""
    assert get_proficiency_bonus(5) == 3


# ---------------------------------------------------------------------------
# perform_roll — JACK_OF_ALL_TRADES
# ---------------------------------------------------------------------------


async def test_perform_roll_joat_half_proficiency(mocker, base_character, db):
    """JACK_OF_ALL_TRADES on an untrained skill applies half proficiency (rounded down)."""
    # Level 5 → proficiency bonus = 3; half = 1 (floor)
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)

    # base_character has WIS=10 (modifier 0); skill Perception uses WIS
    char_skill = CharacterSkill(
        character_id=base_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.JACK_OF_ALL_TRADES,
    )
    db.add(char_skill)
    db.commit()

    result = await perform_roll(base_character, "Perception", db)

    # d20(10) + WIS mod(0) + half prof(1) = 11
    assert "11" in result


# ---------------------------------------------------------------------------
# perform_roll — EXPERTISE doubles proficiency
# ---------------------------------------------------------------------------


async def test_perform_roll_expertise_doubles_proficiency(mocker, base_character, db):
    """EXPERTISE on a skill applies 2× proficiency bonus."""
    # Level 5 → proficiency bonus = 3; expertise = 6
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)

    char_skill = CharacterSkill(
        character_id=base_character.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.EXPERTISE,
    )
    db.add(char_skill)
    db.commit()

    result = await perform_roll(base_character, "Perception", db)

    # d20(10) + WIS mod(0) + expertise(6) = 16
    assert "16" in result


# ---------------------------------------------------------------------------
# perform_roll — character with all-None stats falls through to raw dice
# ---------------------------------------------------------------------------


async def test_perform_roll_character_all_none_stats_raw_dice(mocker, db):
    """A character with no stats configured falls through to raw dice evaluation."""
    user = User(discord_id="99")
    server = Server(discord_id="88", name="S2")
    db.add_all([user, server])
    db.flush()
    char = Character(
        name="Unnamed",
        user=user,
        server=server,
        is_active=True,
        # All stats default to None
    )
    db.add(char)
    db.flush()
    db.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
    db.commit()
    db.refresh(char)

    mocker.patch("utils.dnd_logic.random.randint", return_value=4)

    result = await perform_roll(char, "1d6", db)

    assert "4" in result
