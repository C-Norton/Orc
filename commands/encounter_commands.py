import random
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from database import SessionLocal
from models import User, Server, Party, PartySettings, Character, Encounter, Enemy, EncounterTurn
from enums.encounter_status import EncounterStatus
from enums.enemy_initiative_mode import EnemyInitiativeMode
from enums.enemy_placement_mode import EnemyPlacementMode
from utils.db_helpers import get_active_party, resolve_user_server
from utils.death_save_logic import character_is_dying
from utils.dnd_logic import roll_initiative_for_character, get_stat_modifier
from utils.encounter_utils import (
    check_and_auto_end_encounter,
    insert_enemy_turns_at_position,
    insert_enemy_turns_by_roll,
    remove_enemy_turn_from_encounter,
)
from utils.limits import MAX_ENEMIES_PER_ENCOUNTER
from utils.logging_config import get_logger
from utils.strings import Strings
from dice_roller import roll_dice

logger = get_logger(__name__)


def _get_or_create_party_settings(db, party: Party) -> PartySettings:
    """Return the PartySettings for a party, creating with defaults if absent.

    Args:
        db: An active SQLAlchemy session.
        party: The Party instance whose settings are needed.

    Returns:
        The existing or newly-created PartySettings for the party.
    """
    settings = db.query(PartySettings).filter_by(party_id=party.id).first()
    if settings is None:
        settings = PartySettings(party_id=party.id)
        db.add(settings)
        db.flush()
    return settings


def _validate_hp_format(value: str) -> None:
    """Validate a max_hp input string without rolling any dice.

    Checks that the value is either a positive integer string or a valid dice
    notation formula.  Does not consume any randomness.

    Raises:
        ValueError: If the format is unrecognised.  The exception message
            contains the original input for use in user-facing error messages.
    """
    import re as _re
    stripped_value = value.strip()
    if stripped_value.isdigit():
        if int(stripped_value) <= 0:
            raise ValueError(stripped_value)
        return
    # Accept standard dice notation: optional NdX, optional +/- modifier
    dice_pattern = _re.compile(r'^(\d+)?d(\d+)([+-]\d+)?$', _re.IGNORECASE)
    if not dice_pattern.match(stripped_value.replace(' ', '')):
        raise ValueError(stripped_value)


def _parse_hp_input(value: str) -> int:
    """Parse a max_hp input string into a resolved integer HP value.

    Accepts a flat integer string (e.g. ``"15"``) or a dice notation formula
    (e.g. ``"2d8+4"``).  The dice formula is rolled once to produce the value.

    Raises:
        ValueError: If the string is neither a valid integer nor valid dice
            notation.  The exception message contains the original input so
            callers can embed it in user-facing error messages.
    """
    stripped_value = value.strip()
    if stripped_value.isdigit():
        resolved_hp = int(stripped_value)
        if resolved_hp <= 0:
            raise ValueError(stripped_value)
        return resolved_hp
    try:
        _rolls, _modifier, total = roll_dice(stripped_value)
        return max(total, 1)
    except ValueError:
        raise ValueError(stripped_value)


def _create_enemies_for_encounter(
    db,
    encounter: Encounter,
    enemy_name: str,
    initiative_modifier: int,
    max_hp_str: str,
    count: int,
    ac: Optional[int],
) -> List[Enemy]:
    """Persist Enemy rows for an encounter and return them.

    Handles both single (``count == 1``) and bulk (``count > 1``) creation.
    Bulk enemies are named ``"<enemy_name> 1"`` through ``"<enemy_name> N"``.
    Calls ``db.flush()`` so IDs are available before the caller commits.

    Args:
        db: An active SQLAlchemy session.
        encounter: The encounter to attach enemies to.
        enemy_name: Base name for the enemy or group.
        initiative_modifier: Initiative modifier shared by all created enemies.
        max_hp_str: Flat integer string or dice formula (e.g. ``"2d8+4"``).
        count: Number of enemies to create.
        ac: Optional armor class value.

    Returns:
        The list of newly created and flushed ``Enemy`` instances.
    """
    enemies: List[Enemy] = []
    if count == 1:
        resolved_hp = _parse_hp_input(max_hp_str)
        enemy = Enemy(
            encounter_id=encounter.id,
            name=enemy_name,
            type_name=enemy_name,
            initiative_modifier=initiative_modifier,
            max_hp=resolved_hp,
            current_hp=resolved_hp,
            ac=ac,
        )
        db.add(enemy)
        enemies.append(enemy)
    else:
        for enemy_index in range(1, count + 1):
            resolved_hp = _parse_hp_input(max_hp_str)
            enemy = Enemy(
                encounter_id=encounter.id,
                name=f"{enemy_name} {enemy_index}",
                type_name=enemy_name,
                initiative_modifier=initiative_modifier,
                max_hp=resolved_hp,
                current_hp=resolved_hp,
                ac=ac,
            )
            db.add(enemy)
            enemies.append(enemy)
    db.flush()
    return enemies


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


