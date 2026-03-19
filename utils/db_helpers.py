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

    Args:
        db: An active SQLAlchemy session.
        interaction: The Discord interaction being handled.

    Returns:
        A ``(user, server)`` pair; either value may be ``None`` if the row
        does not exist yet.
    """
    user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
    server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
    return user, server


def get_active_party(db, user: Optional[User], server: Optional[Server]) -> Optional[Party]:
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
        db.query(Character)
        .filter_by(user=user, server=server, is_active=True)
        .first()
    )
