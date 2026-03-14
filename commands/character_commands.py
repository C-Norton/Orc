import discord
from discord import app_commands
from discord.ext import commands
from typing import List
from database import SessionLocal
from models import User, Server, Character, CharacterSkill, Attack
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.constants import SKILL_TO_STAT
from utils.dnd_logic import get_proficiency_bonus, get_stat_modifier

def register_character_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="create_character", description="Create a new DnD character for this server")
    @app_commands.describe(name="The name of your character")
    async def create_character(interaction: discord.Interaction, name: str) -> None:
        db = SessionLocal()

        if len(name) > 100:
            await interaction.response.send_message("Character name cannot exceed 100 characters.", ephemeral=True)
            return
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            if not user:
                user = User(discord_id=str(interaction.user.id))
                db.add(user)
                db.flush()

            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not server:
                server = Server(discord_id=str(interaction.guild_id), name=interaction.guild.name)
                db.add(server)
                db.flush()

            existing_char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            if existing_char:
                await interaction.response.send_message(f"You already have a character named **{name}** in this server.", ephemeral=True)
                return

            # Deactivate all other characters for this user in this server
            db.query(Character).filter_by(user=user, server=server).update({"is_active": False})
            
            new_char = Character(name=name, user=user, server=server, is_active=True)
            db.add(new_char)
            db.commit()
            await interaction.response.send_message(f"Character **{name}** created successfully and set as active!\nNext, set your stats with '/set_stats', your skill proficiencies with 'set_skill', your saving throw proficiencies with '/set_saving_throws'\n View your character at any time with '/view_character', and switch with '/switch_character'")
        finally:
            db.close()

    @bot.tree.command(name="set_stats", description="Set your character's core stats")
    @app_commands.describe(
        strength="Strength score (1-30)",
        dexterity="Dexterity score (1-30)",
        constitution="Constitution score (1-30)",
        intelligence="Intelligence score (1-30)",
        wisdom="Wisdom score (1-30)",
        charisma="Charisma score (1-30)"
    )
    async def set_stats(
        interaction: discord.Interaction,
        strength: int, dexterity: int, constitution: int,
        intelligence: int, wisdom: int, charisma: int
    ) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
                return

            if strength < 1 or strength > 30:
                await interaction.response.send_message("Strength score must be between 1 and 30.", ephemeral=True)
                return
            if dexterity < 1 or dexterity > 30:
                await interaction.response.send_message("dexterity score must be between 1 and 30.", ephemeral=True)
                return
            if constitution < 1 or constitution > 30:
                await interaction.response.send_message("constitution score must be between 1 and 30.", ephemeral=True)
                return

            if intelligence < 1 or intelligence > 30:
                await interaction.response.send_message("intelligence score must be between 1 and 30.", ephemeral=True)
                return

            if wisdom < 1 or wisdom > 30:
                await interaction.response.send_message("wisdom score must be between 1 and 30.", ephemeral=True)
                return

            if charisma < 1 or charisma > 30:
                await interaction.response.send_message("charisma score must be between 1 and 30.", ephemeral=True)
                return

            char.strength = strength
            char.dexterity = dexterity
            char.constitution = constitution
            char.intelligence = intelligence
            char.wisdom = wisdom
            char.charisma = charisma

            db.commit()
            await interaction.response.send_message(f"Stats updated for **{char.name}**!")
        finally:
            db.close()

    @bot.tree.command(name="set_saving_throws", description="Set your character's saving throw proficiencies")
    @app_commands.describe(
        st_str="Proficient in Strength saving throws?",
        st_dex="Proficient in Dexterity saving throws?",
        st_con="Proficient in Constitution saving throws?",
        st_int="Proficient in Intelligence saving throws?",
        st_wis="Proficient in Wisdom saving throws?",
        st_cha="Proficient in Charisma saving throws?"
    )
    async def set_saving_throws(
        interaction: discord.Interaction,
        st_str: bool = False, st_dex: bool = False, st_con: bool = False,
        st_int: bool = False, st_wis: bool = False, st_cha: bool = False
    ) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
                return

            char.st_prof_strength = st_str
            char.st_prof_dexterity = st_dex
            char.st_prof_constitution = st_con
            char.st_prof_intelligence = st_int
            char.st_prof_wisdom = st_wis
            char.st_prof_charisma = st_cha

            db.commit()
            await interaction.response.send_message(f"Saving throw proficiencies updated for **{char.name}**!")
        finally:
            db.close()

    @bot.tree.command(name="view_character", description="View your character's stats, skills, and saving throws")
    async def view_character(interaction: discord.Interaction) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have an active character. Use `/create_character` or `/switch_character`.", ephemeral=True)
                return

            prof_bonus = get_proficiency_bonus(char.level)
            
            embed = discord.Embed(
                title=f"👤 {char.name}",
                description=f"Level {char.level} Character",
                color=discord.Color.blue()
            )

            # Core Stats
            stats_display = []
            for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
                val = getattr(char, stat)
                mod = get_stat_modifier(val)
                stats_display.append(f"**{stat.title()[:3]}**: {val} ({mod:+d})")
            
            embed.add_field(name="Ability Scores", value=" | ".join(stats_display), inline=False)

            # Saving Throws
            saves_display = []
            for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
                val = getattr(char, stat)
                mod = get_stat_modifier(val)
                is_prof = getattr(char, f"st_prof_{stat}")
                save_mod = mod + (prof_bonus if is_prof else 0)
                prof_mark = "●" if is_prof else "○"
                saves_display.append(f"{prof_mark} {stat.title()[:3]}: {save_mod:+d}")
            
            embed.add_field(name="Saving Throws", value="\n".join(saves_display), inline=True)

            # Skills
            skills_display = []
            char_skills = {s.skill_name: s.proficiency for s in char.skills}
            
            sorted_skills = sorted(SKILL_TO_STAT.keys())
            for skill_name in sorted_skills:
                stat_name = SKILL_TO_STAT[skill_name]
                stat_mod = get_stat_modifier(getattr(char, stat_name))
                prof_status = char_skills.get(skill_name, SkillProficiencyStatus.NOT_PROFICIENT)
                
                skill_mod = stat_mod
                if prof_status == SkillProficiencyStatus.PROFICIENT:
                    skill_mod += prof_bonus
                    mark = "●"
                elif prof_status == SkillProficiencyStatus.EXPERTISE:
                    skill_mod += 2 * prof_bonus
                    mark = "◉"
                elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
                    skill_mod += prof_bonus // 2
                    mark = "○"
                else:
                    mark = "○"
                
                skills_display.append(f"{mark} {skill_name}: {skill_mod:+d}")

            # Split skills into two columns if needed, or just one
            embed.add_field(name="Skills", value="\n".join(skills_display[:9]), inline=True)
            embed.add_field(name="Skills (cont.)", value="\n".join(skills_display[9:]), inline=True)

            await interaction.response.send_message(embed=embed)
        finally:
            db.close()

    @bot.tree.command(name="switch_character", description="Switch your active character in this server")
    @app_commands.describe(name="The name of the character to switch to")
    async def switch_character(interaction: discord.Interaction, name: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            
            char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            if not char:
                await interaction.response.send_message(f"You don't have a character named **{name}** in this server.", ephemeral=True)
                return

            # Deactivate all others, activate this one
            db.query(Character).filter_by(user=user, server=server).update({"is_active": False})
            char.is_active = True
            db.commit()
            
            await interaction.response.send_message(f"Switched to character **{name}**!")
        finally:
            db.close()

    @switch_character.autocomplete("name")
    async def switch_character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not user or not server:
                return []
            
            chars = db.query(Character).filter_by(user=user, server=server).all()
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars if current.lower() in c.name.lower()
            ]
        finally:
            db.close()

    @bot.tree.command(name="set_level", description="Set your character's level (1-20)")
    @app_commands.describe(level="Your character's level")
    async def set_level(interaction: discord.Interaction, level: int) -> None:
        if not (1 <= level <= 20):
            await interaction.response.send_message("Level must be between 1 and 20.", ephemeral=True)
            return

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have an active character.", ephemeral=True)
                return

            char.level = level
            db.commit()
            await interaction.response.send_message(f"**{char.name}** is now level **{level}**!")
        finally:
            db.close()

    @bot.tree.command(name="set_skill", description="Set proficiency status for a skill")
    @app_commands.describe(
        skill="The skill to set",
        status="Proficiency status"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Not Proficient", value="not_proficient"),
        app_commands.Choice(name="Proficient", value="proficient"),
        app_commands.Choice(name="Expertise", value="expertise"),
        app_commands.Choice(name="Jack of All Trades", value="jack_of_all_trades")
    ])
    async def set_skill(interaction: discord.Interaction, skill: str, status: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have an active character.", ephemeral=True)
                return

            # Find matching skill from SKILL_TO_STAT keys
            matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == skill.lower()), None)
            if not matched_skill:
                await interaction.response.send_message(f"Unknown skill: {skill}", ephemeral=True)
                return

            prof_enum = SkillProficiencyStatus(status)
            char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=matched_skill).first()
            
            if not char_skill:
                char_skill = CharacterSkill(character_id=char.id, skill_name=matched_skill, proficiency=prof_enum)
                db.add(char_skill)
            else:
                char_skill.proficiency = prof_enum

            db.commit()
            await interaction.response.send_message(f"Updated **{matched_skill}** for **{char.name}** to **{prof_enum.name.replace('_', ' ').title()}**")
        finally:
            db.close()

    @bot.tree.command(name="characters", description="View all of your characters in this server")
    async def characters(interaction: discord.Interaction) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if not user or not server:
                await interaction.response.send_message("You don't have any characters in this server.", ephemeral=True)
                return

            chars = db.query(Character).filter_by(user=user, server=server).all()
            if not chars:
                await interaction.response.send_message("You don't have any characters in this server.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Characters for {interaction.user.display_name}",
                description=f"In server: **{interaction.guild.name}**",
                color=discord.Color.blue()
            )

            for char in chars:
                status = " (Active)" if char.is_active else ""
                embed.add_field(
                    name=f"{char.name}{status}",
                    value=f"Level {char.level}",
                    inline=True
                )

            await interaction.response.send_message(embed=embed)
        finally:
            db.close()

    @bot.tree.command(name="delete_character", description="Permanently delete one of your characters")
    @app_commands.describe(name="The name of the character to delete")
    async def delete_character(interaction: discord.Interaction, name: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            
            if not user or not server:
                await interaction.response.send_message("You don't have any characters in this server.", ephemeral=True)
                return

            char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            if not char:
                await interaction.response.send_message(f"You don't have a character named **{name}** in this server.", ephemeral=True)
                return

            # Note: Cascade delete handles character_skill and attack entries
            db.delete(char)
            db.commit()
            
            await interaction.response.send_message(f"Character **{name}** has been deleted.")
        finally:
            db.close()

    @delete_character.autocomplete("name")
    async def delete_character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not user or not server:
                return []
            
            chars = db.query(Character).filter_by(user=user, server=server).all()
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars if current.lower() in c.name.lower()
            ]
        finally:
            db.close()
