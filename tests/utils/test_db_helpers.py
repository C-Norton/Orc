"""Unit and integration tests for utils/db_helpers.py.

All tests use the shared in-memory DB fixtures from conftest.py and make no
network calls.  The `sample_active_party` fixture is reproduced here as a
local helper because it lives in tests/commands/conftest.py and is not
available to the utils test tree.
"""

import pytest
import discord
from sqlalchemy import insert, select

from models import Character, Party, Server, User, user_server_association
from utils.db_helpers import (
    get_active_character,
    get_active_party,
    get_or_create_user,
    get_or_create_user_server,
    purge_server_data,
    resolve_user_server,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _make_interaction(
    mocker, user_id: int = 111, guild_id: int = 222, guild_name: str = "Test Server"
):
    """Minimal interaction mock sufficient for db_helper tests."""
    interaction = mocker.Mock(spec=discord.Interaction)
    user = mocker.Mock()
    user.id = user_id
    interaction.user = user
    interaction.guild_id = guild_id
    guild = mocker.Mock()
    guild.name = guild_name
    interaction.guild = guild
    return interaction


@pytest.fixture
def sample_party(db_session, sample_user, sample_server):
    """A party with sample_user as GM on sample_server."""
    party = Party(name="The Fellowship", gms=[sample_user], server=sample_server)
    db_session.add(party)
    db_session.commit()
    db_session.refresh(party)
    return party


@pytest.fixture
def sample_active_party(db_session, sample_party, sample_user, sample_server):
    """Sets sample_party as the active party for sample_user on sample_server."""
    db_session.execute(
        insert(user_server_association).values(
            user_id=sample_user.id,
            server_id=sample_server.id,
            active_party_id=sample_party.id,
        )
    )
    db_session.commit()
    return sample_party


# ---------------------------------------------------------------------------
# resolve_user_server
# ---------------------------------------------------------------------------


def test_resolve_user_server_both_exist(db_session, sample_user, sample_server, mocker):
    """Returns existing rows when both user and server are in the DB."""
    interaction = _make_interaction(mocker, user_id=111, guild_id=222)
    user, server = resolve_user_server(db_session, interaction)
    assert user is not None
    assert user.discord_id == "111"
    assert server is not None
    assert server.discord_id == "222"


def test_resolve_user_server_neither_exist(db_session, mocker):
    """Returns (None, None) when neither row exists."""
    interaction = _make_interaction(mocker, user_id=9999, guild_id=8888)
    user, server = resolve_user_server(db_session, interaction)
    assert user is None
    assert server is None


def test_resolve_user_server_only_server_exists(db_session, sample_server, mocker):
    """Returns None for the missing user even when server row exists."""
    interaction = _make_interaction(mocker, user_id=9999, guild_id=222)
    user, server = resolve_user_server(db_session, interaction)
    assert user is None
    assert server is not None


def test_resolve_user_server_only_user_exists(db_session, sample_user, mocker):
    """Returns None for the missing server even when user row exists."""
    interaction = _make_interaction(mocker, user_id=111, guild_id=8888)
    user, server = resolve_user_server(db_session, interaction)
    assert user is not None
    assert server is None


# ---------------------------------------------------------------------------
# get_or_create_user
# ---------------------------------------------------------------------------


def test_get_or_create_user_creates_new_user(db_session):
    """Creates and returns a new user row when the discord_id is absent."""
    user = get_or_create_user(db_session, "55555")
    db_session.commit()
    assert user.discord_id == "55555"
    assert db_session.query(User).filter_by(discord_id="55555").count() == 1


def test_get_or_create_user_returns_existing_user(db_session, sample_user):
    """Returns the existing user without creating a duplicate."""
    user = get_or_create_user(db_session, "111")
    assert user.id == sample_user.id
    assert db_session.query(User).filter_by(discord_id="111").count() == 1


def test_get_or_create_user_is_idempotent(db_session):
    """Calling twice with the same ID does not produce duplicate rows."""
    user1 = get_or_create_user(db_session, "77777")
    db_session.commit()
    user2 = get_or_create_user(db_session, "77777")
    db_session.commit()
    assert user1.id == user2.id
    assert db_session.query(User).filter_by(discord_id="77777").count() == 1


# ---------------------------------------------------------------------------
# get_or_create_user_server
# ---------------------------------------------------------------------------


def test_get_or_create_user_server_creates_both_rows(db_session, mocker):
    """Creates both user and server rows on first use."""
    interaction = _make_interaction(
        mocker, user_id=444, guild_id=555, guild_name="NewGuild"
    )
    user, server = get_or_create_user_server(db_session, interaction)
    db_session.commit()
    assert user.discord_id == "444"
    assert server.discord_id == "555"
    assert server.name == "NewGuild"


def test_get_or_create_user_server_creates_association(db_session, mocker):
    """The user-server association row is created so membership is tracked."""
    interaction = _make_interaction(mocker, user_id=444, guild_id=555)
    user, server = get_or_create_user_server(db_session, interaction)
    db_session.commit()
    assert server in user.servers


def test_get_or_create_user_server_returns_existing_rows(
    db_session, sample_user, sample_server, mocker
):
    """Returns existing rows without creating duplicates."""
    interaction = _make_interaction(mocker, user_id=111, guild_id=222)
    user, server = get_or_create_user_server(db_session, interaction)
    assert user.id == sample_user.id
    assert server.id == sample_server.id
    assert db_session.query(User).filter_by(discord_id="111").count() == 1
    assert db_session.query(Server).filter_by(discord_id="222").count() == 1


def test_get_or_create_user_server_is_idempotent(
    db_session, sample_user, sample_server, mocker
):
    """Calling twice does not create extra rows or raise an integrity error."""
    interaction = _make_interaction(mocker, user_id=111, guild_id=222)
    get_or_create_user_server(db_session, interaction)
    db_session.commit()
    get_or_create_user_server(db_session, interaction)
    db_session.commit()
    assert db_session.query(User).filter_by(discord_id="111").count() == 1
    assert db_session.query(Server).filter_by(discord_id="222").count() == 1


# ---------------------------------------------------------------------------
# get_active_character
# ---------------------------------------------------------------------------


def test_get_active_character_returns_active(
    db_session, sample_user, sample_server, sample_character
):
    """Returns the active character when one exists."""
    assert sample_character.is_active is True  # precondition
    char = get_active_character(db_session, sample_user, sample_server)
    assert char is not None
    assert char.id == sample_character.id


def test_get_active_character_none_when_all_inactive(
    db_session, sample_user, sample_server, sample_character
):
    """Returns None when no character is marked active."""
    sample_character.is_active = False
    db_session.commit()
    char = get_active_character(db_session, sample_user, sample_server)
    assert char is None


def test_get_active_character_none_if_user_is_none(db_session, sample_server):
    """Returns None immediately without querying when user is None."""
    assert get_active_character(db_session, None, sample_server) is None


def test_get_active_character_none_if_server_is_none(db_session, sample_user):
    """Returns None immediately without querying when server is None."""
    assert get_active_character(db_session, sample_user, None) is None


def test_get_active_character_none_if_both_none(db_session):
    """Returns None when both user and server are None."""
    assert get_active_character(db_session, None, None) is None


def test_get_active_character_multiple_active_returns_first(
    db_session, sample_user, sample_server, sample_character
):
    """When an invariant violation produces multiple active characters, .first()
    is returned without raising — the invariant must be enforced at write time."""
    second_char = Character(
        name="SecondChar",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(second_char)
    db_session.commit()
    char = get_active_character(db_session, sample_user, sample_server)
    assert char is not None  # does not crash; returns one of the two


# ---------------------------------------------------------------------------
# get_active_party
# ---------------------------------------------------------------------------


def test_get_active_party_returns_active(
    db_session, sample_active_party, sample_user, sample_server
):
    """Returns the party when one is set as active."""
    party = get_active_party(db_session, sample_user, sample_server)
    assert party is not None
    assert party.id == sample_active_party.id


def test_get_active_party_none_when_no_association(
    db_session, sample_user, sample_server
):
    """Returns None when no user-server association row exists."""
    party = get_active_party(db_session, sample_user, sample_server)
    assert party is None


def test_get_active_party_none_when_active_party_id_is_null(
    db_session, sample_user, sample_server
):
    """Returns None when the association row exists but active_party_id is NULL."""
    db_session.execute(
        insert(user_server_association).values(
            user_id=sample_user.id,
            server_id=sample_server.id,
            active_party_id=None,
        )
    )
    db_session.commit()
    party = get_active_party(db_session, sample_user, sample_server)
    assert party is None


def test_get_active_party_none_if_user_is_none(db_session, sample_server):
    """Returns None immediately when user is None."""
    assert get_active_party(db_session, None, sample_server) is None


def test_get_active_party_none_if_server_is_none(db_session, sample_user):
    """Returns None immediately when server is None."""
    assert get_active_party(db_session, sample_user, None) is None


# ---------------------------------------------------------------------------
# purge_server_data
# ---------------------------------------------------------------------------


def test_purge_server_data_removes_server_row(db_session, sample_server):
    """The Server row itself is deleted after purge."""
    server_id = sample_server.id
    purge_server_data(db_session, sample_server)
    db_session.commit()
    assert db_session.query(Server).filter_by(id=server_id).first() is None


def test_purge_server_data_removes_characters(
    db_session, sample_character, sample_server
):
    """Characters belonging to the server are deleted."""
    server_id = sample_server.id
    purge_server_data(db_session, sample_server)
    db_session.commit()
    assert db_session.query(Character).filter_by(server_id=server_id).count() == 0


def test_purge_server_data_removes_parties(db_session, sample_party, sample_server):
    """Parties belonging to the server are deleted."""
    server_id = sample_server.id
    purge_server_data(db_session, sample_server)
    db_session.commit()
    assert db_session.query(Party).filter_by(server_id=server_id).count() == 0


def test_purge_server_data_removes_user_server_association(
    db_session, sample_user, sample_server
):
    """The user_server_association row for the server is removed."""
    db_session.execute(
        insert(user_server_association).values(
            user_id=sample_user.id,
            server_id=sample_server.id,
            active_party_id=None,
        )
    )
    db_session.commit()

    server_id = sample_server.id
    purge_server_data(db_session, sample_server)
    db_session.commit()

    remaining = db_session.execute(
        select(user_server_association).where(
            user_server_association.c.server_id == server_id
        )
    ).fetchall()
    assert remaining == []


def test_purge_server_data_preserves_other_servers(
    db_session, sample_server, sample_user
):
    """Purging one server does not delete data belonging to another server."""
    other_server = Server(discord_id="9999", name="Other Server")
    db_session.add(other_server)
    db_session.flush()
    other_char = Character(
        name="OtherChar",
        user=sample_user,
        server=other_server,
        is_active=True,
    )
    db_session.add(other_char)
    db_session.commit()

    purge_server_data(db_session, sample_server)
    db_session.commit()

    assert db_session.query(Character).filter_by(server_id=other_server.id).count() == 1
    assert db_session.query(Server).filter_by(id=other_server.id).first() is not None
