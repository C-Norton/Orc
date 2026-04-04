"""Commands for managing character Inspiration.

Inspiration is a 5e mechanic awarded by the GM (or automatically via the
Perkins crit rule) that lets a player roll with advantage on any d20 test.

Workflow::

    /inspiration grant [partymember]  — grant Inspiration (self or GM for others)
    /inspiration use [partymember]    — use Inspiration (self or GM for others)
    /inspiration status [partymember] — check Inspiration status
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from database import db_session
from models import Character, Party, Server, User
from utils.db_helpers import (
    get_active_character,
    get_active_party,
    get_or_create_user_server,
    resolve_user_server,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def _resolve_target(
    db: Session,
    user: User,
    server: Server,
    party: Party | None,
    partymember: str | None,
) -> tuple[Character | None, str | None]:
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
        partymember: str | None = None,
    ) -> None:
        """Grant Inspiration to a character.

        Players may grant Inspiration to their own active character.  GMs may
        grant it to any member of their active party by specifying *partymember*.
        """
        logger.debug(
            f"Command /inspiration grant called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        with db_session() as db:
            user, server = get_or_create_user_server(db, interaction)
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

    @inspiration_grant.autocomplete("partymember")
    async def inspiration_grant_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    @inspiration_group.command(
        name="use",
        description="Use Inspiration for yourself or a party member (GM only for others)",
    )
    @app_commands.describe(
        partymember="Party member to use Inspiration for (GM only; defaults to yourself)"
    )
    async def inspiration_use(
        interaction: discord.Interaction,
        partymember: str | None = None,
    ) -> None:
        """Use (spend) Inspiration for a character.

        Used when a player spends their Inspiration or when a GM needs to
        revoke it.  Players may only use their own; GMs may use any
        party member's.
        """
        logger.debug(
            f"Command /inspiration use called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        with db_session() as db:
            user, server = get_or_create_user_server(db, interaction)
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

    @inspiration_use.autocomplete("partymember")
    async def inspiration_use_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    @inspiration_group.command(
        name="status",
        description="Check whether yourself or a party member has Inspiration",
    )
    @app_commands.describe(partymember="Party member to check (defaults to yourself)")
    async def inspiration_status(
        interaction: discord.Interaction,
        partymember: str | None = None,
    ) -> None:
        """Display the current Inspiration state of a character.

        Anyone can check any party member's Inspiration status.
        """
        logger.debug(
            f"Command /inspiration status called by {interaction.user.id} "
            f"partymember={partymember!r}"
        )
        with db_session() as db:
            user, server = get_or_create_user_server(db, interaction)
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

            await interaction.response.send_message(msg)
            logger.info(
                f"/inspiration status for {char.name}: inspiration={char.inspiration}"
            )

    @inspiration_status.autocomplete("partymember")
    async def inspiration_status_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await _party_member_autocomplete(interaction, current)

    bot.tree.add_command(inspiration_group)


async def _party_member_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest names of characters in the user's active party."""
    with db_session() as db:
        # Use resolve_user_server (read-only) rather than get_or_create_user_server
        # to avoid creating DB rows on autocomplete keystrokes.
        user, server = resolve_user_server(db, interaction)
        if not user or not server:
            return []
        party = get_active_party(db, user, server)
        if not party:
            return []
        return [
            app_commands.Choice(name=c.name, value=c.name)
            for c in party.characters
            if current.lower() in c.name.lower()
        ][:25]
