"""Shared ORM base class and association tables for the ORC bot."""

from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def enum_values(enum_cls) -> list[str]:
    """Return the string values of an enum class for use as SQLAlchemy values_callable.

    Use this wherever a non-str Enum needs to store its ``.value`` in the
    database rather than the member name::

        SAEnum(MyEnum, values_callable=enum_values)
    """
    return [e.value for e in enum_cls]


# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------

# Per-user-per-server state: tracks which party is active for a user on a
# given server.  ``active_party_id`` makes this a hybrid join/settings table.
user_server_association = Table(
    "user_server",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("server_id", Integer, ForeignKey("servers.id")),
    Column("active_party_id", Integer, ForeignKey("parties.id", ondelete="SET NULL")),
)

# Many-to-many: characters belong to parties.
party_character_association = Table(
    "party_character",
    Base.metadata,
    Column("party_id", Integer, ForeignKey("parties.id")),
    Column("character_id", Integer, ForeignKey("characters.id")),
)

# Many-to-many: users designated as GMs for a party.
party_gm_association = Table(
    "party_gm",
    Base.metadata,
    Column("party_id", Integer, ForeignKey("parties.id", ondelete="CASCADE")),
    Column("user_id", Integer, ForeignKey("users.id")),
)
