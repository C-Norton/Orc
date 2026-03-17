import random
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import select
from database import SessionLocal
from models import User, Server, Party, Character, Encounter, Enemy, EncounterTurn, user_server_association
from enums.encounter_status import EncounterStatus
from utils.dnd_logic import roll_initiative_for_character, get_stat_modifier
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def _active_party_for_user(db, user: User, server: Server) -> Optional[Party]:
    """Return the user's active party on this server, or None."""
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


def _open_encounter(db, party: Party) -> Optional[Encounter]:
    """Return the party's PENDING or ACTIVE encounter, if any."""
    return (
        db.query(Encounter)
        .filter(
            Encounter.party_id == party.id,
            Encounter.status.in_([EncounterStatus.PENDING, EncounterStatus.ACTIVE]),
        )
        .first()
    )


def _build_order_message(encounter: Encounter) -> str:
    """Render the initiative order as a Discord message string."""
    turns = sorted(encounter.turns, key=lambda t: t.order_position)
    lines = [Strings.ENCOUNTER_ORDER_HEADER.format(name=encounter.name, round_number=encounter.round_number), "─" * 32]
    for i, turn in enumerate(turns):
        is_current = i == encounter.current_turn_index
        if turn.character_id:
            label = f"{turn.character.name} (Player)"
        else:
            label = f"{turn.enemy.name} (Enemy)"
        arrow = "▶  " if is_current else "   "
        bold = "**" if is_current else ""
        lines.append(f"{arrow}{i + 1}. {bold}{label}{bold} — {turn.initiative_roll}")
    lines.append("─" * 32)
    return "\n".join(lines)


def _ping_for_turn(encounter: Encounter) -> str:
    """Return the Discord ping string for whoever acts on the current turn."""
    turns = sorted(encounter.turns, key=lambda t: t.order_position)
    turn = turns[encounter.current_turn_index]
    if turn.character_id:
        discord_id = turn.character.user.discord_id
        name = turn.character.name
    else:
        discord_id = encounter.party.gm.discord_id
        name = turn.enemy.name
    return Strings.ENCOUNTER_TURN_PING.format(discord_id=discord_id, name=name)


