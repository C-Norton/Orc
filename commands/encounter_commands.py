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
from utils.limits import MAX_ENEMIES_PER_ENCOUNTER
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
    lines = [
        Strings.ENCOUNTER_ORDER_HEADER.format(
            name=encounter.name, round_number=encounter.round_number
        ),
        "─" * 32,
    ]
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
        ping = f"<@{turn.character.user.discord_id}>"
        name = turn.character.name
    else:
        ping = " ".join(f"<@{gm.discord_id}>" for gm in encounter.party.gms)
        name = turn.enemy.name
    return Strings.ENCOUNTER_TURN_PING.format(ping=ping, name=name)


def register_encounter_commands(bot: commands.Bot) -> None:
    """Register the /encounter command group."""
    encounter_group = app_commands.Group(
        name="encounter", description="Manage combat encounters"
    )

    # ------------------------------------------------------------------
    # /encounter create
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="create", description="Create a new encounter for your active party"
    )
    @app_commands.describe(name="Name for this encounter (e.g. 'Goblin Ambush')")
    async def encounter_create(interaction: discord.Interaction, name: str) -> None:
        logger.debug(f"Command /encounter create called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_NO_ACTIVE_PARTY + " Use `/party active` first.",
                    ephemeral=True,
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENCOUNTER_CREATE, ephemeral=True
                )
                return

            if _open_encounter(db, party):
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ALREADY_OPEN, ephemeral=True
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
            logger.info(
                f"/encounter create completed for user {interaction.user.id}: '{name}'"
            )
            await interaction.response.send_message(
                Strings.ENCOUNTER_CREATED.format(name=name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /encounter enemy
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="enemy", description="Add an enemy to the current pending encounter"
    )
    @app_commands.describe(
        name="Enemy name (e.g. 'Goblin Chief')",
        initiative_modifier="Initiative modifier (DEX mod + any bonuses)",
        max_hp="Maximum hit points",
    )
    async def encounter_enemy(
        interaction: discord.Interaction,
        name: str,
        initiative_modifier: int,
        max_hp: int,
    ) -> None:
        logger.debug(f"Command /encounter enemy called by {interaction.user.id}")
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

            if not user or user not in party.gms:
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

            if len(encounter.enemies) >= MAX_ENEMIES_PER_ENCOUNTER:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_ENEMIES.format(limit=MAX_ENEMIES_PER_ENCOUNTER),
                    ephemeral=True,
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
            logger.info(
                f"/encounter enemy completed for user {interaction.user.id}: "
                f"'{name}' added to '{encounter.name}'"
            )
            await interaction.response.send_message(
                Strings.ENCOUNTER_ENEMY_ADDED.format(
                    name=name,
                    init_mod=initiative_modifier,
                    hp=max_hp,
                    encounter_name=encounter.name,
                )
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /encounter start
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="start", description="Roll initiative and begin the encounter"
    )
    async def encounter_start(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /encounter start called by {interaction.user.id}")
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

            participants: list[tuple[int, EncounterTurn]] = []

            for char in members:
                total, bonus = roll_initiative_for_character(char)
                participants.append((
                    total,
                    EncounterTurn(
                        encounter_id=encounter.id, character_id=char.id, initiative_roll=total
                    ),
                ))

            for enemy in encounter.enemies:
                roll = random.randint(1, 20) + enemy.initiative_modifier
                participants.append((
                    roll,
                    EncounterTurn(
                        encounter_id=encounter.id, enemy_id=enemy.id, initiative_roll=roll
                    ),
                ))

            participants.sort(
                key=lambda x: (x[0], 1 if x[1].character_id else 0), reverse=True
            )

            for pos, (_, turn) in enumerate(participants):
                turn.order_position = pos
                db.add(turn)

            encounter.status = EncounterStatus.ACTIVE
            encounter.current_turn_index = 0
            encounter.round_number = 1
            db.flush()

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
            logger.info(
                f"/encounter start completed: '{encounter.name}' is now ACTIVE"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /encounter next
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="next", description="End your turn and advance the initiative order"
    )
    async def encounter_next(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /encounter next called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
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
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
                return

            turns = sorted(encounter.turns, key=lambda t: t.order_position)
            current_turn = turns[encounter.current_turn_index]
            is_gm = user is not None and user in party.gms

            if current_turn.character_id:
                owner_discord_id = current_turn.character.user.discord_id
                is_owner = user and str(user.discord_id) == str(owner_discord_id)
            else:
                is_owner = False

            if not is_gm and not is_owner:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NEXT_TURN_DENIED, ephemeral=True
                )
                return

            next_index = encounter.current_turn_index + 1
            if next_index >= len(turns):
                encounter.round_number += 1
                encounter.current_turn_index = 0
            else:
                encounter.current_turn_index = next_index

            db.commit()
            db.refresh(encounter)

            order_msg = _build_order_message(encounter)
            original = await interaction.channel.fetch_message(int(encounter.message_id))
            await original.edit(content=order_msg)

            ping = _ping_for_turn(encounter)
            await interaction.followup.send(ping)
            await interaction.response.send_message(
                Strings.ENCOUNTER_TURN_ADVANCED, ephemeral=True
            )
            logger.info(
                f"/encounter next: '{encounter.name}' advanced to index "
                f"{encounter.current_turn_index} (round {encounter.round_number})"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /encounter end
    # ------------------------------------------------------------------

    @encounter_group.command(name="end", description="End the current encounter")
    async def encounter_end(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /encounter end called by {interaction.user.id}")
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

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENCOUNTER_END, ephemeral=True
                )
                return

            encounter.status = EncounterStatus.COMPLETE
            db.commit()
            logger.info(
                f"/encounter end completed: '{encounter.name}' marked COMPLETE"
            )
            await interaction.response.send_message(
                Strings.ENCOUNTER_ENDED.format(encounter_name=encounter.name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /encounter view
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="view", description="View the current encounter's initiative order"
    )
    async def encounter_view(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /encounter view called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _active_party_for_user(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
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
                    Strings.ENCOUNTER_NOT_ACTIVE, ephemeral=True
                )
                return

            turns = sorted(encounter.turns, key=lambda t: t.order_position)
            embed = discord.Embed(
                title=Strings.ENCOUNTER_VIEW_TITLE.format(name=encounter.name),
                description=Strings.ENCOUNTER_VIEW_DESC.format(
                    round_number=encounter.round_number
                ),
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
            logger.info(f"/encounter view served for '{encounter.name}'")
        finally:
            db.close()

    bot.tree.add_command(encounter_group)
