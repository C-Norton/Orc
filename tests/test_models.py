import pytest
from sqlalchemy.exc import IntegrityError

from models import User, Server, Character, CharacterSkill, Attack, Party
from enums.skill_proficiency_status import SkillProficiencyStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(db, discord_id="100"):
    u = User(discord_id=discord_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def make_server(db, discord_id="200"):
    s = Server(discord_id=discord_id, name="Test Server")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def make_character(db, user, server, name="Hero", active=True):
    c = Character(
        name=name, user=user, server=server, is_active=active, level=1,
        strength=10, dexterity=10, constitution=10,
        intelligence=10, wisdom=10, charisma=10,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

def test_user_created_successfully(db_session):
    user = make_user(db_session)
    assert user.id is not None
    assert user.discord_id == "100"


def test_user_duplicate_discord_id_raises(db_session):
    make_user(db_session, "dup")
    with pytest.raises(IntegrityError):
        make_user(db_session, "dup")


# ---------------------------------------------------------------------------
# Character uniqueness
# ---------------------------------------------------------------------------

def test_character_unique_name_per_user_and_server(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    make_character(db_session, user, server, name="Dupe")
    with pytest.raises(IntegrityError):
        make_character(db_session, user, server, name="Dupe")


def test_same_name_allowed_on_different_servers(db_session):
    user = make_user(db_session)
    s1 = make_server(db_session, "S1")
    s2 = make_server(db_session, "S2")
    make_character(db_session, user, s1, name="Hero")
    char2 = make_character(db_session, user, s2, name="Hero")
    assert char2.id is not None


# ---------------------------------------------------------------------------
# Cascade deletes
# ---------------------------------------------------------------------------

def test_delete_character_cascades_to_skills(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    char = make_character(db_session, user, server)
    skill = CharacterSkill(
        character_id=char.id,
        skill_name="Perception",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()

    db_session.delete(char)
    db_session.commit()

    remaining = db_session.query(CharacterSkill).filter_by(character_id=char.id).all()
    assert remaining == []


def test_delete_character_cascades_to_attacks(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    char = make_character(db_session, user, server)
    attack = Attack(character_id=char.id, name="Sword", hit_modifier=5, damage_formula="1d8+3")
    db_session.add(attack)
    db_session.commit()

    db_session.delete(char)
    db_session.commit()

    remaining = db_session.query(Attack).filter_by(character_id=char.id).all()
    assert remaining == []


# ---------------------------------------------------------------------------
# Attack uniqueness
# ---------------------------------------------------------------------------

def test_attack_unique_name_per_character(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    char = make_character(db_session, user, server)
    db_session.add(Attack(character_id=char.id, name="Sword", hit_modifier=5, damage_formula="1d8"))
    db_session.commit()
    db_session.add(Attack(character_id=char.id, name="Sword", hit_modifier=3, damage_formula="1d6"))
    with pytest.raises(IntegrityError):
        db_session.commit()


# ---------------------------------------------------------------------------
# CharacterSkill enum storage
# ---------------------------------------------------------------------------

def test_character_skill_stores_proficiency_enum(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    char = make_character(db_session, user, server)
    skill = CharacterSkill(
        character_id=char.id,
        skill_name="Stealth",
        proficiency=SkillProficiencyStatus.EXPERTISE,
    )
    db_session.add(skill)
    db_session.commit()

    fetched = db_session.query(CharacterSkill).filter_by(character_id=char.id).first()
    assert fetched.proficiency == SkillProficiencyStatus.EXPERTISE


# ---------------------------------------------------------------------------
# Party uniqueness
# ---------------------------------------------------------------------------

def test_party_unique_name_per_server(db_session):
    user = make_user(db_session)
    server = make_server(db_session)
    db_session.add(Party(name="The Fellowship", gm=user, server=server))
    db_session.commit()
    db_session.add(Party(name="The Fellowship", gm=user, server=server))
    with pytest.raises(IntegrityError):
        db_session.commit()
