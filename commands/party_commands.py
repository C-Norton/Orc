import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import update, select
from database import SessionLocal
from models import User, Server, Character, Party, user_server_association
from utils.dnd_logic import perform_roll
from utils.limits import MAX_GM_PARTIES_PER_USER, MAX_CHARACTERS_PER_PARTY, MAX_PARTIES_PER_SERVER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

def register_party_commands(bot: commands.Bot) -> None:
    async def party_name_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not server: return []
            parties = db.query(Party).filter_by(server_id=server.id).all()
            return [app_commands.Choice(name=p.name, value=p.name) for p in parties if current.lower() in p.name.lower()][:25]
        finally:
            db.close()

    async def character_name_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not server: return []
            chars = db.query(Character).filter_by(server_id=server.id).all()
            return [app_commands.Choice(name=c.name, value=c.name) for c in chars if current.lower() in c.name.lower()][:25]
        finally:
            db.close()

    @bot.tree.command(name="create_party", description="Create a new party with an optional list of characters")
    @app_commands.describe(
        party_name="The name of the new party",
        characters_list="Optional comma-separated list of character names to include in the party"
    )
    async def create_party(interaction: discord.Interaction, party_name: str, characters_list: str = "") -> None:
        logger.debug(f"Command /create_party called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {party_name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if not user or not server:
                await interaction.response.send_message(Strings.ERROR_USER_SERVER_NOT_INIT, ephemeral=True)
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
                await interaction.response.send_message(Strings.PARTY_ALREADY_EXISTS.format(party_name=party_name), ephemeral=True)
                return

            new_party = Party(name=party_name, gms=[user], server=server)

            found_chars = []
            not_found = []
            if characters_list.strip():
                char_names = [name.strip() for name in characters_list.split(',')]
                for name in char_names:
                    char = db.query(Character).filter_by(name=name, server_id=server.id).first()
                    if char:
                        found_chars.append(char)
                    else:
                        not_found.append(name)

            new_party.characters = found_chars
            db.add(new_party)
            db.commit()

            # Ensure the user-server association exists and update active party
            stmt = select(user_server_association).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            )
            assoc = db.execute(stmt).fetchone()

            if assoc:
                stmt = update(user_server_association).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id
                ).values(active_party_id=new_party.id)
                db.execute(stmt)
            else:
                from sqlalchemy import insert
                stmt = insert(user_server_association).values(
                    user_id=user.id,
                    server_id=server.id,
                    active_party_id=new_party.id
                )
                db.execute(stmt)

            db.commit()

            if not found_chars:
                msg = Strings.PARTY_CREATE_SUCCESS_EMPTY.format(party_name=party_name)
            else:
                msg = Strings.PARTY_CREATE_SUCCESS_MEMBERS.format(party_name=party_name, count=len(found_chars))

            if not_found:
                msg += Strings.ERROR_PARTY_CHAR_NOT_FOUND.format(names=', '.join(not_found))

            logger.info(f"/create_party completed for user {interaction.user.id}: created '{party_name}' with {len(found_chars)} members")
            await interaction.response.send_message(msg)
        finally:
            db.close()

    @bot.tree.command(name="party_add", description="Add a character to a party")
    @app_commands.describe(
        party_name="The name of the party",
        character_owner="The owner of the character",
        character_name="The name of the character to add"
    )
    async def party_add(interaction: discord.Interaction, party_name: str, character_name: str, character_owner: Optional[discord.Member] = None) -> None:
        logger.debug(f"Command /party_add called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} - party: {party_name}, char: {character_name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True)
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(Strings.ERROR_GM_ONLY_PARTY_ADD, ephemeral=True)
                return

            query = db.query(Character).filter_by(name=character_name, server_id=server.id)
            if character_owner:
                owner = db.query(User).filter_by(discord_id=str(character_owner.id)).first()
                if not owner:
                    await interaction.response.send_message(f"User **{character_owner.display_name}** has no characters.", ephemeral=True)
                    return
                query = query.filter_by(user_id=owner.id)

            chars = query.all()
            if not chars:
                await interaction.response.send_message(Strings.CHAR_NOT_FOUND_NAME.format(name=character_name), ephemeral=True)
                return

            if len(chars) > 1:
                await interaction.response.send_message(f"Multiple characters named '**{character_name}**' found. Please specify the owner.", ephemeral=True)
                return

            char = chars[0]
            if char in party.characters:
                await interaction.response.send_message(Strings.PARTY_MEMBER_ALREADY_IN.format(character_name=character_name), ephemeral=True)
                return

            if len(party.characters) >= MAX_CHARACTERS_PER_PARTY:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_PARTY_MEMBERS.format(limit=MAX_CHARACTERS_PER_PARTY),
                    ephemeral=True,
                )
                return

            party.characters.append(char)
            db.commit()
            logger.info(f"/party_add completed for user {interaction.user.id}: added '{character_name}' to '{party_name}'")
            await interaction.response.send_message(Strings.PARTY_MEMBER_ADDED.format(character_name=character_name, discord_id=char.user.discord_id, party_name=party_name))
        finally:
            db.close()

    @party_add.autocomplete("party_name")
    async def party_add_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @party_add.autocomplete("character_name")
    async def party_add_character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await character_name_autocomplete(interaction, current)

    @bot.tree.command(name="party_remove", description="Remove a character from a party")
    @app_commands.describe(
        party_name="The name of the party",
        character_owner="The owner of the character",
        character_name="The name of the character to remove"
    )
    async def party_remove(interaction: discord.Interaction, party_name: str, character_name: str, character_owner: Optional[discord.Member] = None) -> None:
        logger.debug(f"Command /party_remove called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} - party: {party_name}, char: {character_name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True)
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(Strings.ERROR_GM_ONLY_PARTY_REMOVE, ephemeral=True)
                return

            # Find the character in the party
            char = next((c for c in party.characters if c.name == character_name and (not character_owner or str(c.user.discord_id) == str(character_owner.id))), None)

            if not char:
                await interaction.response.send_message(f"Character '**{character_name}**' not found in party '**{party_name}**'.", ephemeral=True)
                return

            party.characters.remove(char)
            db.commit()
            logger.info(f"/party_remove completed for user {interaction.user.id}: removed '{character_name}' from '{party_name}'")
            await interaction.response.send_message(Strings.PARTY_MEMBER_REMOVED.format(character_name=character_name, party_name=party_name))
        finally:
            db.close()

    @party_remove.autocomplete("party_name")
    async def party_remove_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @party_remove.autocomplete("character_name")
    async def party_remove_character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party_name = interaction.namespace.party_name
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
            if not party: return []
            return [app_commands.Choice(name=c.name, value=c.name) for c in party.characters if current.lower() in c.name.lower()][:25]
        finally:
            db.close()

    @bot.tree.command(name="active_party", description="Set or view your active party in this server")
    @app_commands.describe(party_name="The name of the party to set as active (leave blank to view)")
    async def active_party(interaction: discord.Interaction, party_name: Optional[str] = None) -> None:
        logger.debug(f"Command /active_party called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {party_name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if party_name:
                party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
                if not party:
                    await interaction.response.send_message(Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True)
                    return

                # Ensure the user-server association exists
                stmt = select(user_server_association).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id
                )
                assoc = db.execute(stmt).fetchone()

                if assoc:
                    stmt = update(user_server_association).where(
                        user_server_association.c.user_id == user.id,
                        user_server_association.c.server_id == server.id
                    ).values(active_party_id=party.id)
                    db.execute(stmt)
                else:
                    from sqlalchemy import insert
                    stmt = insert(user_server_association).values(
                        user_id=user.id,
                        server_id=server.id,
                        active_party_id=party.id
                    )
                    db.execute(stmt)

                db.commit()
                logger.info(f"/active_party completed for user {interaction.user.id}: set active party to '{party_name}'")
                await interaction.response.send_message(Strings.PARTY_ACTIVE_SET.format(party_name=party_name))
            else:
                stmt = select(user_server_association.c.active_party_id).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id
                )
                result = db.execute(stmt).fetchone()
                if result and result[0]:
                    party = db.get(Party, result[0])
                    char_names = ", ".join([c.name for c in party.characters])
                    logger.info(f"/active_party completed for user {interaction.user.id}: viewed active party '{party.name}'")
                    await interaction.response.send_message(Strings.PARTY_ACTIVE_VIEW.format(party_name=party.name, char_names=char_names))
                else:
                    await interaction.response.send_message(Strings.PARTY_ACTIVE_NONE)
        finally:
            db.close()

    @active_party.autocomplete("party_name")
    async def active_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @bot.tree.command(name="rollas", description="Roll as a member of your active party")
    @app_commands.describe(member_name="The name of the party member", notation="Skill or dice notation")
    async def rollas(interaction: discord.Interaction, member_name: str, notation: str) -> None:
        logger.debug(f"Command /rollas called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} - member: {member_name}, notation: {notation}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            stmt = select(user_server_association.c.active_party_id).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            )
            result = db.execute(stmt).fetchone()
            if not result or not result[0]:
                await interaction.response.send_message(Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True)
                return

            party = db.get(Party, result[0])
            char = next((c for c in party.characters if c.name == member_name), None)
            logger.debug(f"Member lookup for /rollas: {'found: ' + char.name if char else 'not found'} in party '{party.name}'")
            if not char:
                await interaction.response.send_message(Strings.PARTY_ACTIVE_MEMBER_NOT_FOUND.format(member_name=member_name), ephemeral=True)
                return

            response = await perform_roll(char, notation, db)
            await interaction.response.send_message(response)
            logger.info(f"/rollas completed for user {interaction.user.id}: rolled {notation} as '{member_name}'")
        finally:
            db.close()

    @rollas.autocomplete("member_name")
    async def rollas_member_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not user or not server: return []
            stmt = select(user_server_association.c.active_party_id).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            )
            result = db.execute(stmt).fetchone()
            if not result or not result[0]: return []
            party = db.get(Party, result[0])
            return [app_commands.Choice(name=c.name, value=c.name) for c in party.characters if current.lower() in c.name.lower()][:25]
        finally:
            db.close()

    @bot.tree.command(name="partyroll", description="Roll for every member of your active party")
    async def partyroll(interaction: discord.Interaction, notation: str) -> None:
        logger.debug(f"Command /partyroll called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} - notation: {notation}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            stmt = select(user_server_association.c.active_party_id).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            )
            result = db.execute(stmt).fetchone()
            if not result or not result[0]:
                await interaction.response.send_message(Strings.ERROR_PARTY_SET_ACTIVE_FIRST, ephemeral=True)
                return

            party = db.get(Party, result[0])
            if not party.characters:
                await interaction.response.send_message(Strings.PARTY_ROLL_EMPTY, ephemeral=True)
                return

            await interaction.response.defer()
            results = []
            for char in party.characters:
                res = await perform_roll(char, notation, db)
                results.append(res)

            response = Strings.PARTY_ROLL_HEADER.format(notation=notation, party_name=party.name) + "\n".join(results)
            if len(response) > 2000:
                await interaction.followup.send(response[:1997] + "...")
            else:
                await interaction.followup.send(response)
            logger.info(f"/partyroll completed for user {interaction.user.id}: rolled {notation} for {len(party.characters)} members in '{party.name}'")
        finally:
            db.close()

    @bot.tree.command(name="view_party", description="View details of a party")
    @app_commands.describe(party_name="The name of the party to view")
    async def view_party(interaction: discord.Interaction, party_name: str) -> None:
        logger.debug(f"Command /view_party called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {party_name}")
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True)
                return

            embed = discord.Embed(title=Strings.PARTY_VIEW_TITLE.format(party_name=party.name), color=discord.Color.blue())
            gm_mentions = " ".join(f"<@{gm.discord_id}>" for gm in party.gms)
            embed.add_field(name=Strings.PARTY_VIEW_GM, value=gm_mentions or "None", inline=False)

            if not party.characters:
                embed.description = Strings.PARTY_VIEW_EMPTY
            else:
                members_info = []
                for char in party.characters:
                    members_info.append(Strings.PARTY_VIEW_MEMBER_LINE.format(char_name=char.name, char_level=char.level, discord_id=char.user.discord_id))
                embed.add_field(name=Strings.PARTY_VIEW_MEMBERS, value="\n".join(members_info), inline=False)

            await interaction.response.send_message(embed=embed)
            logger.info(f"/view_party completed for user {interaction.user.id}: viewed '{party_name}'")
        finally:
            db.close()

    @view_party.autocomplete("party_name")
    async def view_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @bot.tree.command(name="delete_party", description="Delete a party")
    async def delete_party(interaction: discord.Interaction, party_name: str) -> None:
        logger.debug(f"Command /delete_party called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {party_name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(Strings.PARTY_NOT_FOUND.format(party_name=party_name), ephemeral=True)
                return

            if not user or user not in party.gms:
                await interaction.response.send_message(Strings.ERROR_GM_ONLY_PARTY_DELETE, ephemeral=True)
                return

            db.delete(party)
            db.commit()
            logger.info(f"/delete_party completed for user {interaction.user.id}: deleted '{party_name}'")
            await interaction.response.send_message(Strings.PARTY_DELETE_SUCCESS.format(party_name=party_name))
        finally:
            db.close()

    @delete_party.autocomplete("party_name")
    async def delete_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @bot.tree.command(name="add_gm", description="Add a Discord user as a GM of a party (GM only)")
    @app_commands.describe(
        party_name="The name of the party",
        new_gm="The Discord user to add as a GM"
    )
    async def add_gm(interaction: discord.Interaction, party_name: str, new_gm: discord.Member) -> None:
        """Add a new GM to the party. Only existing GMs may use this command."""
        logger.debug(
            f"Command /add_gm called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} - party: {party_name}, new_gm: {new_gm.id}"
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
                await interaction.response.send_message(Strings.ERROR_GM_ONLY_ADD_GM, ephemeral=True)
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
                f"/add_gm completed: user {interaction.user.id} added {new_gm.id} as GM of '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.GM_ADDED.format(discord_id=new_gm.id, party_name=party_name)
            )
        finally:
            db.close()

    @add_gm.autocomplete("party_name")
    async def add_gm_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)

    @bot.tree.command(name="remove_gm", description="Remove a GM from a party (GM only)")
    @app_commands.describe(
        party_name="The name of the party",
        target_gm="The Discord user to remove as a GM"
    )
    async def remove_gm(interaction: discord.Interaction, party_name: str, target_gm: discord.Member) -> None:
        """Remove a GM from the party. The last GM cannot be removed."""
        logger.debug(
            f"Command /remove_gm called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} - party: {party_name}, target_gm: {target_gm.id}"
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
                await interaction.response.send_message(Strings.ERROR_GM_ONLY_REMOVE_GM, ephemeral=True)
                return

            target = db.query(User).filter_by(discord_id=str(target_gm.id)).first()
            if not target or target not in party.gms:
                await interaction.response.send_message(
                    Strings.ERROR_GM_NOT_IN_PARTY.format(discord_id=target_gm.id, party_name=party_name),
                    ephemeral=True,
                )
                return

            if len(party.gms) == 1:
                await interaction.response.send_message(Strings.ERROR_GM_LAST, ephemeral=True)
                return

            party.gms.remove(target)
            db.commit()
            logger.info(
                f"/remove_gm completed: user {interaction.user.id} removed {target_gm.id} as GM of '{party_name}'"
            )
            await interaction.response.send_message(
                Strings.GM_REMOVED.format(discord_id=target_gm.id, party_name=party_name)
            )
        finally:
            db.close()

    @remove_gm.autocomplete("party_name")
    async def remove_gm_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)
