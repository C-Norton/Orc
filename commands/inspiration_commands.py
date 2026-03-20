"""Commands for managing character Inspiration.

Inspiration is a 5e mechanic awarded by the GM (or automatically via the
Perkins crit rule) that lets a player roll with advantage on any d20 test.

Workflow::

    /inspiration grant [partymember]  — grant Inspiration (self or GM for others)
    /inspiration remove [partymember] — remove Inspiration (self or GM for others)
    /inspiration status [partymember] — check Inspiration status
"""

from __future__ import annotations

from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database import SessionLocal
from models import Character, Party, Server, User, user_server_association
from utils.db_helpers import get_active_character, get_active_party, resolve_user_server
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def _resolve_target(
    db, user: User, server: Server, party: Optional[Party], partymember: Optional[str]
) -> tuple[Optional[Character], Optional[str]]:
    """Return ``(character, error_message)`` for the target of an inspiration command.

    When *partymember* is None the caller's own active character is returned.
    When *partymember* is provided the caller must be a GM of their active party.
    Returns ``(None, error_string)`` on any validation failure.
    """
    if partymember is None:
        char = get_active_character(db, user, server)
        if not char:
            return None, Strings.CHARACTER_NOT_FOUND
        return char, None

    # Targeting a named character — must be in the active party
    if not party:
        return None, Strings.ERROR_NO_ACTIVE_PARTY
    char = next((c for c in party.characters if c.name == partymember), None)
    if not char:
        return None, Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember)
    # Players may manage inspiration for their own characters (active or inactive).
    # Only targeting another player's character requires GM status.
    if char.user_id != user.id and user not in party.gms:
        return None, Strings.ERROR_GM_ONLY_INSPIRATION
    return char, None


def register_inspiration_commands(bot: commands.Bot) -> None:
    """Register the ``/inspiration`` command group."""
    inspiration_group = app_commands.Group(
        name="inspiration",
        description="Grant, remove, or check Inspiration for a character",
    )

    @inspiration_group.command(
        name="grant",
        description="Grant Inspiration to yourself or a party member (GM only for others)",
    )
    @app_commands.describe(
        partymember="Party member to grant Inspiration to (GM only; defaults to yourself)"
    )
    async def inspiration_grant(
        interaction: discord.Interaction,
        partymember: Optional[str] = None,
    ) -> None:
        """Grant Inspiration to a character.

        Players may grant Inspiration to their own active character.  GMs may
        grant it to any member of their active party by specifying *partymember*.
        """
        logger.debug(
            f"Command /inspiration grant called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

            char, error = _resolve_target(db, user, server, party, partymember)
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return

            if char.inspiration:
                await interaction.response.send_message(
                    Strings.INSPIRATION_ALREADY_HAS.format(char_name=char.name),
                    ephemeral=True,
                )
                return

            char.inspiration = True
            db.commit()
            logger.info(
                f"/inspiration grant: {char.name} granted Inspiration "
                f"by user {interaction.user.id}"
            )
            await interaction.response.send_message(
                Strings.INSPIRATION_GRANTED.format(char_name=char.name)
            )
        finally:
            db.close()

    @inspiration_grant.autocomplete("partymember")
    async def inspiration_grant_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    @inspiration_group.command(
        name="remove",
        description="Remove Inspiration from yourself or a party member (GM only for others)",
    )
    @app_commands.describe(
        partymember="Party member to remove Inspiration from (GM only; defaults to yourself)"
    )
    async def inspiration_remove(
        interaction: discord.Interaction,
        partymember: Optional[str] = None,
    ) -> None:
        """Remove Inspiration from a character.

        Used when a player spends their Inspiration or when a GM needs to
        revoke it.  Players may only remove their own; GMs may remove any
        party member's.
        """
        logger.debug(
            f"Command /inspiration remove called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

            char, error = _resolve_target(db, user, server, party, partymember)
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return

            if not char.inspiration:
                await interaction.response.send_message(
                    Strings.INSPIRATION_NOT_HELD.format(char_name=char.name),
                    ephemeral=True,
                )
                return

            char.inspiration = False
            db.commit()
            logger.info(
                f"/inspiration remove: {char.name} Inspiration removed "
                f"by user {interaction.user.id}"
            )
            await interaction.response.send_message(
                Strings.INSPIRATION_REMOVED.format(char_name=char.name)
            )
        finally:
            db.close()

    @inspiration_remove.autocomplete("partymember")
    async def inspiration_remove_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    @inspiration_group.command(
        name="status",
        description="Check whether yourself or a party member has Inspiration",
    )
    @app_commands.describe(partymember="Party member to check (defaults to yourself)")
    async def inspiration_status(
        interaction: discord.Interaction,
        partymember: Optional[str] = None,
    ) -> None:
        """Display the current Inspiration state of a character.

        Anyone can check any party member's Inspiration status.
        """
        logger.debug(
            f"Command /inspiration status called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

            if partymember is None:
                char = get_active_character(db, user, server)
                if not char:
                    await interaction.response.send_message(
                        Strings.CHARACTER_NOT_FOUND, ephemeral=True
                    )
                    return
            else:
                if not party:
                    await interaction.response.send_message(
                        Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True
                    )
                    return
                char = next(
                    (c for c in party.characters if c.name == partymember), None
                )
                if not char:
                    await interaction.response.send_message(
                        Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember),
                        ephemeral=True,
                    )
                    return

            if char.inspiration:
                msg = Strings.INSPIRATION_STATUS_HAS.format(char_name=char.name)
            else:
                msg = Strings.INSPIRATION_STATUS_NONE.format(char_name=char.name)

            await interaction.response.send_message(msg, ephemeral=True)
            logger.info(
                f"/inspiration status for {char.name}: inspiration={char.inspiration}"
            )
        finally:
            db.close()

    @inspiration_status.autocomplete("partymember")
    async def inspiration_status_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    bot.tree.add_command(inspiration_group)


async def _party_member_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """Suggest names of characters in the user's active party."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = (
            db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        )
        if not user or not server:
            return []
        stmt = select(user_server_association.c.active_party_id).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id,
        )
        result = db.execute(stmt).fetchone()
        if not result or result[0] is None:
            return []
        party = db.get(Party, result[0])
        if not party:
            return []
        return [
            app_commands.Choice(name=c.name, value=c.name)
            for c in party.characters
            if current.lower() in c.name.lower()
        ][:25]
    finally:
        db.close()
