"""Tests for purge_server_data in utils/db_helpers.py."""

import pytest
from sqlalchemy import select

from models import (
    Attack,
    Character,
    ClassLevel,
    CharacterSkill,
    Encounter,
    Enemy,
    Party,
    PartySettings,
    Server,
    User,
    user_server_association,
)
from models.base import party_character_association, party_gm_association
from enums.encounter_status import EncounterStatus
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.db_helpers import purge_server_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(db, discord_id="100", name="Test Guild") -> Server:
    server = Server(discord_id=discord_id, name=name)
    db.add(server)
    db.flush()
    return server


def _make_user(db, discord_id="999") -> User:
    user = User(discord_id=discord_id)
    db.add(user)
    db.flush()
    return user


def _make_character(db, user, server, name="Hero") -> Character:
    char = Character(name=name, user=user, server=server, is_active=True)
    db.add(char)
    db.flush()
    db.add(ClassLevel(character_id=char.id, class_name="Fighter", level=1))
    db.flush()
    db.refresh(char)
    return char


def _make_party(db, server, name="Party") -> Party:
    party = Party(name=name, server=server)
    db.add(party)
    db.flush()
    return party


def _make_encounter(db, party, server, name="Dungeon") -> Encounter:
    encounter = Encounter(
        name=name,
        party_id=party.id,
        server_id=server.id,
        status=EncounterStatus.PENDING,
    )
    db.add(encounter)
    db.flush()
    return encounter


def _make_enemy(db, encounter, name="Goblin") -> Enemy:
    enemy = Enemy(
        encounter_id=encounter.id,
        name=name,
        type_name="goblin",
        initiative_modifier=0,
        max_hp=5,
        current_hp=5,
    )
    db.add(enemy)
    db.flush()
    return enemy


# ---------------------------------------------------------------------------
# Server record itself
# ---------------------------------------------------------------------------


def test_purge_removes_server_record(db_session):
    server = _make_server(db_session)
    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Server).filter_by(discord_id="100").first() is None


def test_purge_server_not_in_db_is_noop(db_session):
    """Purge on a freshly-created (but not yet committed) server should work."""
    other_server = _make_server(db_session, discord_id="999", name="Other")
    db_session.commit()

    server = _make_server(db_session, discord_id="100")
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    # The other server is unaffected
    assert db_session.query(Server).filter_by(discord_id="999").first() is not None


# ---------------------------------------------------------------------------
# Character cascade
# ---------------------------------------------------------------------------


