import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import update, select, insert
from database import SessionLocal
from models import User, Server, Character, Party, Encounter, EncounterTurn, user_server_association
from enums.encounter_status import EncounterStatus
from utils.dnd_logic import perform_roll
from utils.limits import MAX_GM_PARTIES_PER_USER, MAX_CHARACTERS_PER_PARTY, MAX_PARTIES_PER_SERVER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


class _ConfirmCharacterRemoveView(discord.ui.View):
    """Ephemeral confirmation shown when removing a character who is in an active encounter.

    ✅ Remove — deletes their EncounterTurn and removes them from the party.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, party_id: int, char_id: int, party_name: str, char_name: str) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.char_id = char_id
        self.party_name = party_name
        self.char_name = char_name

    @discord.ui.button(label="Remove", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cascade-delete the character's EncounterTurn, then remove from party."""
        db = SessionLocal()
        try:
            party = db.get(Party, self.party_id)
            char = db.get(Character, self.char_id)

            if not party or not char:
                await interaction.response.edit_message(
                    content="Character or party no longer exists.", view=None
                )
                return

            active_turn = (
                db.query(EncounterTurn)
                .filter_by(character_id=char.id)
                .join(EncounterTurn.encounter)
                .filter(Encounter.status == EncounterStatus.ACTIVE)
                .first()
            )

            if active_turn:
                encounter = active_turn.encounter
                sorted_turns = sorted(encounter.turns, key=lambda t: t.order_position)
                deleted_index = sorted_turns.index(active_turn)
                turn_count_after = len(sorted_turns) - 1

                db.delete(active_turn)
                db.flush()

                # Keep current_turn_index valid after removal
                if turn_count_after == 0:
                    encounter.current_turn_index = 0
                elif deleted_index < encounter.current_turn_index:
                    encounter.current_turn_index -= 1
                elif deleted_index == encounter.current_turn_index:
                    if encounter.current_turn_index >= turn_count_after:
                        encounter.current_turn_index = 0
                        encounter.round_number += 1

            if char in party.characters:
                party.characters.remove(char)

            db.commit()
            logger.info(
                f"Confirmed removal of '{self.char_name}' from '{self.party_name}' "
                "including EncounterTurn cascade"
            )
            await interaction.response.edit_message(
                content=Strings.PARTY_REMOVE_ENCOUNTER_CONFIRMED.format(
                    char_name=self.char_name, party_name=self.party_name
                ),
                view=None,
            )
        finally:
            db.close()
        self.stop()

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_REMOVE_CANCELLED, view=None
        )
        self.stop()


class _ConfirmPartyDeleteView(discord.ui.View):
    """Ephemeral confirmation before permanently deleting a party.

    If the party has open encounters the initial message lists them; the
    confirm handler auto-completes them before deleting.

    ✅ Delete — auto-completes open encounters, then cascade-deletes the party.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, party_id: int, party_name: str) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.party_name = party_name

    @discord.ui.button(label="Delete", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Auto-complete open encounters, then delete the party."""
        db = SessionLocal()
        try:
            party = db.get(Party, self.party_id)
            if not party:
                await interaction.response.edit_message(
                    content="Party no longer exists.", view=None
                )
                return

            completed_names: list[str] = []
            for enc in party.encounters:
                if enc.status in (EncounterStatus.PENDING, EncounterStatus.ACTIVE):
                    enc.status = EncounterStatus.COMPLETE
                    completed_names.append(enc.name)
            if completed_names:
                db.flush()

            db.delete(party)
            db.commit()
            logger.info(
                f"Confirmed deletion of party '{self.party_name}' (id={self.party_id})"
            )
            msg = Strings.PARTY_DELETE_SUCCESS.format(party_name=self.party_name)
            if completed_names:
                for enc_name in completed_names:
                    msg += "\n" + Strings.PARTY_DELETE_ENCOUNTER_COMPLETED.format(
                        encounter_name=enc_name
                    )
            await interaction.response.edit_message(content=msg, view=None)
        finally:
            db.close()
        self.stop()

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_DELETE_CANCELLED, view=None
        )
        self.stop()


