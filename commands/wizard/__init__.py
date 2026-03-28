"""Character creation wizard package.

Public API (re-exported for use by section views, modals, and hub_view):

    start_character_creation — launch the wizard from ``/character create``
    _show_hub                — navigate back to the hub (used by section views / modals)
    _finish_wizard           — commit the wizard to the DB (used by hub_view)
"""

from __future__ import annotations

import discord

from commands.wizard.completion import _finish_wizard
from commands.wizard.hub_view import HubView, _build_hub_embed, _show_hub
from commands.wizard.state import WizardState
from utils.logging_config import get_logger

logger = get_logger(__name__)

__all__ = ["start_character_creation", "_show_hub", "_finish_wizard"]


async def start_character_creation(interaction: discord.Interaction) -> None:
    """Launch the character creation wizard hub."""
    logger.debug(
        f"Command /character create called by {interaction.user} "
        f"(ID: {interaction.user.id}) in guild {interaction.guild_id}"
    )
    wizard_state = WizardState(
        user_discord_id=str(interaction.user.id),
        guild_discord_id=str(interaction.guild_id),
        guild_name=getattr(interaction.guild, "name", str(interaction.guild_id)),
    )
    embed = _build_hub_embed(wizard_state)
    view = HubView(wizard_state)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