def _active_encounter(db, party: Party) -> Optional[Encounter]:
    """Return the party's ACTIVE encounter, or None.

    Unlike ``_open_encounter``, this only returns encounters that have already
    been started (``EncounterStatus.ACTIVE``).

    Args:
        db: An active SQLAlchemy session.
        party: The party whose encounter is needed.

    Returns:
        The active ``Encounter`` if one exists, otherwise ``None``.
    """
    return (
        db.query(Encounter)
        .filter(
            Encounter.party_id == party.id,
            Encounter.status == EncounterStatus.ACTIVE,
        )
        .first()
    )


async def _require_active_encounter(
    db,
    interaction: discord.Interaction,
    no_party_msg: str = Strings.ENCOUNTER_NOT_ACTIVE,
    no_encounter_msg: str = Strings.ENCOUNTER_NOT_ACTIVE,
) -> tuple[Optional[User], Optional[Party], Optional[Encounter]]:
    """Resolve user, active party, and active encounter for a command handler.

    Sends an ephemeral error and returns ``(None, None, None)`` at the first
    missing piece so the caller can ``return`` immediately.  All three values
    are guaranteed non-``None`` when the returned encounter is non-``None``.

    Args:
        db: An active SQLAlchemy session.
        interaction: The Discord interaction being handled.
        no_party_msg: Error string sent when the user has no active party.
        no_encounter_msg: Error string sent when there is no active encounter.

    Returns:
        ``(user, party, encounter)`` on success, or ``(None, None, None)`` if
        any step fails (after sending the appropriate error response).
    """
    user, server = resolve_user_server(db, interaction)
    party = get_active_party(db, user, server)
    if not party:
        await interaction.response.send_message(no_party_msg, ephemeral=True)
        return None, None, None
    encounter = _active_encounter(db, party)
    if not encounter:
        await interaction.response.send_message(no_encounter_msg, ephemeral=True)
        return None, None, None
    return user, party, encounter


def _build_order_message(encounter: Encounter) -> str:
    """Render the initiative order as a Discord message string.

    Includes current HP for enemies and characters (when HP is set).
    """
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
            char = turn.character
            dying_suffix = ""
            if character_is_dying(char):
                dying_suffix = " " + Strings.DEATH_SAVE_COUNTER_DISPLAY.format(
                    successes=char.death_save_successes,
                    failures=char.death_save_failures,
                )
            label = f"{char.name} (Player)"
            if char.current_hp is not None and char.max_hp is not None:
                hp_part = f" — HP: {char.current_hp}/{char.max_hp}{dying_suffix}"
            else:
                hp_part = dying_suffix
        else:
            enemy = turn.enemy
            label = f"{enemy.name} (Enemy)"
            if enemy.current_hp is not None and enemy.max_hp is not None:
                hp_part = f" — HP: {enemy.current_hp}/{enemy.max_hp}"
            else:
                hp_part = ""
        arrow = "▶  " if is_current else "   "
        bold = "**" if is_current else ""
        lines.append(
            f"{arrow}{i + 1}. {bold}{label}{bold} — {turn.initiative_roll}{hp_part}"
        )
    lines.append("─" * 32)
    return "\n".join(lines)


