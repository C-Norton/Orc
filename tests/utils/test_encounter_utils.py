"""Unit tests for utils.encounter_utils — remove, reindex, and insert logic.

These tests create minimal in-memory database objects to exercise the pure
utility functions without going through Discord command handlers.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User, Server, Party, Encounter, Enemy, EncounterTurn
from enums.encounter_status import EncounterStatus
from utils.encounter_utils import (
    remove_enemy_turn_from_encounter,
    insert_enemy_turns_by_roll,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def engine():
    """Shared-connection in-memory SQLite for utility tests."""
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
    """Fresh session for each test."""
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def minimal_encounter(db):
    """A minimal ACTIVE encounter with no turns, owned by a throwaway party."""
    user = User(discord_id="1")
    server = Server(discord_id="2", name="S")
    db.add_all([user, server])
    db.flush()
    party = Party(name="P", server=server, gms=[user])
    db.add(party)
    db.flush()
    encounter = Encounter(
        name="Test",
        party_id=party.id,
        server_id=server.id,
        status=EncounterStatus.ACTIVE,
        current_turn_index=0,
        round_number=1,
    )
    db.add(encounter)
    db.commit()
    db.refresh(encounter)
    return encounter


def _add_enemy_turn(db, encounter, name, roll, position):
    """Helper: create an Enemy and its EncounterTurn, returning the turn."""
    enemy = Enemy(
        encounter_id=encounter.id,
        name=name,
        type_name=name,
        initiative_modifier=0,
        max_hp=10,
        current_hp=10,
    )
    db.add(enemy)
    db.flush()
    turn = EncounterTurn(
        encounter_id=encounter.id,
        enemy_id=enemy.id,
        initiative_roll=roll,
        order_position=position,
    )
    db.add(turn)
    db.flush()
    return turn


def _add_char_turn(db, encounter, roll, position):
    """Helper: create a Character with a User/Server and its EncounterTurn."""
    user = User(discord_id=str(position + 100))
    server = db.query(Server).first()
    db.add(user)
    db.flush()
    from models import Character, ClassLevel

    char = Character(
        name=f"Hero{position}",
        user=user,
        server=server,
        is_active=True,
    )
    db.add(char)
    db.flush()
    db.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
    turn = EncounterTurn(
        encounter_id=encounter.id,
        character_id=char.id,
        initiative_roll=roll,
        order_position=position,
    )
    db.add(turn)
    db.flush()
    return turn


# ---------------------------------------------------------------------------
# remove_enemy_turn_from_encounter — reindex positions
# ---------------------------------------------------------------------------


def test_remove_enemy_turn_adjusts_positions(db, minimal_encounter):
    """Removing turn at index 1 of 3 → remaining turns get positions 0 and 1."""
    t0 = _add_enemy_turn(db, minimal_encounter, "A", roll=20, position=0)
    t1 = _add_enemy_turn(db, minimal_encounter, "B", roll=15, position=1)
    t2 = _add_enemy_turn(db, minimal_encounter, "C", roll=10, position=2)
    minimal_encounter.current_turn_index = 2  # "C" is active
    db.commit()
    db.refresh(minimal_encounter)

    remove_enemy_turn_from_encounter(db, minimal_encounter, t1)
    db.commit()

    remaining = (
        db.query(EncounterTurn)
        .filter_by(encounter_id=minimal_encounter.id)
        .order_by(EncounterTurn.order_position)
        .all()
    )
    assert len(remaining) == 2
    positions = [t.order_position for t in remaining]
    assert positions == [0, 1]
    # "C" was at position 2; removal of position 1 means current_turn_index
    # decrements from 2 to 1.
    assert minimal_encounter.current_turn_index == 1


def test_remove_enemy_turn_last_in_list(db, minimal_encounter):
    """Removing the last turn leaves earlier turns untouched."""
    t0 = _add_enemy_turn(db, minimal_encounter, "A", roll=20, position=0)
    t1 = _add_enemy_turn(db, minimal_encounter, "B", roll=10, position=1)
    minimal_encounter.current_turn_index = 0
    db.commit()
    db.refresh(minimal_encounter)

    remove_enemy_turn_from_encounter(db, minimal_encounter, t1)
    db.commit()

    remaining = (
        db.query(EncounterTurn).filter_by(encounter_id=minimal_encounter.id).all()
    )
    assert len(remaining) == 1
    assert remaining[0].order_position == 0
    # Removing turn at position 1 (> current index 0) → index unchanged
    assert minimal_encounter.current_turn_index == 0


def test_remove_enemy_turn_only_turn(db, minimal_encounter):
    """Removing the only turn leaves an empty list and resets index to 0."""
    turn = _add_enemy_turn(db, minimal_encounter, "A", roll=15, position=0)
    minimal_encounter.current_turn_index = 0
    db.commit()
    db.refresh(minimal_encounter)

    remove_enemy_turn_from_encounter(db, minimal_encounter, turn)
    db.commit()

    remaining = (
        db.query(EncounterTurn).filter_by(encounter_id=minimal_encounter.id).all()
    )
    assert remaining == []
    assert minimal_encounter.current_turn_index == 0


# ---------------------------------------------------------------------------
# insert_enemy_turns_by_roll — tiebreaking and ordering
# ---------------------------------------------------------------------------


def test_insert_enemy_turns_by_roll_tiebreak_enemy_last(db, minimal_encounter):
    """On equal roll, existing character turn precedes newly inserted enemy turn."""
    char_turn = _add_char_turn(db, minimal_encounter, roll=15, position=0)
    minimal_encounter.current_turn_index = 0
    db.commit()
    db.refresh(minimal_encounter)

    enemy = Enemy(
        encounter_id=minimal_encounter.id,
        name="Rival",
        type_name="Rival",
        initiative_modifier=0,
        max_hp=5,
        current_hp=5,
    )
    db.add(enemy)
    db.flush()

    insert_enemy_turns_by_roll(db, minimal_encounter, [(enemy, 15)])
    db.commit()

    turns = (
        db.query(EncounterTurn)
        .filter_by(encounter_id=minimal_encounter.id)
        .order_by(EncounterTurn.order_position)
        .all()
    )
    assert len(turns) == 2
    # Character should be at position 0 (higher priority on tie), enemy at 1
    assert turns[0].character_id is not None
    assert turns[1].enemy_id is not None


def test_insert_enemy_turns_mixed_order(db, minimal_encounter):
    """New enemy with higher roll goes before existing lower-roll character turn."""
    _add_char_turn(db, minimal_encounter, roll=10, position=0)
    minimal_encounter.current_turn_index = 0
    db.commit()
    db.refresh(minimal_encounter)

    high_enemy = Enemy(
        encounter_id=minimal_encounter.id,
        name="FastFoe",
        type_name="FastFoe",
        initiative_modifier=0,
        max_hp=8,
        current_hp=8,
    )
    db.add(high_enemy)
    db.flush()

    insert_enemy_turns_by_roll(db, minimal_encounter, [(high_enemy, 18)])
    db.commit()

    turns = (
        db.query(EncounterTurn)
        .filter_by(encounter_id=minimal_encounter.id)
        .order_by(EncounterTurn.order_position)
        .all()
    )
    # Enemy rolls 18, character rolls 10 → enemy should be position 0
    assert turns[0].enemy_id == high_enemy.id
    assert turns[1].character_id is not None
