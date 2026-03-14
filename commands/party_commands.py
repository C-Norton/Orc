import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from sqlalchemy import update, select
from database import SessionLocal
from models import User, Server, Character, Party, user_server_association
from utils.dnd_logic import perform_roll

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

            stmt = update(user_server_association).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            ).values(active_party_id=new_party.id)
            db.execute(stmt)
            db.commit()

            if not found_chars:
                msg = f"Empty party '**{party_name}**' created successfully!"
            else:
                msg = f"Party '**{party_name}**' created successfully with {len(found_chars)} characters!"
            
            if not_found:
                msg += f"\nCharacters not found: {', '.join(not_found)}"
            
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
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if party.gm_id != user.id:
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
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if party.gm_id != user.id:
                await interaction.response.send_message("Only the GM of the party can remove members.", ephemeral=True)
                return

            # Find the character in the party
            char = next((c for c in party.characters if c.name == character_name and (not character_owner or str(c.user.discord_id) == str(character_owner.id))), None)

            if not char:
                await interaction.response.send_message(f"Character '**{character_name}**' not found in party '**{party_name}**'.", ephemeral=True)
                return

            party.characters.remove(char)
            db.commit()
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
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if party_name:
                party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
                if not party:
                    await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                    return
                
                stmt = update(user_server_association).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id
                ).values(active_party_id=party.id)
                db.execute(stmt)
                db.commit()
                await interaction.response.send_message(f"Set '**{party_name}**' as your active party.")
            else:
                stmt = select(user_server_association.c.active_party_id).where(
                    user_server_association.c.user_id == user.id,
                    user_server_association.c.server_id == server.id
                )
                result = db.execute(stmt).fetchone()
                if result and result[0]:
                    party = db.query(Party).get(result[0])
                    char_names = ", ".join([c.name for c in party.characters])
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
            
            party = db.query(Party).get(result[0])
            char = next((c for c in party.characters if c.name == member_name), None)
            if not char:
                await interaction.response.send_message(f"Member '**{member_name}**' not found in your active party.", ephemeral=True)
                return
            
            response = await perform_roll(char, notation, db)
            await interaction.response.send_message(response)
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
            party = db.query(Party).get(result[0])
            return [app_commands.Choice(name=c.name, value=c.name) for c in party.characters if current.lower() in c.name.lower()][:25]
        finally:
            db.close()

    @bot.tree.command(name="partyroll", description="Roll for every member of your active party")
    async def partyroll(interaction: discord.Interaction, notation: str) -> None:
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
            
            party = db.query(Party).get(result[0])
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
        finally:
            db.close()

    @bot.tree.command(name="delete_party", description="Delete a party")
    async def delete_party(interaction: discord.Interaction, party_name: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

            if not party:
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            if party.gm_id != user.id:
                await interaction.response.send_message("Only the GM can delete the party.", ephemeral=True)
                return

            db.delete(party)
            db.commit()
            await interaction.response.send_message(f"Party '**{party_name}**' deleted successfully.")
        finally:
            db.close()

    @delete_party.autocomplete("party_name")
    async def delete_party_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await party_name_autocomplete(interaction, current)
