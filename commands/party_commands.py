import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import update, select
from database import SessionLocal
from models import User, Server, Character, Party, user_server_association
from utils.dnd_logic import perform_roll
from utils.logging_config import get_logger

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
                await interaction.response.send_message("User or Server not initialized.", ephemeral=True)
                return

            existing_party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
            if existing_party:
                await interaction.response.send_message(f"A party named '**{party_name}**' already exists in this server.", ephemeral=True)
                return

            new_party = Party(name=party_name, gm=user, server=server)

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
                msg = f"Empty party '**{party_name}**' created successfully!"
            else:
                msg = f"Party '**{party_name}**' created successfully with {len(found_chars)} characters!"

            if not_found:
                msg += f"\nCharacters not found: {', '.join(not_found)}"

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
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message("Only the GM of the party can add members.", ephemeral=True)
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
                await interaction.response.send_message(f"Character '**{character_name}**' not found.", ephemeral=True)
                return

            if len(chars) > 1:
                await interaction.response.send_message(f"Multiple characters named '**{character_name}**' found. Please specify the owner.", ephemeral=True)
                return

            char = chars[0]
            if char in party.characters:
                await interaction.response.send_message(f"**{character_name}** is already in the party.", ephemeral=True)
                return

            party.characters.append(char)
            db.commit()
            logger.info(f"/party_add completed for user {interaction.user.id}: added '{character_name}' to '{party_name}'")
            await interaction.response.send_message(f"Added **{character_name}** (owned by <@{char.user.discord_id}>) to party '**{party_name}**'.")
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
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message("Only the GM of the party can remove members.", ephemeral=True)
                return

            # Find the character in the party
            char = next((c for c in party.characters if c.name == character_name and (not character_owner or str(c.user.discord_id) == str(character_owner.id))), None)

            if not char:
                await interaction.response.send_message(f"Character '**{character_name}**' not found in party '**{party_name}**'.", ephemeral=True)
                return

            party.characters.remove(char)
            db.commit()
            logger.info(f"/party_remove completed for user {interaction.user.id}: removed '{character_name}' from '{party_name}'")
            await interaction.response.send_message(f"Removed **{character_name}** from party '**{party_name}**'.")
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
                    await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
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
                await interaction.response.send_message(f"Set '**{party_name}**' as your active party.")
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
                    await interaction.response.send_message(f"Your active party is '**{party.name}**'.\nMembers: {char_names}")
                else:
                    await interaction.response.send_message("You don't have an active party set.")
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
                await interaction.response.send_message("Set an active party first with `/active_party`.", ephemeral=True)
                return

            party = db.get(Party, result[0])
            char = next((c for c in party.characters if c.name == member_name), None)
            logger.debug(f"Member lookup for /rollas: {'found: ' + char.name if char else 'not found'} in party '{party.name}'")
            if not char:
                await interaction.response.send_message(f"Member '**{member_name}**' not found in your active party.", ephemeral=True)
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
                await interaction.response.send_message("Set an active party first with `/active_party`.", ephemeral=True)
                return

            party = db.get(Party, result[0])
            if not party.characters:
                await interaction.response.send_message("Your active party is empty.", ephemeral=True)
                return

            await interaction.response.defer()
            results = []
            for char in party.characters:
                res = await perform_roll(char, notation, db)
                results.append(res)

            response = f"🎲 **Party Roll: {notation}** (Party: {party.name})\n" + "\n".join(results)
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
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            embed = discord.Embed(title=f"Party: {party.name}", color=discord.Color.blue())
            embed.add_field(name="GM", value=f"<@{party.gm.discord_id}>", inline=False)

            if not party.characters:
                embed.description = "This party has no members."
            else:
                members_info = []
                for char in party.characters:
                    members_info.append(f"● **{char.name}** (Level {char.level}) - Controlled by <@{char.user.discord_id}>")
                embed.add_field(name="Members", value="\n".join(members_info), inline=False)

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
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if not user or party.gm_id != user.id:
                await interaction.response.send_message("Only the GM can delete the party.", ephemeral=True)
                return

            db.delete(party)
            db.commit()
            logger.info(f"/delete_party completed for user {interaction.user.id}: deleted '{party_name}'")
            await interaction.response.send_message(f"Party '**{party_name}**' deleted successfully.")
        finally:
            db.close()

    @delete_party.autocomplete("party_name")
    async def delete_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)