def test_purge_removes_characters(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    _make_character(db_session, user, server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Character).filter_by(server_id=server.id).count() == 0


def test_purge_cascades_to_character_skills(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    char = _make_character(db_session, user, server)
    skill = CharacterSkill(
        character_id=char.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(CharacterSkill).filter_by(character_id=char.id).count() == 0


def test_purge_cascades_to_attacks(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    char = _make_character(db_session, user, server)
    db_session.add(
        Attack(character_id=char.id, name="Sword", hit_modifier=3, damage_formula="1d8")
    )
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Attack).filter_by(character_id=char.id).count() == 0


def test_purge_cascades_to_class_levels(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    char = _make_character(db_session, user, server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(ClassLevel).filter_by(character_id=char.id).count() == 0


# ---------------------------------------------------------------------------
# Party cascade
# ---------------------------------------------------------------------------


def test_purge_removes_parties(db_session):
    server = _make_server(db_session)
    _make_party(db_session, server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Party).filter_by(server_id=server.id).count() == 0


def test_purge_cascades_to_party_settings(db_session):
    server = _make_server(db_session)
    party = _make_party(db_session, server)
    db_session.add(PartySettings(party_id=party.id))
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(PartySettings).filter_by(party_id=party.id).count() == 0


def test_purge_cascades_to_encounters(db_session):
    server = _make_server(db_session)
    party = _make_party(db_session, server)
    _make_encounter(db_session, party, server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Encounter).filter_by(server_id=server.id).count() == 0


def test_purge_cascades_to_enemies(db_session):
    server = _make_server(db_session)
    party = _make_party(db_session, server)
    encounter = _make_encounter(db_session, party, server)
    enemy = _make_enemy(db_session, encounter)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Enemy).filter_by(id=enemy.id).count() == 0


# ---------------------------------------------------------------------------
# Association table cleanup
# ---------------------------------------------------------------------------


def test_purge_removes_user_server_association(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    user.servers.append(server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    rows = db_session.execute(
        select(user_server_association).where(
            user_server_association.c.server_id == server.id
        )
    ).fetchall()
    assert rows == []


def test_purge_removes_party_character_association(db_session):
    user = _make_user(db_session)
    server = _make_server(db_session)
    char = _make_character(db_session, user, server)
    party = _make_party(db_session, server)
    party.characters.append(char)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    rows = db_session.execute(
        select(party_character_association).where(
            party_character_association.c.party_id == party.id
        )
    ).fetchall()
    assert rows == []


def test_purge_removes_party_gm_association(db_session):
    gm_user = _make_user(db_session, discord_id="GM1")
    server = _make_server(db_session)
    party = _make_party(db_session, server)
    party.gms.append(gm_user)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    rows = db_session.execute(
        select(party_gm_association).where(party_gm_association.c.party_id == party.id)
    ).fetchall()
    assert rows == []


# ---------------------------------------------------------------------------
# Isolation — other servers are not affected
# ---------------------------------------------------------------------------


def test_purge_does_not_affect_other_server_characters(db_session):
    user = _make_user(db_session)
    server_a = _make_server(db_session, discord_id="A", name="Server A")
    server_b = _make_server(db_session, discord_id="B", name="Server B")
    _make_character(db_session, user, server_a, name="HeroA")
    char_b = _make_character(db_session, user, server_b, name="HeroB")
    db_session.commit()

    purge_server_data(db_session, server_a)
    db_session.commit()

    surviving = db_session.query(Character).filter_by(id=char_b.id).first()
    assert surviving is not None
    assert surviving.name == "HeroB"


def test_purge_does_not_affect_other_server_parties(db_session):
    server_a = _make_server(db_session, discord_id="A", name="Server A")
    server_b = _make_server(db_session, discord_id="B", name="Server B")
    _make_party(db_session, server_a, name="Party A")
    party_b = _make_party(db_session, server_b, name="Party B")
    db_session.commit()

    purge_server_data(db_session, server_a)
    db_session.commit()

    assert db_session.query(Party).filter_by(id=party_b.id).first() is not None


def test_purge_does_not_remove_users(db_session):
    """Users themselves must survive — they may exist across many servers."""
    user = _make_user(db_session)
    server = _make_server(db_session)
    user.servers.append(server)
    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(User).filter_by(discord_id="999").first() is not None


# ---------------------------------------------------------------------------
# Full combined scenario
# ---------------------------------------------------------------------------


def test_purge_full_scenario(db_session):
    """Server with user, character (with attack + skill), party with encounter and enemy."""
    user = _make_user(db_session)
    server = _make_server(db_session)
    user.servers.append(server)

    char = _make_character(db_session, user, server)
    db_session.add(
        Attack(character_id=char.id, name="Axe", hit_modifier=4, damage_formula="1d6")
    )
    db_session.add(
        CharacterSkill(
            character_id=char.id,
            skill_name="Athletics",
            proficiency=SkillProficiencyStatus.PROFICIENT,
        )
    )

    party = _make_party(db_session, server)
    party.characters.append(char)
    party.gms.append(user)
    db_session.add(PartySettings(party_id=party.id))

    encounter = _make_encounter(db_session, party, server)
    _make_enemy(db_session, encounter)

    db_session.commit()

    purge_server_data(db_session, server)
    db_session.commit()

    assert db_session.query(Server).filter_by(id=server.id).first() is None
    assert db_session.query(Character).filter_by(server_id=server.id).count() == 0
    assert db_session.query(Party).filter_by(server_id=server.id).count() == 0
    assert db_session.query(Encounter).filter_by(server_id=server.id).count() == 0
    # User survives
    assert db_session.query(User).filter_by(discord_id="999").first() is not None