class _ConfirmSelfGMRemoveView(discord.ui.View):
    """Ephemeral confirmation shown when a GM tries to remove themselves.

    ✅ Remove  — removes the user from the party's GM list.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, party_id: int, party_name: str, user_discord_id: str) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.party_name = party_name
        self.user_discord_id = user_discord_id

    @discord.ui.button(label="Remove myself", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Remove the user from the party's GM list."""
        db = SessionLocal()
        try:
            party = db.get(Party, self.party_id)
            user = db.query(User).filter_by(discord_id=self.user_discord_id).first()

            if not party or not user:
                await interaction.response.edit_message(
                    content="Party or user no longer exists.", view=None
                )
                return

            if user not in party.gms:
                await interaction.response.edit_message(
                    content="You are no longer a GM of this party.", view=None
                )
                return

            party.gms.remove(user)
            db.commit()
            logger.info(
                f"Confirmed self-GM-removal: user {self.user_discord_id} "
                f"left GMs of '{self.party_name}'"
            )
            await interaction.response.edit_message(
                content=Strings.GM_REMOVED.format(
                    discord_id=self.user_discord_id, party_name=self.party_name
                ),
                view=None,
            )
        finally:
            db.close()
        self.stop()

    @discord.ui.button(label="Cancel", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_GM_REMOVE_SELF_CANCELLED, view=None
        )
        self.stop()


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
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
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
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not server:
                return []
            chars = db.query(Character).filter_by(server_id=server.id).all()
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars
                if current.lower() in c.name.lower()
            ][:25]
        finally:
            db.close()

    def _get_active_party(db, user: User, server: Server) -> Optional[Party]:
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

    def _set_active_party(db, user: User, server: Server, party: Party) -> None:
        """Upsert the user-server association to point at party."""
        stmt = select(user_server_association).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id,
        )
        assoc = db.execute(stmt).fetchone()
        if assoc:
            db.execute(
                update(user_server_association)
                .where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id,
                )
                .values(active_party_id=party.id)
            )
        else:
            db.execute(
                insert(user_server_association).values(
                    user_id=user.id,
                    server_id=server.id,
                    active_party_id=party.id,
                )
            )

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
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if not user or not server:
                await interaction.response.send_message(
                    Strings.ERROR_USER_SERVER_NOT_INIT, ephemeral=True
                )
                return

            if len(user.gm_parties) >= MAX_GM_PARTIES_PER_USER:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_GM_PARTIES.format(limit=MAX_GM_PARTIES_PER_USER),
                    ephemeral=True,
                )
                return

            server_party_count = db.query(Party).filter_by(server_id=server.id).count()
            if server_party_count >= MAX_PARTIES_PER_SERVER:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_PARTIES_SERVER.format(limit=MAX_PARTIES_PER_SERVER),
                    ephemeral=True,
                )
                return

            existing_party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
            if existing_party:
                await interaction.response.send_message(
                    Strings.PARTY_ALREADY_EXISTS.format(party_name=party_name), ephemeral=True
                )
                return

            new_party = Party(name=party_name, gms=[user], server=server)

            found_chars = []
            not_found = []
            if characters_list.strip():
                char_names = [n.strip() for n in characters_list.split(",")]
                for n in char_names:
                    char = db.query(Character).filter_by(name=n, server_id=server.id).first()
                    if char:
                        found_chars.append(char)
                    else:
                        not_found.append(n)

            new_party.characters = found_chars
            db.add(new_party)
            db.commit()

            _set_active_party(db, user, server, new_party)
            db.commit()

            if not found_chars:
                msg = Strings.PARTY_CREATE_SUCCESS_EMPTY.format(party_name=party_name)
            else:
                msg = Strings.PARTY_CREATE_SUCCESS_MEMBERS.format(
                    party_name=party_name, count=len(found_chars)
                )

            if not_found:
                msg += Strings.ERROR_PARTY_CHAR_NOT_FOUND.format(names=", ".join(not_found))

            logger.info(
                f"/party create completed for user {interaction.user.id}: "
                f"created '{party_name}' with {len(found_chars)} members"
            )
            await interaction.response.send_message(msg)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party active
    # ------------------------------------------------------------------

    @party_group.command(name="active", description="Set or view your active party in this server")
    @app_commands.describe(party_name="Party to set as active (leave blank to view current)")
    async def party_active(
        interaction: discord.Interaction, party_name: Optional[str] = None
    ) -> None:
        logger.debug(
            f"Command /party active called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {party_name}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if party_name:
                party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
                if not party:
                    await interaction.response.send_message(
                        Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                    )
                    return

                _set_active_party(db, user, server, party)
                db.commit()
                logger.info(
                    f"/party active completed for user {interaction.user.id}: "
                    f"set active party to '{party_name}'"
                )
                await interaction.response.send_message(
                    Strings.PARTY_ACTIVE_SET.format(party_name=party_name)
                )
            else:
                stmt = select(user_server_association.c.active_party_id).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id,
                )
                result = db.execute(stmt).fetchone()
                if result and result[0]:
                    party = db.get(Party, result[0])
                    char_names = ", ".join([c.name for c in party.characters])
                    logger.info(
                        f"/party active completed for user {interaction.user.id}: "
                        f"viewed active party '{party.name}'"
                    )
                    await interaction.response.send_message(
                        Strings.PARTY_ACTIVE_VIEW.format(
                            party_name=party.name, char_names=char_names
                        )
                    )
                else:
                    await interaction.response.send_message(Strings.PARTY_ACTIVE_NONE)
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
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            embed = discord.Embed(
                title=Strings.PARTY_VIEW_TITLE.format(party_name=party.name),
                color=discord.Color.blue(),
            )
            gm_mentions = " ".join(f"<@{gm.discord_id}>" for gm in party.gms)
            embed.add_field(name=Strings.PARTY_VIEW_GM, value=gm_mentions or "None", inline=False)

            if not party.characters:
                embed.description = Strings.PARTY_VIEW_EMPTY
            else:
                members_info = []
                for char in party.characters:
                    members_info.append(
                        Strings.PARTY_VIEW_MEMBER_LINE.format(
                            char_name=char.name,
                            char_level=char.level,
                            discord_id=char.user.discord_id,
                        )
                    )
                embed.add_field(
                    name=Strings.PARTY_VIEW_MEMBERS,
                    value="\n".join(members_info),
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_PARTY_DELETE, ephemeral=True
                )
                return

            open_encounter_names = [
                enc.name
                for enc in party.encounters
                if enc.status in (EncounterStatus.PENDING, EncounterStatus.ACTIVE)
            ]
            if open_encounter_names:
                confirm_msg = Strings.PARTY_DELETE_ENCOUNTER_CONFIRM.format(
                    party_name=party_name,
                    encounter_names=", ".join(f"**{n}**" for n in open_encounter_names),
                )
            else:
                confirm_msg = Strings.PARTY_DELETE_CONFIRM.format(party_name=party_name)

            view = _ConfirmPartyDeleteView(party_id=party.id, party_name=party_name)
            logger.debug(
                f"/party delete showing confirmation for user {interaction.user.id}: '{party_name}'"
            )
            await interaction.response.send_message(confirm_msg, view=view, ephemeral=True)
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

    @party_group.command(name="roll", description="Roll for every member of your active party")
    @app_commands.describe(notation="Skill, stat, save, initiative, or dice notation")
    async def party_roll(interaction: discord.Interaction, notation: str) -> None:
        logger.debug(
            f"Command /party roll called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} — notation: {notation}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            party = _get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True
                )
                return

            if not party.characters:
                await interaction.response.send_message(Strings.PARTY_ROLL_EMPTY, ephemeral=True)
                return

            await interaction.response.defer()
            results = []
            for char in party.characters:
                res = await perform_roll(char, notation, db)
                results.append(res)

            response = (
                Strings.PARTY_ROLL_HEADER.format(notation=notation, party_name=party.name)
                + "\n".join(results)
            )
            if len(response) > 2000:
                await interaction.followup.send(response[:1997] + "...")
            else:
                await interaction.followup.send(response)
            logger.info(
                f"/party roll completed for user {interaction.user.id}: "
                f"rolled {notation} for {len(party.characters)} members in '{party.name}'"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /party roll_as
    # ------------------------------------------------------------------

    @party_group.command(name="roll_as", description="Roll as a member of your active party")
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            party = _get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True
                )
                return

            char = next((c for c in party.characters if c.name == member_name), None)
            logger.debug(
                f"Member lookup for /party roll_as: "
                f"{'found: ' + char.name if char else 'not found'} in party '{party.name}'"
            )
            if not char:
                await interaction.response.send_message(
                    Strings.PARTY_ACTIVE_MEMBER_NOT_FOUND.format(member_name=member_name),
                    ephemeral=True,
                )
                return

            response = await perform_roll(char, notation, db)
            await interaction.response.send_message(response)
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not user or not server:
                return []
            party = _get_active_party(db, user, server)
            if not party:
                return []
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in party.characters
                if current.lower() in c.name.lower()
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_PARTY_ADD, ephemeral=True
                )
                return

            query = db.query(Character).filter_by(name=character_name, server_id=server.id)
            if character_owner:
                owner = db.query(User).filter_by(discord_id=str(character_owner.id)).first()
                if not owner:
                    await interaction.response.send_message(
                        f"User **{character_owner.display_name}** has no characters.",
                        ephemeral=True,
                    )
                    return
                query = query.filter_by(user_id=owner.id)

            chars = query.all()
            if not chars:
                await interaction.response.send_message(
                    Strings.CHAR_NOT_FOUND_NAME.format(name=character_name), ephemeral=True
                )
                return

            if len(chars) > 1:
                await interaction.response.send_message(
                    f"Multiple characters named '**{character_name}**' found. "
                    "Please specify the owner.",
                    ephemeral=True,
                )
                return

            char = chars[0]
            if char in party.characters:
                await interaction.response.send_message(
                    Strings.PARTY_MEMBER_ALREADY_IN.format(character_name=character_name),
                    ephemeral=True,
                )
                return

            if len(party.characters) >= MAX_CHARACTERS_PER_PARTY:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_PARTY_MEMBERS.format(limit=MAX_CHARACTERS_PER_PARTY),
                    ephemeral=True,
                )
                return

            party.characters.append(char)
            db.commit()
            logger.info(
                f"/party character_add completed for user {interaction.user.id}: "
                f"added '{character_name}' to '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.PARTY_MEMBER_ADDED.format(
                    character_name=character_name,
                    discord_id=char.user.discord_id,
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

    @party_group.command(name="character_remove", description="Remove a character from a party")
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_PARTY_REMOVE, ephemeral=True
                )
                return

            char = next(
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

            if not char:
                await interaction.response.send_message(
                    f"Character '**{character_name}**' not found in party '**{party_name}**'.",
                    ephemeral=True,
                )
                return

            # Check whether this character is in an active encounter for this party
            active_turn = (
                db.query(EncounterTurn)
                .filter_by(character_id=char.id)
                .join(EncounterTurn.encounter)
                .filter(
                    Encounter.party_id == party.id,
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )

            if active_turn:
                confirm_msg = Strings.PARTY_REMOVE_ENCOUNTER_WARNING.format(
                    char_name=character_name,
                    encounter_name=active_turn.encounter.name,
                )
            else:
                confirm_msg = Strings.PARTY_CHAR_REMOVE_CONFIRM.format(
                    char_name=character_name, party_name=party_name
                )

            view = _ConfirmCharacterRemoveView(
                party_id=party.id,
                char_id=char.id,
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
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party_name = interaction.namespace.party_name
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
            if not party:
                return []
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in party.characters
                if current.lower() in c.name.lower()
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_ADD_GM, ephemeral=True
                )
                return

            target = db.query(User).filter_by(discord_id=str(new_gm.id)).first()
            if not target:
                await interaction.response.send_message(
                    Strings.ERROR_GM_TARGET_NOT_REGISTERED, ephemeral=True
                )
                return

            if target in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ALREADY.format(discord_id=new_gm.id, party_name=party_name),
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
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(
                    Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True
                )
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_ONLY_REMOVE_GM, ephemeral=True
                )
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

            if len(party.gms) == 1:
                await interaction.response.send_message(Strings.ERROR_GM_LAST, ephemeral=True)
                return

            is_self_removal = str(target.discord_id) == str(interaction.user.id)
            if is_self_removal:
                view = _ConfirmSelfGMRemoveView(
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
                Strings.GM_REMOVED.format(discord_id=target_gm.id, party_name=party_name)
            )
        finally:
            db.close()

    @party_gm_remove.autocomplete("party_name")
    async def party_gm_remove_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return await _party_name_autocomplete(interaction, current)

    bot.tree.add_command(party_group)
