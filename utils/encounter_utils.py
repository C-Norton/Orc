"""Shared utilities for encounter-related commands."""

from typing import TYPE_CHECKING

import discord

from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

if TYPE_CHECKING:
    from models import Encounter, EncounterTurn, Party


def remove_enemy_turn_from_encounter(
    db,
    encounter: "Encounter",
    target_turn: "EncounterTurn",
) -> None:
    """Remove an enemy's EncounterTurn from the initiative order and re-index.

    Adjusts ``encounter.current_turn_index`` so the order stays coherent
    after the removal.  Flushes but does not commit the session.

    Args:
        db: An active SQLAlchemy session.
        encounter: The Encounter the turn belongs to.
        target_turn: The EncounterTurn to remove (must be an enemy turn).
    """
    all_turns_sorted = sorted(encounter.turns, key=lambda t: t.order_position)
    removed_order_pos = target_turn.order_position
    db.delete(target_turn)
    db.flush()

    remaining_turns = [t for t in all_turns_sorted if t.id != target_turn.id]
    for new_position, turn in enumerate(remaining_turns):
        turn.order_position = new_position

    new_turn_count = len(remaining_turns)
    if new_turn_count == 0:
        encounter.current_turn_index = 0
    elif removed_order_pos < encounter.current_turn_index:
        encounter.current_turn_index -= 1
    elif removed_order_pos == encounter.current_turn_index:
        encounter.current_turn_index = encounter.current_turn_index % new_turn_count
    # else removed_order_pos > current_turn_index: no change needed


async def notify_gms_hp_update(
    party: "Party",
    message: str,
    client: discord.Client,
    encounter: "Encounter",
) -> None:
    """Attempt to DM each GM of the party with an HP-update embed.

    The embed title shows the encounter name and the footer identifies the
    party, so GMs can immediately tell which encounter the update relates to.
    Failures (Forbidden, HTTPException, NotFound) are logged and silently
    skipped so that a DM failure never blocks the command response.

    Args:
        party: The Party whose GMs should be notified.
        message: The body text to include in the embed description.
        client: The Discord client used to fetch user objects.
        encounter: The Encounter generating the notification.
    """
    embed = discord.Embed(
        title=Strings.ENCOUNTER_GM_DM_EMBED_TITLE.format(encounter_name=encounter.name),
        description=message,
        color=discord.Color.dark_red(),
    )
    embed.set_footer(
        text=Strings.ENCOUNTER_GM_DM_EMBED_FOOTER.format(party_name=party.name)
    )
    for gm in party.gms:
        try:
            gm_discord_user = await client.fetch_user(int(gm.discord_id))
            await gm_discord_user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound) as exc:
            logger.warning(f"Could not DM GM {gm.discord_id}: {exc}")
