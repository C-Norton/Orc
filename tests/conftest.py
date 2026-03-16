import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, MagicMock
import discord

from models import Base, User, Server, Character
from enums.skill_proficiency_status import SkillProficiencyStatus


@pytest.fixture(scope="function")
def engine():
    """In-memory SQLite with StaticPool so all sessions share one connection."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def db_session(session_factory):
    session = session_factory()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Discord interaction mock
# ---------------------------------------------------------------------------

def make_interaction(user_id=111, guild_id=222, guild_name="Test Server", username="TestUser"):
    """Build a mock discord.Interaction. Usable both as a helper and via the
    `interaction` fixture below."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.type = discord.InteractionType.application_command

    user = MagicMock()
    user.id = user_id
    user.display_name = username
    user.__str__ = MagicMock(return_value=f"{username}#{user_id}")
    interaction.user = user

    guild = MagicMock()
    guild.id = guild_id
    guild.name = guild_name
    interaction.guild = guild
    interaction.guild_id = guild_id

    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.namespace = MagicMock()

    return interaction


@pytest.fixture
def interaction():
    return make_interaction()


# ---------------------------------------------------------------------------
# Seeded DB fixtures
# user_id=111 and guild_id=222 match the defaults in make_interaction so
# commands can find these records when processing a default interaction.
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user(db_session):
    user = User(discord_id="111")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_server(db_session):
    server = Server(discord_id="222", name="Test Server")
    db_session.add(server)
    db_session.commit()
    db_session.refresh(server)
    return server


@pytest.fixture
def sample_character(db_session, sample_user, sample_server):
    """Active character with all core stats set. Level 5 → proficiency +3."""
    char = Character(
        name="Aldric",
        user=sample_user,
        server=sample_server,
        is_active=True,
        level=5,
        strength=16,       # mod +3
        dexterity=14,      # mod +2
        constitution=15,   # mod +2
        intelligence=10,   # mod  0
        wisdom=12,         # mod +1
        charisma=8,        # mod -1
        st_prof_strength=True,
        st_prof_constitution=True,
    )
    db_session.add(char)
    db_session.commit()
    db_session.refresh(char)
    return char


@pytest.fixture
def sample_character_no_stats(db_session, sample_user, sample_server):
    """Active character whose core stats have never been set (all None)."""
    char = Character(
        name="Unnamed",
        user=sample_user,
        server=sample_server,
        is_active=True,
        level=1,
    )
    db_session.add(char)
    db_session.commit()
    db_session.refresh(char)
    return char