def register_encounter_commands(bot: commands.Bot) -> None:

    # ------------------------------------------------------------------
    # /create_encounter
    # ------------------------------------------------------------------

    @bot.tree.command(name="create_encounter", description="Create a new encounter for your active party")
    @app_commands.describe(name="Name for this encounter (e.g. 'Goblin Ambush')")
    async def create_encounter(interaction: discord.Interaction, name: str) -> None:
        logger.debug(f"Command /create_encounter called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_NO_ACTIVE_PARTY + " Use `/active_party` first.", ephemeral=True
                )
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENCOUNTER_CREATE, ephemeral=True
                )
                return

            if _open_encounter(db, party):
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ALREADY_OPEN,
                    ephemeral=True,
                )
                return

            encounter = Encounter(
                name=name,
                party_id=party.id,
                server_id=server.id,
                status=EncounterStatus.PENDING,
            )
            db.add(encounter)
            db.commit()
            logger.info(f"/create_encounter completed for user {interaction.user.id}: '{name}'")
            await interaction.response.send_message(
                Strings.ENCOUNTER_CREATED.format(name=name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /add_enemy
    # ------------------------------------------------------------------

    @bot.tree.command(name="add_enemy", description="Add an enemy to the current pending encounter")
    @app_commands.describe(
        name="Enemy name (e.g. 'Goblin Chief')",
        initiative_modifier="Initiative modifier (DEX mod + any bonuses)",
        max_hp="Maximum hit points",
    )
    async def add_enemy(
        interaction: discord.Interaction,
        name: str,
        initiative_modifier: int,
        max_hp: int,
    ) -> None:
        logger.debug(f"Command /add_enemy called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True
                )
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENEMY_ADD, ephemeral=True
                )
                return

            encounter = _open_encounter(db, party)
            if not encounter:
                await interaction.response.send_message(
                    Strings.ERROR_NO_PENDING_ENCOUNTER, ephemeral=True
                )
                return

            if encounter.status != EncounterStatus.PENDING:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NOT_STARTED, ephemeral=True
                )
                return

            enemy = Enemy(
                encounter_id=encounter.id,
                name=name,
                initiative_modifier=initiative_modifier,
                max_hp=max_hp,
            )
            db.add(enemy)
            db.commit()
            logger.info(f"/add_enemy completed for user {interaction.user.id}: '{name}' added to '{encounter.name}'")
            await interaction.response.send_message(
                Strings.ENCOUNTER_ENEMY_ADDED.format(name=name, init_mod=initiative_modifier, hp=max_hp, encounter_name=encounter.name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /start_encounter
    # ------------------------------------------------------------------

    @bot.tree.command(name="start_encounter", description="Roll initiative and begin the encounter")
    async def start_encounter(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /start_encounter called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True)
                return

            encounter = _open_encounter(db, party)
            if not encounter:
                await interaction.response.send_message(
                    Strings.ERROR_NO_PENDING_ENCOUNTER, ephemeral=True
                )
                return

            if encounter.status == EncounterStatus.ACTIVE:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ALREADY_STARTED, ephemeral=True
                )
                return

            if not encounter.enemies:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NO_ENEMIES, ephemeral=True
                )
                return

            members = party.characters
            if not members:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_PARTY_NO_MEMBERS, ephemeral=True
                )
                return

            await interaction.response.defer()

            # Roll initiative for every participant and collect (roll, turn_obj)
            participants: list[tuple[int, EncounterTurn]] = []

            for char in members:
                total, bonus = roll_initiative_for_character(char)
                participants.append((
                    total,
                    EncounterTurn(encounter_id=encounter.id, character_id=char.id, initiative_roll=total),
                ))

            for enemy in encounter.enemies:
                roll = random.randint(1, 20) + enemy.initiative_modifier
                participants.append((
                    roll,
                    EncounterTurn(encounter_id=encounter.id, enemy_id=enemy.id, initiative_roll=roll),
                ))

            # Sort descending by roll; characters beat enemies on a tie
            participants.sort(key=lambda x: (x[0], 1 if x[1].character_id else 0), reverse=True)

            for pos, (_, turn) in enumerate(participants):
                turn.order_position = pos
                db.add(turn)

            encounter.status = EncounterStatus.ACTIVE
            encounter.current_turn_index = 0
            encounter.round_number = 1
            db.flush()  # populate turn.character / turn.enemy before building message

            # Re-query encounter with relationships populated
            db.refresh(encounter)
            for t in encounter.turns:
                if t.character_id:
                    db.refresh(t.character)
                else:
                    db.refresh(t.enemy)

            order_msg = _build_order_message(encounter)
            sent = await interaction.followup.send(order_msg)

            encounter.message_id = str(sent.id)
            encounter.channel_id = str(interaction.channel_id)
            db.commit()

            ping = _ping_for_turn(encounter)
            await interaction.followup.send(ping)
            logger.info(f"/start_encounter completed: '{encounter.name}' is now ACTIVE")
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /next_turn
    # ------------------------------------------------------------------

    @bot.tree.command(name="next_turn", description="End your turn and advance initiative order")
    async def next_turn(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /next_turn called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            # Find the active encounter on this server
            encounter = (
                db.query(Encounter)
                .join(Party, Encounter.party_id == Party.id)
                .join(Server, Encounter.server_id == Server.id)
                .filter(
                    Server.discord_id == str(interaction.guild_id),
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )

            if not encounter:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
                return

            turns = sorted(encounter.turns, key=lambda t: t.order_position)
            current_turn = turns[encounter.current_turn_index]
            party = encounter.party
            is_gm = user and party.gm_id == user.id

            # Determine if the caller is allowed to advance
            if current_turn.character_id:
                owner_discord_id = current_turn.character.user.discord_id
                is_owner = user and str(user.discord_id) == str(owner_discord_id)
            else:
                # Enemy turn — only GM can advance
                is_owner = False

            if not is_gm and not is_owner:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NEXT_TURN_DENIED,
                    ephemeral=True,
                )
                return

            # Advance the turn counter
            next_index = encounter.current_turn_index + 1
            if next_index >= len(turns):
                encounter.round_number += 1
                encounter.current_turn_index = 0
            else:
                encounter.current_turn_index = next_index

            db.commit()
            db.refresh(encounter)

            # Edit the original order message
            order_msg = _build_order_message(encounter)
            original = await interaction.channel.fetch_message(int(encounter.message_id))
            await original.edit(content=order_msg)

            # Ping the next participant
            ping = _ping_for_turn(encounter)
            await interaction.followup.send(ping)
            await interaction.response.send_message(
                Strings.ENCOUNTER_TURN_ADVANCED, ephemeral=True
            )
            logger.info(
                f"/next_turn: '{encounter.name}' advanced to index {encounter.current_turn_index} "
                f"(round {encounter.round_number})"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /end_encounter
    # ------------------------------------------------------------------

    @bot.tree.command(name="end_encounter", description="End the current encounter")
    async def end_encounter(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /end_encounter called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True)
                return

            encounter = (
                db.query(Encounter)
                .filter(
                    Encounter.party_id == party.id,
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )

            if not encounter:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NO_ACTIVE_TO_END, ephemeral=True
                )
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENCOUNTER_END, ephemeral=True
                )
                return

            encounter.status = EncounterStatus.COMPLETE
            db.commit()
            logger.info(f"/end_encounter completed: '{encounter.name}' marked COMPLETE")
            await interaction.response.send_message(
                Strings.ENCOUNTER_ENDED.format(encounter_name=encounter.name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /view_encounter
    # ------------------------------------------------------------------

    @bot.tree.command(name="view_encounter", description="View the current encounter's initiative order")
    async def view_encounter(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /view_encounter called by {interaction.user.id}")
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            encounter = (
                db.query(Encounter)
                .join(Party, Encounter.party_id == Party.id)
                .join(Server, Encounter.server_id == Server.id)
                .filter(
                    Server.discord_id == str(interaction.guild_id),
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )

            if not encounter:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
                return

            turns = sorted(encounter.turns, key=lambda t: t.order_position)
            embed = discord.Embed(
                title=Strings.ENCOUNTER_VIEW_TITLE.format(name=encounter.name),
                description=Strings.ENCOUNTER_VIEW_DESC.format(round_number=encounter.round_number),
                color=discord.Color.dark_red(),
            )
            for i, turn in enumerate(turns):
                is_current = i == encounter.current_turn_index
                if turn.character_id:
                    label = f"{turn.character.name} (Player)"
                else:
                    label = f"{turn.enemy.name} (Enemy)"
                prefix = "▶ " if is_current else ""
                embed.add_field(
                    name=f"{prefix}{i + 1}. {label}",
                    value=f"Initiative: {turn.initiative_roll}",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)
            logger.info(f"/view_encounter served for '{encounter.name}'")
        finally:
            db.close()
