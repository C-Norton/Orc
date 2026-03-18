"""Shared utilities for encounter-related commands."""

from typing import TYPE_CHECKING

import discord

from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

if TYPE_CHECKING:
    from models import Encounter, EncounterTurn, Enemy, Party


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


def check_and_auto_end_encounter(db, encounter: "Encounter") -> bool:
    """End the encounter automatically if no enemy turns remain.

    Queries for any remaining ``EncounterTurn`` rows tied to an enemy in this
    encounter.  If none exist the encounter status is set to ``COMPLETE``.
    Flushes but does not commit the session.

    Args:
        db: An active SQLAlchemy session.
        encounter: The Encounter to inspect.

    Returns:
        ``True`` if the encounter was ended, ``False`` if enemies remain.
    """
    from models import EncounterTurn

    remaining = (
        db.query(EncounterTurn)
        .filter(
            EncounterTurn.encounter_id == encounter.id,
            EncounterTurn.enemy_id.isnot(None),
        )
        .count()
    )
    if remaining == 0:
        from enums.encounter_status import EncounterStatus

        encounter.status = EncounterStatus.COMPLETE
        db.flush()
        return True
    return False


def insert_enemy_turns_at_position(
    db,
    encounter: "Encounter",
    enemies_with_rolls: "list[tuple[Enemy, int]]",
    insert_position: int,
) -> None:
    """Insert new enemy turns at a specific position, shifting subsequent turns.

    All turns at or after ``insert_position`` are shifted right by the number
    of new enemies.  ``encounter.current_turn_index`` is incremented when the
    insertion point falls at or before it so the same combatant remains active.
    Flushes but does not commit the session.

    Args:
        db: An active SQLAlchemy session.
        encounter: The active Encounter to insert turns into.
        enemies_with_rolls: Pairs of ``(Enemy, initiative_roll)`` to insert.
        insert_position: The ``order_position`` at which the first new turn
            should land (0 = top, ``len(turns)`` = bottom, etc.).
    """
    from models import EncounterTurn

    all_turns = sorted(encounter.turns, key=lambda t: t.order_position)
    count = len(enemies_with_rolls)

    for turn in all_turns:
        if turn.order_position >= insert_position:
            turn.order_position += count

    for offset, (enemy, initiative_roll) in enumerate(enemies_with_rolls):
        new_turn = EncounterTurn(
            encounter_id=encounter.id,
            enemy_id=enemy.id,
            initiative_roll=initiative_roll,
            order_position=insert_position + offset,
        )
        db.add(new_turn)

    if insert_position <= encounter.current_turn_index:
        encounter.current_turn_index += count

    db.flush()


def insert_enemy_turns_by_roll(
    db,
    encounter: "Encounter",
    enemies_with_rolls: "list[tuple[Enemy, int]]",
) -> None:
    """Merge new enemy turns into the initiative order by their initiative roll.

    New enemies are sorted into the existing order using the same tiebreaking
    rules as ``/encounter start``: higher roll goes first; on ties, player
    characters precede enemies; among new enemies of equal roll the original
    insertion order is preserved.  ``encounter.current_turn_index`` is updated
    to keep the same combatant active after the re-index.
    Flushes but does not commit the session.

    Args:
        db: An active SQLAlchemy session.
        encounter: The active Encounter to merge turns into.
        enemies_with_rolls: Pairs of ``(Enemy, initiative_roll)`` to insert.
    """
    from models import EncounterTurn

    all_turns = sorted(encounter.turns, key=lambda t: t.order_position)
    current_turn = all_turns[encounter.current_turn_index] if all_turns else None

    # (initiative_roll, is_character, tiebreak_position, turn_object)
    combined: list[tuple[int, int, int, "EncounterTurn"]] = [
        (turn.initiative_roll, 1 if turn.character_id else 0, turn.order_position, turn)
        for turn in all_turns
    ]

    new_turns: list["EncounterTurn"] = []
    for enemy, roll in enemies_with_rolls:
        new_turn = EncounterTurn(
            encounter_id=encounter.id,
            enemy_id=enemy.id,
            initiative_roll=roll,
            order_position=0,  # placeholder; reassigned below
        )
        db.add(new_turn)
        new_turns.append(new_turn)
        # New enemies go after existing entries of equal roll (is_character=0,
        # tiebreak > any existing order_position).
        combined.append((roll, 0, len(all_turns) + len(new_turns), new_turn))

    combined.sort(key=lambda x: (-x[0], -x[1], x[2]))

    for new_position, (_, _, _, turn) in enumerate(combined):
        turn.order_position = new_position

    if current_turn is not None:
        encounter.current_turn_index = next(
            pos for pos, (_, _, _, turn) in enumerate(combined) if turn is current_turn
        )

    db.flush()


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
