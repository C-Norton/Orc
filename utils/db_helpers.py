"""Shared database query helpers used across command modules.

These functions encapsulate the most frequently repeated DB lookup patterns so
that each command file does not need its own copy.
"""

from typing import Optional

import discord
from sqlalchemy import select

from models import Character, Party, Server, User, user_server_association


def resolve_user_server(
    db, interaction: discord.Interaction
) -> tuple[Optional[User], Optional[Server]]:
    """Look up the User and Server rows for a Discord interaction.

    Returns ``None`` for either value if the row does not exist yet.
    Prefer ``get_or_create_user_server`` in command handlers so that rows are
    created automatically on first use.

    Args:
        db: An active SQLAlchemy session.
        interaction: The Discord interaction being handled.

    Returns:
        A ``(user, server)`` pair; either value may be ``None``.
    """
    user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
    server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
    return user, server


def get_or_create_user_server(
    db, interaction: discord.Interaction
) -> tuple[User, Server]:
    """Return the User and Server rows for a Discord interaction, creating them
    if they do not exist yet.

    This is the preferred helper for command handlers.  It guarantees that both
    rows exist after the call so commands never need to handle a ``None`` user
    or server on first use.  The user-server association row is also created so
    that ``get_active_party`` works immediately.

    Args:
        db: An active SQLAlchemy session.
        interaction: The Discord interaction being handled.

    Returns:
        A ``(user, server)`` pair; both are always non-``None``.
    """
    discord_user_id = str(interaction.user.id)
    discord_guild_id = str(interaction.guild_id)

    user = db.query(User).filter_by(discord_id=discord_user_id).first()
    if user is None:
        user = User(discord_id=discord_user_id)
        db.add(user)
        db.flush()

    server = db.query(Server).filter_by(discord_id=discord_guild_id).first()
    if server is None:
        guild_name = getattr(interaction.guild, "name", discord_guild_id)
        server = Server(discord_id=discord_guild_id, name=guild_name)
        db.add(server)
        db.flush()

    if server not in user.servers:
        user.servers.append(server)
        db.flush()

    return user, server


def get_active_party(
    db, user: Optional[User], server: Optional[Server]
) -> Optional[Party]:
    """Return the user's active party on this server, or None.

    Returns ``None`` immediately if either ``user`` or ``server`` is ``None``,
    avoiding unnecessary DB queries when upstream lookups found no row.

    Args:
        db: An active SQLAlchemy session.
        user: The User row, or ``None``.
        server: The Server row, or ``None``.

    Returns:
        The active ``Party`` if one is set, otherwise ``None``.
    """
    if not user or not server:
        return None
    stmt = select(user_server_association.c.active_party_id).where(
        user_server_association.c.user_id == user.id,
        user_server_association.c.server_id == server.id,
    )
    result = db.execute(stmt).fetchone()
    if not result or result[0] is None:
        return None
    return db.get(Party, result[0])


def get_active_character(
    db, user: Optional[User], server: Optional[Server]
) -> Optional[Character]:
    """Return the user's active character on this server, or None.

    Returns ``None`` immediately if either ``user`` or ``server`` is ``None``.

    Args:
        db: An active SQLAlchemy session.
        user: The User row, or ``None``.
        server: The Server row, or ``None``.

    Returns:
        The active ``Character`` if one exists, otherwise ``None``.
    """
    if not user or not server:
        return None
    return (
        db.query(Character).filter_by(user=user, server=server, is_active=True).first()
    )
