import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import update, select, insert
from database import SessionLocal
from models import (
    User,
    Server,
    Character,
    Party,
    PartySettings,
    Encounter,
    EncounterTurn,
    user_server_association,
)
from enums.crit_rule import CritRule
from enums.death_save_nat20_mode import DeathSaveNat20Mode
from enums.encounter_status import EncounterStatus
from enums.enemy_initiative_mode import EnemyInitiativeMode
from utils.db_helpers import (
    get_active_party,
    get_or_create_user,
    get_or_create_user_server,
)
from utils.dnd_logic import perform_roll
from utils.limits import (
    MAX_GM_PARTIES_PER_USER,
    MAX_CHARACTERS_PER_PARTY,
    MAX_PARTIES_PER_SERVER,
)
from utils.logging_config import get_logger
from utils.strings import Strings
from commands.party_views import (
    ConfirmCharacterRemoveView,
    ConfirmPartyDeleteView,
    ConfirmSelfGMRemoveView,
    PartyListView,
)

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


def _lookup_party(db, party_name: str, server_id: int) -> Optional[Party]:
    """Return the Party with the given name in the given server, or None."""
    return db.query(Party).filter_by(name=party_name, server_id=server_id).first()


def _is_gm(user: Optional[User], party: Party) -> bool:
    """Return True if user is a GM of the party."""
    return user is not None and user in party.gms


async def _get_party_or_error(
    db, interaction: discord.Interaction, party_name: str, server_id: int
) -> Optional[Party]:
    """Look up the party; if absent, send the not-found error and return None.

    Callers must check `if party is None: return` immediately after awaiting this.
    """
    party = _lookup_party(db, party_name, server_id)
    if not party:
        await interaction.response.send_message(
            Strings.PARTY_NOT_FOUND.format(party_name=party_name),
            ephemeral=True,
        )
    return party


async def _require_gm_or_error(
    interaction: discord.Interaction,
    user: Optional[User],
    party: Party,
    error_string: str,
) -> bool:
    """Send an error and return False if the user is not a GM of the party.

    Callers must check `if not result: return` immediately after awaiting this.
    """
    if not _is_gm(user, party):
        await interaction.response.send_message(error_string, ephemeral=True)
        return False
    return True