def _ping_for_turn(encounter: Encounter) -> str:
    """Return the Discord ping string for whoever acts on the current turn.

    When a player character is dying, appends a death save prompt.
    """
    turns = sorted(encounter.turns, key=lambda t: t.order_position)
    turn = turns[encounter.current_turn_index]
    if turn.character_id:
        character = turn.character
        ping = f"<@{character.user.discord_id}>"
        name = character.name
        ping_message = Strings.ENCOUNTER_TURN_PING.format(ping=ping, name=name)
        if character_is_dying(character):
            ping_message += "\n" + Strings.DEATH_SAVE_TURN_PROMPT.format(
                char_name=character.name
            )
        return ping_message
    else:
        ping = " ".join(f"<@{gm.discord_id}>" for gm in encounter.party.gms)
        name = turn.enemy.name
        return Strings.ENCOUNTER_TURN_PING.format(ping=ping, name=name)


class EnemyPlacementView(discord.ui.View):
    """Ephemeral button menu for placing newly added enemies in an active encounter.

    Shown to the GM when ``/encounter enemy`` is called while an encounter is
    already ACTIVE.  No Enemy rows are written to the database until a button
    is clicked.  If the view times out without a selection, nothing is created.
    """

    def __init__(
        self,
        encounter_id: int,
        party_id: int,
        enemy_name: str,
        initiative_modifier: int,
        max_hp_str: str,
        count: int,
        ac: Optional[int],
    ) -> None:
        super().__init__(timeout=180)
        self.encounter_id = encounter_id
        self.party_id = party_id
        self.enemy_name = enemy_name
        self.initiative_modifier = initiative_modifier
        self.max_hp_str = max_hp_str
        self.count = count
        self.ac = ac
        self.message: Optional[discord.Message] = None

    def _build_enemy_description(self) -> str:
        """Return a short display string describing the enemy or group."""
        if self.count == 1:
            return f"**{self.enemy_name}**"
        return f"**{self.count}× {self.enemy_name}**"

    def _create_enemies(self, db, encounter: "Encounter") -> List[Enemy]:
        """Persist Enemy rows for this placement and return them.

        Delegates to the module-level ``_create_enemies_for_encounter`` using
        this view's stored parameters.  Called inside the button callback after
        the encounter has been re-verified as ACTIVE.
        """
        return _create_enemies_for_encounter(
            db,
            encounter,
            self.enemy_name,
            self.initiative_modifier,
            self.max_hp_str,
            self.count,
            self.ac,
        )

    def _roll_for_enemies(
        self, enemies: List[Enemy], initiative_mode: EnemyInitiativeMode
    ) -> List[tuple]:
        """Return ``(enemy, roll)`` pairs based on the party's initiative mode.

        SHARED and BY_TYPE both produce one shared roll for the entire batch
        (all new enemies share the same ``type_name`` since they come from a
        single ``/encounter enemy`` invocation).  INDIVIDUAL gives each enemy
        its own roll.
        """
        if initiative_mode in (EnemyInitiativeMode.SHARED, EnemyInitiativeMode.BY_TYPE):
            shared_roll = random.randint(1, 20) + self.initiative_modifier
            return [(enemy, shared_roll) for enemy in enemies]
        # INDIVIDUAL
        return [
            (enemy, random.randint(1, 20) + self.initiative_modifier)
            for enemy in enemies
        ]

    async def _place_enemies(
        self,
        interaction: discord.Interaction,
        placement: EnemyPlacementMode,
    ) -> None:
        """Create enemies and insert them into the encounter at the chosen position.

        Called by each button callback.  Opens its own DB session, re-verifies
        the encounter is still ACTIVE, creates the enemies, inserts the turns,
        commits, updates the public initiative message, and confirms to the GM.
        """
        self.stop()
        for child in self.children:
            child.disabled = True

        db = SessionLocal()
        try:
            encounter = db.get(Encounter, self.encounter_id)
            if not encounter or encounter.status != EncounterStatus.ACTIVE:
                await interaction.response.edit_message(
                    content=Strings.ENCOUNTER_NOT_ACTIVE,
                    view=None,
                )
                return

            party = db.get(Party, self.party_id)
            encounter_settings = _get_or_create_party_settings(db, party)
            initiative_mode = encounter_settings.initiative_mode

            enemies = self._create_enemies(db, encounter)
            all_turns_count = len(
                [t for t in encounter.turns]
            )

            if placement == EnemyPlacementMode.TOP:
                roll = random.randint(1, 20) + self.initiative_modifier
                enemies_with_rolls = [(enemy, roll) for enemy in enemies]
                insert_enemy_turns_at_position(db, encounter, enemies_with_rolls, 0)
                confirmation = Strings.ENCOUNTER_ENEMY_ADDED_TOP

            elif placement == EnemyPlacementMode.BOTTOM:
                roll = random.randint(1, 20) + self.initiative_modifier
                enemies_with_rolls = [(enemy, roll) for enemy in enemies]
                insert_enemy_turns_at_position(
                    db, encounter, enemies_with_rolls, all_turns_count
                )
                confirmation = Strings.ENCOUNTER_ENEMY_ADDED_BOTTOM

            elif placement == EnemyPlacementMode.AFTER_CURRENT:
                roll = random.randint(1, 20) + self.initiative_modifier
                enemies_with_rolls = [(enemy, roll) for enemy in enemies]
                insert_enemy_turns_at_position(
                    db, encounter, enemies_with_rolls, encounter.current_turn_index + 1
                )
                confirmation = Strings.ENCOUNTER_ENEMY_ADDED_AFTER_CURRENT

            else:  # EnemyPlacementMode.ROLL
                enemies_with_rolls = self._roll_for_enemies(enemies, initiative_mode)
                insert_enemy_turns_by_roll(db, encounter, enemies_with_rolls)
                confirmation = Strings.ENCOUNTER_ENEMY_ADDED_ROLLED

            db.commit()
            db.refresh(encounter)

            enemy_description = self._build_enemy_description()
            order_msg = _build_order_message(encounter)

            try:
                original_msg = await interaction.channel.fetch_message(
                    int(encounter.message_id)
                )
                await original_msg.edit(content=order_msg)
            except (discord.NotFound, discord.HTTPException) as exc:
                logger.warning(
                    f"EnemyPlacementView: could not update initiative message: {exc}"
                )

            await interaction.response.edit_message(
                content=confirmation.format(enemy_description=enemy_description),
                view=None,
            )
            await interaction.followup.send(
                Strings.ENCOUNTER_ENEMY_JOINED_PUBLIC.format(
                    enemy_description=enemy_description,
                    encounter_name=encounter.name,
                )
            )
            logger.info(
                f"EnemyPlacementView: {enemy_description} added to "
                f"'{encounter.name}' via {placement.value}"
            )
        finally:
            db.close()

    async def on_timeout(self) -> None:
        """Disable all buttons when the placement menu expires without a selection."""
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=Strings.ENCOUNTER_ENEMY_PLACEMENT_EXPIRED,
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass

    @discord.ui.button(label="Top of Initiative", style=discord.ButtonStyle.primary)
    async def top_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Place the enemy(ies) at position 1 in the initiative order."""
        await self._place_enemies(interaction, EnemyPlacementMode.TOP)

    @discord.ui.button(label="Bottom of Initiative", style=discord.ButtonStyle.secondary)
    async def bottom_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Place the enemy(ies) at the last position in the initiative order."""
        await self._place_enemies(interaction, EnemyPlacementMode.BOTTOM)

    @discord.ui.button(label="After Current Turn", style=discord.ButtonStyle.secondary)
    async def after_current_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Place the enemy(ies) immediately after the currently active turn."""
        await self._place_enemies(interaction, EnemyPlacementMode.AFTER_CURRENT)

    @discord.ui.button(label="Roll Initiative", style=discord.ButtonStyle.success)
    async def roll_initiative_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Roll initiative for the enemy(ies) and insert them in sorted order."""
        await self._place_enemies(interaction, EnemyPlacementMode.ROLL)


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
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

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
        name="enemy", description="Add one or more enemies to the current pending encounter"
    )
    @app_commands.describe(
        name="Enemy name (e.g. 'Goblin')",
        initiative_modifier="Initiative modifier (DEX mod + any bonuses)",
        max_hp="Hit points — flat number (e.g. 15) or dice formula (e.g. 2d8+4)",
        count="Number of enemies to add (default 1)",
        ac="Armor Class (optional)",
    )
    async def encounter_enemy(
        interaction: discord.Interaction,
        name: str,
        initiative_modifier: int,
        max_hp: str,
        count: int = 1,
        ac: Optional[int] = None,
    ) -> None:
        """Add one or more enemies to the current PENDING encounter.

        Supports flat HP values (``"15"``) or dice formulas (``"2d8+4"``).
        When count > 1 the enemies are named ``"<name> 1"`` through
        ``"<name> <count>"``, all sharing the same ``type_name``.
        """
        logger.debug(f"Command /encounter enemy called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

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

            # Validate the HP input format before any rolls or DB writes so the
            # user gets a clear error if the formula is malformed.  This check
            # does not consume any randomness.
            try:
                _validate_hp_format(max_hp)
            except ValueError:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_INVALID_HP.format(value=max_hp),
                    ephemeral=True,
                )
                return

            # Ceiling check: total after add must not exceed the limit.
            current_enemy_count = len(encounter.enemies)
            if current_enemy_count + count > MAX_ENEMIES_PER_ENCOUNTER:
                remaining_slots = MAX_ENEMIES_PER_ENCOUNTER - current_enemy_count
                enemy_word = "enemy" if count == 1 else "enemies"
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ENEMY_COUNT_OVER_LIMIT.format(
                        count=count,
                        enemy_word=enemy_word,
                        limit=MAX_ENEMIES_PER_ENCOUNTER,
                        remaining=remaining_slots,
                    ),
                    ephemeral=True,
                )
                return

            if encounter.status == EncounterStatus.ACTIVE:
                enemy_description = (
                    f"**{name}**" if count == 1 else f"**{count}× {name}**"
                )
                view = EnemyPlacementView(
                    encounter_id=encounter.id,
                    party_id=party.id,
                    enemy_name=name,
                    initiative_modifier=initiative_modifier,
                    max_hp_str=max_hp,
                    count=count,
                    ac=ac,
                )
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ENEMY_PLACEMENT_PROMPT.format(
                        encounter_name=encounter.name,
                        enemy_description=enemy_description,
                    ),
                    view=view,
                    ephemeral=True,
                )
                view.message = await interaction.original_response()
                logger.debug(
                    f"/encounter enemy: placement menu shown for '{name}' "
                    f"in active encounter '{encounter.name}'"
                )
                return

            created_enemies = _create_enemies_for_encounter(
                db, encounter, name, initiative_modifier, max_hp, count, ac
            )
            db.commit()

            if count == 1:
                enemy = created_enemies[0]
                ac_str = str(ac) if ac is not None else "—"
                logger.info(
                    f"/encounter enemy completed for user {interaction.user.id}: "
                    f"'{name}' added to '{encounter.name}'"
                )
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ENEMY_ADDED_SINGLE.format(
                        name=enemy.name,
                        encounter_name=encounter.name,
                        init_mod=initiative_modifier,
                        hp=enemy.max_hp,
                        ac_str=ac_str,
                    ),
                ephemeral=True)
            else:
                ac_part = f", AC: {ac}" if ac is not None else ""
                enemy_lines = "\n".join(
                    Strings.ENCOUNTER_ENEMY_BULK_LINE.format(
                        name=created_enemy.name,
                        hp=created_enemy.max_hp,
                        ac_part=ac_part,
                    )
                    for created_enemy in created_enemies
                )
                logger.info(
                    f"/encounter enemy completed for user {interaction.user.id}: "
                    f"{count}× '{name}' added to '{encounter.name}'"
                )
                await interaction.response.send_message(
                    Strings.ENCOUNTER_ENEMIES_ADDED_BULK.format(
                        count=count,
                        type_name=name,
                        encounter_name=encounter.name,
                        enemy_lines=enemy_lines,
                    ),ephemeral=True
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
            user, server = resolve_user_server(db, interaction)
            party = get_active_party(db, user, server)

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

            encounter_settings = _get_or_create_party_settings(db, party)
            initiative_mode = encounter_settings.initiative_mode

            if initiative_mode == EnemyInitiativeMode.SHARED:
                # All enemies share a single initiative roll.
                # Use the highest initiative_modifier among all enemies.
                shared_modifier = max(
                    (enemy.initiative_modifier for enemy in encounter.enemies), default=0
                )
                shared_roll = random.randint(1, 20) + shared_modifier
                for enemy in encounter.enemies:
                    participants.append((
                        shared_roll,
                        EncounterTurn(
                            encounter_id=encounter.id,
                            enemy_id=enemy.id,
                            initiative_roll=shared_roll,
                        ),
                    ))

            elif initiative_mode == EnemyInitiativeMode.BY_TYPE:
                # Enemies sharing the same type_name share one initiative roll.
                type_rolls: dict[str, int] = {}
                for enemy in encounter.enemies:
                    if enemy.type_name not in type_rolls:
                        type_rolls[enemy.type_name] = (
                            random.randint(1, 20) + enemy.initiative_modifier
                        )
                    roll = type_rolls[enemy.type_name]
                    participants.append((
                        roll,
                        EncounterTurn(
                            encounter_id=encounter.id,
                            enemy_id=enemy.id,
                            initiative_roll=roll,
                        ),
                    ))

            else:  # EnemyInitiativeMode.INDIVIDUAL
                for enemy in encounter.enemies:
                    roll = random.randint(1, 20) + enemy.initiative_modifier
                    participants.append((
                        roll,
                        EncounterTurn(
                            encounter_id=encounter.id,
                            enemy_id=enemy.id,
                            initiative_roll=roll,
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
            user, party, encounter = await _require_active_encounter(db, interaction)
            if encounter is None:
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
            await interaction.response.send_message(
                Strings.ENCOUNTER_TURN_ADVANCED, ephemeral=True
            )
            await interaction.followup.send(ping)
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
            user, party, encounter = await _require_active_encounter(
                db,
                interaction,
                no_party_msg=Strings.ERROR_NO_ACTIVE_PARTY,
                no_encounter_msg=Strings.ENCOUNTER_NO_ACTIVE_TO_END,
            )
            if encounter is None:
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
    # /encounter damage
    # ------------------------------------------------------------------

    @encounter_group.command(
        name="damage",
        description="Apply damage to an enemy in the initiative order (GM only)",
    )
    @app_commands.describe(
        position="The enemy's position number in the initiative order",
        damage="Amount of damage to deal",
    )
    async def encounter_damage(
        interaction: discord.Interaction,
        position: int,
        damage: int,
    ) -> None:
        """Apply damage to an enemy at the given initiative-order position.

        Automatically removes the enemy from the turn order when HP reaches 0
        and posts a public defeat announcement.
        """
        logger.debug(f"Command /encounter damage called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, party, encounter = await _require_active_encounter(db, interaction)
            if encounter is None:
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ENCOUNTER_DAMAGE, ephemeral=True
                )
                return

            if damage <= 0:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_DAMAGE_MUST_BE_POSITIVE, ephemeral=True
                )
                return

            turns = sorted(encounter.turns, key=lambda t: t.order_position)

            if position < 1 or position > len(turns):
                await interaction.response.send_message(
                    Strings.ENCOUNTER_DAMAGE_INVALID_POSITION.format(
                        position=position, count=len(turns)
                    ),
                    ephemeral=True,
                )
                return

            target_turn = turns[position - 1]

            if target_turn.character_id:
                await interaction.response.send_message(
                    Strings.ENCOUNTER_DAMAGE_NOT_ENEMY.format(position=position),
                    ephemeral=True,
                )
                return

            enemy = target_turn.enemy
            new_hp = max(0, enemy.current_hp - damage)
            enemy.current_hp = new_hp

            if new_hp == 0:
                remove_enemy_turn_from_encounter(db, encounter, target_turn)
                all_enemies_defeated = check_and_auto_end_encounter(db, encounter)
                db.commit()

                await interaction.response.send_message(
                    Strings.ENCOUNTER_DAMAGE_HP_UPDATE.format(
                        name=enemy.name,
                        damage=damage,
                        current_hp=0,
                        max_hp=enemy.max_hp,
                    ),
                    ephemeral=True,
                )
                await interaction.followup.send(
                    Strings.ENCOUNTER_DAMAGE_ENEMY_DEFEATED.format(name=enemy.name)
                )
                if all_enemies_defeated:
                    await interaction.followup.send(
                        Strings.ENCOUNTER_ALL_ENEMIES_DEFEATED.format(
                            encounter_name=encounter.name
                        )
                    )
                    logger.info(
                        f"/encounter damage: all enemies defeated, encounter '{encounter.name}' auto-ended"
                    )
                else:
                    logger.info(
                        f"/encounter damage: '{enemy.name}' defeated in '{encounter.name}'"
                    )
            else:
                db.commit()
                await interaction.response.send_message(
                    Strings.ENCOUNTER_DAMAGE_HP_UPDATE.format(
                        name=enemy.name,
                        damage=damage,
                        current_hp=new_hp,
                        max_hp=enemy.max_hp,
                    ),
                    ephemeral=True,
                )
                logger.info(
                    f"/encounter damage: '{enemy.name}' took {damage} damage, "
                    f"HP {new_hp}/{enemy.max_hp} in '{encounter.name}'"
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
        """Show the initiative order to all players.

        GMs also receive a second, ephemeral embed with full enemy details
        (current HP, max HP, AC, initiative modifier) regardless of the
        ``enemy_ac_public`` party setting.
        """
        logger.debug(f"Command /encounter view called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, party, encounter = await _require_active_encounter(db, interaction)
            if encounter is None:
                return

            settings = _get_or_create_party_settings(db, party)
            enemy_ac_public = settings.enemy_ac_public
            is_gm = user is not None and user in party.gms

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
                    char = turn.character
                    label = f"{char.name} (Player)"
                    if char.current_hp is not None and char.max_hp is not None:
                        hp_str = Strings.ENCOUNTER_VIEW_CHARACTER_HP.format(
                            current_hp=char.current_hp, max_hp=char.max_hp
                        )
                    else:
                        hp_str = Strings.ENCOUNTER_VIEW_CHARACTER_HP_UNKNOWN
                else:
                    enemy = turn.enemy
                    label = f"{enemy.name} (Enemy)"
                    if enemy.current_hp is not None and enemy.max_hp is not None:
                        if enemy_ac_public and enemy.ac is not None:
                            hp_str = Strings.ENCOUNTER_VIEW_ENEMY_HP_AC.format(
                                current_hp=enemy.current_hp,
                                max_hp=enemy.max_hp,
                                ac=enemy.ac,
                            )
                        else:
                            hp_str = Strings.ENCOUNTER_VIEW_ENEMY_HP.format(
                                current_hp=enemy.current_hp,
                                max_hp=enemy.max_hp,
                            )
                    else:
                        hp_str = ""
                prefix = "▶ " if is_current else ""
                field_value = (
                    f"Initiative: {turn.initiative_roll} | {hp_str}"
                    if hp_str
                    else f"Initiative: {turn.initiative_roll}"
                )
                embed.add_field(
                    name=f"{prefix}{i + 1}. {label}",
                    value=field_value,
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

            if is_gm:
                gm_embed = discord.Embed(
                    title=Strings.ENCOUNTER_VIEW_GM_DETAILS_TITLE.format(
                        name=encounter.name
                    ),
                    color=discord.Color.gold(),
                )
                for i, turn in enumerate(turns):
                    if turn.enemy_id:
                        enemy = turn.enemy
                        ac_str = str(enemy.ac) if enemy.ac is not None else "—"
                        gm_embed.add_field(
                            name=f"{i + 1}. {enemy.name}",
                            value=Strings.ENCOUNTER_VIEW_GM_ENEMY_VALUE.format(
                                current_hp=enemy.current_hp,
                                max_hp=enemy.max_hp,
                                ac_str=ac_str,
                                init_mod=enemy.initiative_modifier,
                            ),
                            inline=False,
                        )
                await interaction.followup.send(embed=gm_embed, ephemeral=True)

            logger.info(f"/encounter view served for '{encounter.name}'")
        finally:
            db.close()

    bot.tree.add_command(encounter_group)