def register_party_commands(bot: commands.Bot) -> None:
    """Register the /party command group."""
    party_group = app_commands.Group(
        name="party", description="Manage parties and roll for party members"
    )

    # ------------------------------------------------------------------
    # Shared autocomplete helpers
    # ------------------------------------------------------------------

    async def _party_name_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Return autocomplete choices for party names in the current server."""
        db = SessionLocal()
        try:
            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            if not server:
                return []
            parties = db.query(Party).filter_by(server_id=server.id).all()
            return [
                app_commands.Choice(name=p.name, value=p.name)
                for p in parties
                if current.lower() in p.name.lower()
            ][:25]
        finally:
            db.close()

    async def _character_name_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Return autocomplete choices for character names in the current server."""
        db = SessionLocal()
        try:
            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            if not server:
                return []
            characters = db.query(Character).filter_by(server_id=server.id).all()
            return [
                app_commands.Choice(name=character.name, value=character.name)
                for character in characters
                if current.lower() in character.name.lower()
            ][:25]
        finally:
            db.close()

    def _set_active_party(db, user: User, server: Server, party: Party) -> None:
        """Upsert the user-server association to point at party."""
        stmt = select(user_server_association).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id,
        )
        assoc = db.execute(stmt).fetchone()
        if assoc:
            # Row already exists — update the active_party_id in place
            db.execute(
                update(user_server_association)
                .where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id,
                )
                .values(active_party_id=party.id)
            )
        else:
            # No association row yet — create one with the chosen party
            db.execute(
                insert(user_server_association).values(
                    user_id=user.id,
                    server_id=server.id,
                    active_party_id=party.id,
                )
            )

    async def _apply_validated_enum_setting(
        db,
        interaction: discord.Interaction,
        party: Party,
        value: str,
        enum_class: type,
        invalid_msg: str,
        attribute_name: str,
        success_msg: str,
        log_msg: str,
    ) -> None:
        """Validate a string against an enum, write it to party settings, and reply.

        Args:
            db: Active SQLAlchemy session.
            interaction: The Discord interaction to reply to.
            party: The party whose settings should be updated.
            value: The raw string value supplied by the user.
            enum_class: The enum type to validate and cast the value against.
            invalid_msg: The error string to send if the value is not in the enum.
            attribute_name: The PartySettings attribute to set (e.g. "crit_rule").
            success_msg: The string to send on success.
            log_msg: The message to pass to logger.info on success.
        """
        # Build the set of accepted string values from the enum for validation
        valid_values = {member.value for member in enum_class}
        if value not in valid_values:
            await interaction.response.send_message(invalid_msg, ephemeral=True)
            return
        party_settings = _get_or_create_party_settings(db, party)
        setattr(party_settings, attribute_name, enum_class(value))
        db.commit()
        logger.info(log_msg)
        await interaction.response.send_message(success_msg)

    # ------------------------------------------------------------------
    # /party create
    # ------------------------------------------------------------------

    @party_group.command(name="create", description="Create a new party")
    @app_commands.describe(
        party_name="The name of the new party",
        characters_list="Optional comma-separated list of character names to include",
    )
    async def party_create(
        interaction: discord.Interaction,
        party_name: str,
        characters_list: str = "",
    ) -> None:
        logger.debug(
            f"Command /party create called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {party_name}"
        )
        # Defer immediately — character lookups may push past the 3-second response window
        await interaction.response.defer()
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if not user or not server:
                await interaction.followup.send(
                    Strings.ERROR_USER_SERVER_NOT_INIT, ephemeral=True
                )
                return

            # Enforce the per-user GM-party cap before doing any more work
            if len(user.gm_parties) >= MAX_GM_PARTIES_PER_USER:
                await interaction.followup.send(
                    Strings.ERROR_LIMIT_GM_PARTIES.format(
                        limit=MAX_GM_PARTIES_PER_USER
                    ),
                    ephemeral=True,
                )
                return

            # Enforce the server-wide party count limit
            server_party_count = db.query(Party).filter_by(server_id=server.id).count()
            if server_party_count >= MAX_PARTIES_PER_SERVER:
                await interaction.followup.send(
                    Strings.ERROR_LIMIT_PARTIES_SERVER.format(
                        limit=MAX_PARTIES_PER_SERVER
                    ),
                    ephemeral=True,
                )
                return

            existing_party = _lookup_party(db, party_name, server.id)
            if existing_party:
                await interaction.followup.send(
                    Strings.PARTY_ALREADY_EXISTS.format(party_name=party_name),
                    ephemeral=True,
                )
                return

            new_party = Party(name=party_name, gms=[user], server=server)

            # Walk the comma-separated list and resolve each name against this server's
            # characters; collect matches and misses separately to report both at the end
            found_characters = []
            not_found = []
            if characters_list.strip():
                character_names = [
                    character_name.strip()
                    for character_name in characters_list.split(",")
                ]
                for character_name in character_names:
                    character = (
                        db.query(Character)
                        .filter_by(name=character_name, server_id=server.id)
                        .first()
                    )
                    if character:
                        found_characters.append(character)
                    else:
                        not_found.append(character_name)

            new_party.characters = found_characters
            db.add(new_party)
            # Commit the party first so it has an id before the active-party upsert
            db.commit()

            _set_active_party(db, user, server, new_party)
            db.commit()

            if not found_characters:
                message = Strings.PARTY_CREATE_SUCCESS_EMPTY.format(
                    party_name=party_name
                )
            else:
                message = Strings.PARTY_CREATE_SUCCESS_MEMBERS.format(
                    party_name=party_name, count=len(found_characters)
                )

            if not_found:
                message += Strings.ERROR_PARTY_CHAR_NOT_FOUND.format(
                    names=", ".join(not_found)
                )

            logger.info(
                f"/party create completed for user {interaction.user.id}: "
                f"created '{party_name}' with {len(found_characters)} members"
            )
            await interaction.followup.send(message, ephemeral=True)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party active
    # ------------------------------------------------------------------

    @party_group.command(
        name="active", description="Set or view your active party in this server"
    )
    @app_commands.describe(
        party_name="Party to set as active (leave blank to view current)"
    )
    async def party_active(
        interaction: discord.Interaction, party_name: Optional[str] = None
    ) -> None:
        logger.debug(
            f"Command /party active called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {party_name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if party_name:
                # Setting mode: point the user's active-party slot at the named party
                party = await _get_party_or_error(
                    db, interaction, party_name, server.id
                )
                if party is None:
                    return

                _set_active_party(db, user, server, party)
                db.commit()
                logger.info(
                    f"/party active completed for user {interaction.user.id}: "
                    f"set active party to '{party_name}'"
                )
                await interaction.response.send_message(
                    Strings.PARTY_ACTIVE_SET.format(party_name=party_name),
                    ephemeral=True,
                )
            else:
                # View mode: read the active_party_id from the user-server association table
                stmt = select(user_server_association.c.active_party_id).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id,
                )
                result = db.execute(stmt).fetchone()
                if result and result[0]:
                    party = db.get(Party, result[0])
                    char_names = ", ".join(
                        [character.name for character in party.characters]
                    )
                    logger.info(
                        f"/party active completed for user {interaction.user.id}: "
                        f"viewed active party '{party.name}'"
                    )
                    await interaction.response.send_message(
                        Strings.PARTY_ACTIVE_VIEW.format(
                            party_name=party.name, char_names=char_names
                        ),
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        Strings.PARTY_ACTIVE_NONE, ephemeral=True
                    )
        finally:
            db.close()

    @party_active.autocomplete("party_name")
    async def party_active_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party view
    # ------------------------------------------------------------------

    @party_group.command(name="view", description="View details of a party")
    @app_commands.describe(party_name="The name of the party to view")
    async def party_view(interaction: discord.Interaction, party_name: str) -> None:
        logger.debug(
            f"Command /party view called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {party_name}"
        )
        db = SessionLocal()
        try:
            # party_view doesn't create the server — if it doesn't exist no parties do either
            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            if not server:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name),
                    ephemeral=True,
                )
                return
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            embed = discord.Embed(
                title=Strings.PARTY_VIEW_TITLE.format(party_name=party.name),
                color=discord.Color.blue(),
            )
            gm_mentions = " ".join(f"<@{gm.discord_id}>" for gm in party.gms)
            # Fall back to "None" if the party somehow has no GMs
            embed.add_field(
                name=Strings.PARTY_VIEW_GM, value=gm_mentions or "None", inline=False
            )

            if not party.characters:
                embed.description = Strings.PARTY_VIEW_EMPTY
            else:
                members_info = []
                for character in party.characters:
                    members_info.append(
                        Strings.PARTY_VIEW_MEMBER_LINE.format(
                            char_name=character.name,
                            char_level=character.level,
                            discord_id=character.user.discord_id,
                        )
                    )
                embed.add_field(
                    name=Strings.PARTY_VIEW_MEMBERS,
                    value="\n".join(members_info),
                    inline=False,
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(
                f"/party view completed for user {interaction.user.id}: viewed '{party_name}'"
            )
        finally:
            db.close()

    @party_view.autocomplete("party_name")
    async def party_view_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party delete
    # ------------------------------------------------------------------

    @party_group.command(name="delete", description="Delete a party")
    @app_commands.describe(party_name="The name of the party to delete")
    async def party_delete(interaction: discord.Interaction, party_name: str) -> None:
        logger.debug(
            f"Command /party delete called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {party_name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_DELETE
            ):
                return

            # Collect open encounters so the confirmation message can warn the GM;
            # the view will auto-complete them before cascading the delete
            open_encounter_names = [
                enc.name
                for enc in party.encounters
                if enc.status in (EncounterStatus.PENDING, EncounterStatus.ACTIVE)
            ]
            if open_encounter_names:
                # List the encounters that will be force-completed on confirmation
                confirm_msg = Strings.PARTY_DELETE_ENCOUNTER_CONFIRM.format(
                    party_name=party_name,
                    encounter_names=", ".join(f"**{n}**" for n in open_encounter_names),
                )
            else:
                confirm_msg = Strings.PARTY_DELETE_CONFIRM.format(party_name=party_name)

            view = ConfirmPartyDeleteView(party_id=party.id, party_name=party_name)
            logger.debug(
                f"/party delete showing confirmation for user {interaction.user.id}: '{party_name}'"
            )
            await interaction.response.send_message(
                confirm_msg, view=view, ephemeral=True
            )
        finally:
            db.close()

    @party_delete.autocomplete("party_name")
    async def party_delete_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party roll
    # ------------------------------------------------------------------

    @party_group.command(
        name="roll", description="Roll for every member of your active party"
    )
    @app_commands.describe(notation="Skill, stat, save, initiative, or dice notation")
    async def party_roll(interaction: discord.Interaction, notation: str) -> None:
        logger.debug(
            f"Command /party roll called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — notation: {notation}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            party = get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True
                )
                return

            if not party.characters:
                await interaction.response.send_message(
                    Strings.PARTY_ROLL_EMPTY, ephemeral=True
                )
                return

            # Rolling for every member can take longer than 3 seconds — defer first
            await interaction.response.defer()
            results = []
            for character in party.characters:
                roll_result = await perform_roll(character, notation, db)
                results.append(roll_result)

            response = Strings.PARTY_ROLL_HEADER.format(
                notation=notation, party_name=party.name
            ) + "\n".join(results)
            # Discord caps messages at 2000 characters; truncate with an ellipsis if needed
            if len(response) > 2000:
                await interaction.followup.send(
                    response[:1997] + "...", suppress_embeds=True
                )
            else:
                await interaction.followup.send(response, suppress_embeds=True)
            logger.info(
                f"/party roll completed for user {interaction.user.id}: "
                f"rolled {notation} for {len(party.characters)} members in '{party.name}'"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party roll_as
    # ------------------------------------------------------------------

    @party_group.command(
        name="roll_as", description="Roll as a member of your active party"
    )
    @app_commands.describe(
        member_name="The name of the party member",
        notation="Skill, stat, save, initiative, or dice notation",
    )
    async def party_roll_as(
        interaction: discord.Interaction, member_name: str, notation: str
    ) -> None:
        logger.debug(
            f"Command /party roll_as called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — member: {member_name}, notation: {notation}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            party = get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True
                )
                return

            character = next(
                (c for c in party.characters if c.name == member_name), None
            )
            logger.debug(
                f"Member lookup for /party roll_as: "
                f"{'found: ' + character.name if character else 'not found'} in party '{party.name}'"
            )
            if not character:
                await interaction.response.send_message(
                    Strings.PARTY_ACTIVE_MEMBER_NOT_FOUND.format(
                        member_name=member_name
                    ),
                    ephemeral=True,
                )
                return

            response = await perform_roll(character, notation, db)
            await interaction.response.send_message(response, suppress_embeds=True)
            logger.info(
                f"/party roll_as completed for user {interaction.user.id}: "
                f"rolled {notation} as '{member_name}'"
            )
        finally:
            db.close()

    @party_roll_as.autocomplete("member_name")
    async def party_roll_as_member_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            if not user or not server:
                return []
            party = get_active_party(db, user, server)
            if not party:
                return []
            return [
                app_commands.Choice(name=character.name, value=character.name)
                for character in party.characters
                if current.lower() in character.name.lower()
            ][:25]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party character_add
    # ------------------------------------------------------------------

    @party_group.command(name="character_add", description="Add a character to a party")
    @app_commands.describe(
        party_name="The name of the party",
        character_name="The name of the character to add",
        character_owner="The owner of the character (if ambiguous)",
    )
    async def party_character_add(
        interaction: discord.Interaction,
        party_name: str,
        character_name: str,
        character_owner: Optional[discord.Member] = None,
    ) -> None:
        logger.debug(
            f"Command /party character_add called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — party: {party_name}, char: {character_name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_ADD
            ):
                return

            # Start broad: all characters with this name in the server
            query = db.query(Character).filter_by(
                name=character_name, server_id=server.id
            )
            if character_owner:
                # Narrow to the specified owner to resolve ambiguity
                owner = (
                    db.query(User).filter_by(discord_id=str(character_owner.id)).first()
                )
                if not owner:
                    await interaction.response.send_message(
                        Strings.ERROR_CHARACTER_OWNER_NO_CHARACTERS.format(
                            display_name=character_owner.display_name
                        ),
                        ephemeral=True,
                    )
                    return
                query = query.filter_by(user_id=owner.id)

            characters = query.all()
            if not characters:
                await interaction.response.send_message(
                    Strings.CHAR_NOT_FOUND_NAME.format(name=character_name),
                    ephemeral=True,
                )
                return

            # Multiple characters share the name — the caller must specify an owner
            if len(characters) > 1:
                await interaction.response.send_message(
                    Strings.ERROR_MULTIPLE_CHARACTERS_FOUND.format(
                        character_name=character_name
                    ),
                    ephemeral=True,
                )
                return

            character = characters[0]
            if character in party.characters:
                await interaction.response.send_message(
                    Strings.PARTY_MEMBER_ALREADY_IN.format(
                        character_name=character_name
                    ),
                    ephemeral=True,
                )
                return

            if len(party.characters) >= MAX_CHARACTERS_PER_PARTY:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_PARTY_MEMBERS.format(
                        limit=MAX_CHARACTERS_PER_PARTY
                    ),
                    ephemeral=True,
                )
                return

            party.characters.append(character)
            db.commit()
            logger.info(
                f"/party character_add completed for user {interaction.user.id}: "
                f"added '{character_name}' to '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.PARTY_MEMBER_ADDED.format(
                    character_name=character_name,
                    discord_id=character.user.discord_id,
                    party_name=party_name,
                )
            )
        finally:
            db.close()

    @party_character_add.autocomplete("party_name")
    async def party_character_add_party_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @party_character_add.autocomplete("character_name")
    async def party_character_add_char_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _character_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party character_remove
    # ------------------------------------------------------------------

    @party_group.command(
        name="character_remove", description="Remove a character from a party"
    )
    @app_commands.describe(
        party_name="The name of the party",
        character_name="The name of the character to remove",
        character_owner="The owner of the character (if ambiguous)",
    )
    async def party_character_remove(
        interaction: discord.Interaction,
        party_name: str,
        character_name: str,
        character_owner: Optional[discord.Member] = None,
    ) -> None:
        logger.debug(
            f"Command /party character_remove called by {interaction.user} "
            f"(ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — party: {party_name}, char: {character_name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_REMOVE
            ):
                return

            # Search the party's in-memory member list, optionally filtered by owner
            character = next(
                (
                    c
                    for c in party.characters
                    if c.name == character_name
                    and (
                        not character_owner
                        or str(c.user.discord_id) == str(character_owner.id)
                    )
                ),
                None,
            )

            if not character:
                await interaction.response.send_message(
                    Strings.ERROR_CHAR_NOT_IN_PARTY.format(
                        character_name=character_name, party_name=party_name
                    ),
                    ephemeral=True,
                )
                return

            # Mid-combat removal needs special handling — check for an active turn first
            active_turn = (
                db.query(EncounterTurn)
                .filter_by(character_id=character.id)
                .join(EncounterTurn.encounter)
                .filter(
                    Encounter.party_id == party.id,
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )

            if active_turn:
                # Warn the GM that the character's encounter turn will be deleted
                confirm_msg = Strings.PARTY_REMOVE_ENCOUNTER_WARNING.format(
                    char_name=character_name,
                    encounter_name=active_turn.encounter.name,
                )
            else:
                confirm_msg = Strings.PARTY_CHAR_REMOVE_CONFIRM.format(
                    char_name=character_name, party_name=party_name
                )

            view = ConfirmCharacterRemoveView(
                party_id=party.id,
                char_id=character.id,
                party_name=party_name,
                char_name=character_name,
            )
            await interaction.response.send_message(
                confirm_msg, view=view, ephemeral=True
            )
        finally:
            db.close()

    @party_character_remove.autocomplete("party_name")
    async def party_character_remove_party_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @party_character_remove.autocomplete("character_name")
    async def party_character_remove_char_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            party_name = interaction.namespace.party_name
            party = _lookup_party(db, party_name, server.id)
            if not party:
                return []
            return [
                app_commands.Choice(name=character.name, value=character.name)
                for character in party.characters
                if current.lower() in character.name.lower()
            ][:25]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party gm_add
    # ------------------------------------------------------------------

    @party_group.command(
        name="gm_add", description="Add a Discord user as a GM of a party (GM only)"
    )
    @app_commands.describe(
        party_name="The name of the party",
        new_gm="The Discord user to add as a GM",
    )
    async def party_gm_add(
        interaction: discord.Interaction, party_name: str, new_gm: discord.Member
    ) -> None:
        """Add a new GM to the party. Only existing GMs may use this command."""
        logger.debug(
            f"Command /party gm_add called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — party: {party_name}, new_gm: {new_gm.id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_ADD_GM
            ):
                return

            # Ensure the target has a User row even if they've never run a bot command
            target = get_or_create_user(db, str(new_gm.id))

            if target in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ALREADY.format(
                        discord_id=new_gm.id, party_name=party_name
                    ),
                    ephemeral=True,
                )
                return

            party.gms.append(target)
            db.commit()
            logger.info(
                f"/party gm_add completed: user {interaction.user.id} "
                f"added {new_gm.id} as GM of '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.GM_ADDED.format(discord_id=new_gm.id, party_name=party_name)
            )
        finally:
            db.close()

    @party_gm_add.autocomplete("party_name")
    async def party_gm_add_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party gm_remove
    # ------------------------------------------------------------------

    @party_group.command(
        name="gm_remove", description="Remove a GM from a party (GM only)"
    )
    @app_commands.describe(
        party_name="The name of the party",
        target_gm="The Discord user to remove as a GM",
    )
    async def party_gm_remove(
        interaction: discord.Interaction, party_name: str, target_gm: discord.Member
    ) -> None:
        """Remove a GM from the party. The last GM cannot be removed."""
        logger.debug(
            f"Command /party gm_remove called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — party: {party_name}, target_gm: {target_gm.id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_REMOVE_GM
            ):
                return

            target = db.query(User).filter_by(discord_id=str(target_gm.id)).first()
            if not target or target not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_NOT_IN_PARTY.format(
                        discord_id=target_gm.id, party_name=party_name
                    ),
                    ephemeral=True,
                )
                return

            # Prevent orphaning the party by removing its last GM
            if len(party.gms) == 1:
                await interaction.response.send_message(
                    Strings.ERROR_GM_LAST, ephemeral=True
                )
                return

            # Removing yourself requires an extra confirmation step
            is_self_removal = str(target.discord_id) == str(interaction.user.id)
            if is_self_removal:
                view = ConfirmSelfGMRemoveView(
                    party_id=party.id,
                    party_name=party_name,
                    user_discord_id=str(interaction.user.id),
                )
                logger.debug(
                    f"/party gm_remove showing self-removal confirmation for user {interaction.user.id} "
                    f"in party '{party_name}'"
                )
                await interaction.response.send_message(
                    Strings.PARTY_GM_REMOVE_SELF_CONFIRM.format(party_name=party_name),
                    view=view,
                    ephemeral=True,
                )
                return

            party.gms.remove(target)
            db.commit()
            logger.info(
                f"/party gm_remove completed: user {interaction.user.id} "
                f"removed {target_gm.id} as GM of '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.GM_REMOVED.format(
                    discord_id=target_gm.id, party_name=party_name
                )
            )
        finally:
            db.close()

    @party_gm_remove.autocomplete("party_name")
    async def party_gm_remove_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    # ------------------------------------------------------------------
    # /party settings subgroup
    # ------------------------------------------------------------------

    settings_group = app_commands.Group(
        name="settings",
        description="View or change per-party settings (GM only for changes)",
    )

    @settings_group.command(
        name="view", description="View the current settings for a party"
    )
    @app_commands.describe(
        party_name="The party whose settings you want to view (defaults to active party)"
    )
    async def party_settings_view(
        interaction: discord.Interaction,
        party_name: Optional[str] = None,
    ) -> None:
        """Display the current settings for the specified (or active) party.

        Any party member or GM can view settings.
        """
        logger.debug(
            f"Command /party settings view called by {interaction.user.id} "
            f"for party '{party_name}'"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if party_name:
                party = _lookup_party(db, party_name, server.id)
            else:
                party = get_active_party(db, user, server)

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name or "(active)"),
                    ephemeral=True,
                )
                return

            party_settings = _get_or_create_party_settings(db, party)
            db.commit()

            msg = Strings.PARTY_SETTINGS_VIEW.format(
                party_name=party.name,
                initiative_mode=party_settings.initiative_mode.value,
                enemy_ac_public=str(party_settings.enemy_ac_public),
                death_save_nat20_mode=party_settings.death_save_nat20_mode.value,
            )
            logger.info(
                f"/party settings view served for user {interaction.user.id}: '{party.name}'"
            )
            await interaction.response.send_message(msg, ephemeral=True)
        finally:
            db.close()

    @party_settings_view.autocomplete("party_name")
    async def party_settings_view_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @settings_group.command(
        name="initiative_mode",
        description="Set how enemy initiative is rolled (GM only)",
    )
    @app_commands.describe(
        party_name="The party to update",
        mode="Initiative mode: by_type, individual, or shared",
    )
    async def party_settings_initiative_mode(
        interaction: discord.Interaction,
        party_name: str,
        mode: str,
    ) -> None:
        """Update the enemy initiative rolling mode for a party.

        Only the party GM can use this command.  Valid modes are ``by_type``,
        ``individual``, and ``shared``.

        Args:
            interaction: The Discord interaction.
            party_name: Name of the party to update.
            mode: One of 'by_type', 'individual', or 'shared'.
        """
        logger.debug(
            f"Command /party settings initiative_mode called by {interaction.user.id} "
            f"party='{party_name}' mode='{mode}'"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_SETTINGS
            ):
                return

            await _apply_validated_enum_setting(
                db,
                interaction,
                party,
                value=mode,
                enum_class=EnemyInitiativeMode,
                invalid_msg=Strings.PARTY_SETTINGS_INVALID_MODE,
                attribute_name="initiative_mode",
                success_msg=Strings.PARTY_SETTINGS_UPDATED.format(
                    setting="initiative_mode",
                    value=mode,
                    party_name=party.name,
                ),
                log_msg=(
                    f"/party settings initiative_mode updated for user {interaction.user.id}: "
                    f"'{party_name}' → {mode}"
                ),
            )
        finally:
            db.close()

    @party_settings_initiative_mode.autocomplete("party_name")
    async def party_settings_initiative_mode_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @settings_group.command(
        name="enemy_ac",
        description="Set whether enemy AC is visible to all players (GM only)",
    )
    @app_commands.describe(
        party_name="The party to update",
        public="True to show enemy AC to players, False to hide it",
    )
    async def party_settings_enemy_ac(
        interaction: discord.Interaction,
        party_name: str,
        public: bool,
    ) -> None:
        """Update the enemy AC visibility setting for a party.

        Only the party GM can use this command.

        Args:
            interaction: The Discord interaction.
            party_name: Name of the party to update.
            public: Whether enemy AC values should be visible to all players.
        """
        logger.debug(
            f"Command /party settings enemy_ac called by {interaction.user.id} "
            f"party='{party_name}' public={public}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_SETTINGS
            ):
                return

            party_settings = _get_or_create_party_settings(db, party)
            party_settings.enemy_ac_public = public
            db.commit()

            logger.info(
                f"/party settings enemy_ac updated for user {interaction.user.id}: "
                f"'{party_name}' → {public}"
            )
            await interaction.response.send_message(
                Strings.PARTY_SETTINGS_UPDATED.format(
                    setting="enemy_ac_public",
                    value=str(public),
                    party_name=party.name,
                )
            )
        finally:
            db.close()

    @party_settings_enemy_ac.autocomplete("party_name")
    async def party_settings_enemy_ac_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @settings_group.command(
        name="crit_rule",
        description="Set how critical hits are resolved for this party (GM only)",
    )
    @app_commands.describe(
        party_name="The party to update",
        rule="Crit rule: double_dice (default), perkins, double_damage, max_damage, or none",
    )
    async def party_settings_crit_rule(
        interaction: discord.Interaction,
        party_name: str,
        rule: str,
    ) -> None:
        """Update the critical hit rule for a party.

        Only the party GM can use this command.  Valid rules are
        ``double_dice`` (default), ``perkins``, ``double_damage``,
        ``max_damage``, and ``none``.

        Args:
            interaction: The Discord interaction.
            party_name: Name of the party to update.
            rule: One of the CritRule string values.
        """
        logger.debug(
            f"Command /party settings crit_rule called by {interaction.user.id} "
            f"party='{party_name}' rule='{rule}'"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_SETTINGS
            ):
                return

            await _apply_validated_enum_setting(
                db,
                interaction,
                party,
                value=rule,
                enum_class=CritRule,
                invalid_msg=Strings.PARTY_SETTINGS_INVALID_CRIT_RULE,
                attribute_name="crit_rule",
                success_msg=Strings.PARTY_SETTINGS_UPDATED.format(
                    setting="crit_rule",
                    value=rule,
                    party_name=party.name,
                ),
                log_msg=(
                    f"/party settings crit_rule updated for user {interaction.user.id}: "
                    f"'{party_name}' → {rule}"
                ),
            )
        finally:
            db.close()

    @party_settings_crit_rule.autocomplete("party_name")
    async def party_settings_crit_rule_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    @settings_group.command(
        name="death_save_nat20",
        description="Set how a natural 20 on a death save is resolved (GM only)",
    )
    @app_commands.describe(
        party_name="The party to update",
        mode="regain_hp (5e 2024 RAW) or double_success (house rule)",
    )
    async def party_settings_death_save_nat20(
        interaction: discord.Interaction,
        party_name: str,
        mode: str,
    ) -> None:
        """Update the nat-20 death save rule for a party.

        Only the party GM can use this command.  Valid modes are
        ``regain_hp`` (5e 2024 RAW: regain 1 HP) and ``double_success``
        (house rule: count as 2 successes).

        Args:
            interaction: The Discord interaction.
            party_name: Name of the party to update.
            mode: One of the DeathSaveNat20Mode string values.
        """
        logger.debug(
            f"Command /party settings death_save_nat20 called by {interaction.user.id} "
            f"party='{party_name}' mode='{mode}'"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = await _get_party_or_error(db, interaction, party_name, server.id)
            if party is None:
                return

            if not await _require_gm_or_error(
                interaction, user, party, Strings.ERROR_GM_ONLY_PARTY_SETTINGS
            ):
                return

            await _apply_validated_enum_setting(
                db,
                interaction,
                party,
                value=mode,
                enum_class=DeathSaveNat20Mode,
                invalid_msg=Strings.PARTY_SETTINGS_INVALID_NAT20_MODE,
                attribute_name="death_save_nat20_mode",
                success_msg=Strings.PARTY_SETTINGS_NAT20_UPDATED.format(
                    mode=mode,
                    party_name=party.name,
                ),
                log_msg=(
                    f"/party settings death_save_nat20 updated for user {interaction.user.id}: "
                    f"'{party_name}' → {mode}"
                ),
            )
        finally:
            db.close()

    @party_settings_death_save_nat20.autocomplete("party_name")
    async def party_settings_death_save_nat20_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    party_group.add_command(settings_group)

    # ------------------------------------------------------------------
    # /party list
    # ------------------------------------------------------------------

    @party_group.command(
        name="list",
        description="List all parties on this server with their member counts",
    )
    async def party_list(interaction: discord.Interaction) -> None:
        """Display a paginated list of all parties on this server.

        Available to any user — no character or GM status required.
        """
        logger.debug(f"Command /party list called by {interaction.user.id}")
        db = SessionLocal()
        try:
            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            if not server:
                await interaction.response.send_message(
                    Strings.PARTY_LIST_EMPTY, ephemeral=True
                )
                return

            parties = (
                db.query(Party)
                .filter_by(server_id=server.id)
                .order_by(Party.name)
                .all()
            )
            if not parties:
                await interaction.response.send_message(
                    Strings.PARTY_LIST_EMPTY, ephemeral=True
                )
                return

            party_data = [(p.name, len(p.characters)) for p in parties]
            view = PartyListView(party_data, server_name=server.name)
            logger.info(
                f"/party list served for user {interaction.user.id}: "
                f"{len(parties)} parties in server {server.discord_id}"
            )
            await interaction.response.send_message(embed=view.build_embed(), view=view)
        finally:
            db.close()

    bot.tree.add_command(party_group)
