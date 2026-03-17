import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from database import SessionLocal
from models import User, Server, Character, CharacterSkill, EncounterTurn
from enums.encounter_status import EncounterStatus
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.constants import SKILL_TO_STAT
from utils.dnd_logic import get_proficiency_bonus, get_stat_modifier
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

def register_character_commands(bot: commands.Bot) -> None:
    """
    Registers character management slash commands to the bot's command tree.

    For those familiar with Python but new to Discord.py:
    - @bot.tree.command: Defines a 'Slash Command' (e.g., /create_character).
    - discord.Interaction: The context object for the event, containing info about the user,
      the server (guild), and the channel.
    - await interaction.response.send_message: How the bot replies. A command MUST be responded to
      within 3 seconds, or it will time out.
    """
    @bot.tree.command(name="create_character", description="Create a new D&D character for this server")
    @app_commands.describe(name="The name of your character")
    async def create_character(interaction: discord.Interaction, name: str, level: int) -> None:
        logger.debug(f"Command /create_character called by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id} with name: {name}")
        db = SessionLocal()

        if len(name) > 100:
            # ephemeral=True means only the user who ran the command can see the response.
            await interaction.response.send_message(Strings.CHAR_CREATE_NAME_LIMIT, ephemeral=True)
            return
        try:
            # discord_id is stored as a string to prevent precision loss with large snowflakes.
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            if not user:
                user = User(discord_id=str(interaction.user.id))
                db.add(user)
                db.flush() # Flush to get the ID without committing yet.

            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not server:
                server = Server(discord_id=str(interaction.guild_id), name=interaction.guild.name)
                db.add(server)
                db.flush()

            existing_char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            if existing_char:
                await interaction.response.send_message(Strings.CHAR_EXISTS.format(name=name), ephemeral=True)
                return
            if level < 1 or level > 20:
                await interaction.response.send_message(Strings.CHAR_LEVEL_LIMIT, ephemeral=True)
                return
            # Deactivate all other characters for this user in this server
            db.query(Character).filter_by(user=user, server=server).update({"is_active": False})

            new_char = Character(name=name, user=user, server=server, level= level, is_active=True)
            db.add(new_char)
            db.commit()
            logger.info(f"/create_character completed for user {interaction.user.id}: created '{name}' at level {level}")
            await interaction.response.send_message(Strings.CHAR_CREATED_ACTIVE.format(name=name, level=level))
        finally:
            db.close()

    @bot.tree.command(name="set_stats", description="Set your character's core stats")
    @app_commands.describe(
        strength="Strength score (1-30)",
        dexterity="Dexterity score (1-30)",
        constitution="Constitution score (1-30)",
        intelligence="Intelligence score (1-30)",
        wisdom="Wisdom score (1-30)",
        charisma="Charisma score (1-30)",
        initiative_bonus="Initiative bonus (optional, defaults to Dex mod)"
    )
    async def set_stats(
        interaction: discord.Interaction,
        # In slash commands, Optional[int] = None means the argument is not required by the user.
        strength: Optional[int] = None, dexterity: Optional[int] = None, constitution: Optional[int] = None,
        intelligence: Optional[int] = None, wisdom: Optional[int] = None, charisma: Optional[int] = None,
        initiative_bonus: Optional[int] = None
    ) -> None:
        logger.debug(f"Command /set_stats called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.CHARACTER_NOT_FOUND, ephemeral=True)
                return

            # Check for first-time registration (if any existing core stats are None)
            is_first_time = any(getattr(char, s) is None for s in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"])

            if is_first_time:
                # Must provide all core stats
                if any(s is None for s in [strength, dexterity, constitution, intelligence, wisdom, charisma]):
                    await interaction.response.send_message(Strings.CHAR_STATS_FIRST_TIME, ephemeral=True)
                    return

            # Validation and update
            stats_to_update = {
                "strength": strength,
                "dexterity": dexterity,
                "constitution": constitution,
                "intelligence": intelligence,
                "wisdom": wisdom,
                "charisma": charisma
            }

            for stat_name, value in stats_to_update.items():
                if value is not None:
                    if not (1 <= value <= 30):
                        await interaction.response.send_message(Strings.CHAR_STAT_LIMIT.format(stat_name=stat_name.title()), ephemeral=True)
                        return
                    setattr(char, stat_name, value)

            # Initiative bonus is always optional
            if initiative_bonus is not None:
                char.initiative_bonus = initiative_bonus

            db.commit()
            logger.info(f"/set_stats completed for user {interaction.user.id}: updated stats for '{char.name}'")
            await interaction.response.send_message(Strings.CHAR_STATS_UPDATED.format(char_name=char.name))
        finally:
            db.close()

    @bot.tree.command(name="set_saving_throws", description="Set your character's saving throw proficiencies")
    @app_commands.describe(
        strength="Proficient in Strength saving throws?",
        dexterity="Proficient in Dexterity saving throws?",
        constitution="Proficient in Constitution saving throws?",
        intelligence="Proficient in Intelligence saving throws?",
        wisdom="Proficient in Wisdom saving throws?",
        charisma="Proficient in Charisma saving throws?"
    )
    async def set_saving_throws(
        interaction: discord.Interaction,
        strength: bool = False, dexterity: bool = False, constitution: bool = False,
        intelligence: bool = False, wisdom: bool = False, charisma: bool = False
    ) -> None:
        logger.debug(f"Command /set_saving_throws called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.CHARACTER_NOT_FOUND, ephemeral=True)
                return

            char.st_prof_strength = strength
            char.st_prof_dexterity = dexterity
            char.st_prof_constitution = constitution
            char.st_prof_intelligence = intelligence
            char.st_prof_wisdom = wisdom
            char.st_prof_charisma = charisma

            db.commit()
            logger.info(f"/set_saving_throws completed for user {interaction.user.id}: updated saves for '{char.name}'")
            await interaction.response.send_message(Strings.CHAR_SAVES_UPDATED.format(char_name=char.name))
        finally:
            db.close()

    @bot.tree.command(name="view_character", description="View your character's stats, skills, and saving throws")
    async def view_character(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /view_character called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND + " Use `/create_character` or `/switch_character`.", ephemeral=True)
                return

            prof_bonus = get_proficiency_bonus(char.level)

            # Embeds are rich-text messages commonly used in Discord for structured data.
            embed = discord.Embed(
                title=Strings.CHAR_VIEW_TITLE.format(char_name=char.name),
                description=Strings.CHAR_VIEW_DESC.format(char_level=char.level),
                color=discord.Color.blue()
            )

            dex_mod = get_stat_modifier(char.dexterity)
            init_bonus = char.initiative_bonus if char.initiative_bonus is not None else dex_mod
            embed.description += Strings.CHAR_VIEW_INIT.format(init_bonus=init_bonus)

            # Core Stats
            stats_display = []
            for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
                val = getattr(char, stat)
                mod = get_stat_modifier(val)
                stats_display.append(f"**{stat.title()[:3]}**: {val} ({mod:+d})")

            embed.add_field(name=Strings.CHAR_VIEW_STATS_FIELD, value=" | ".join(stats_display), inline=False)

            # Saving Throws
            saves_display = []
            for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
                val = getattr(char, stat)
                mod = get_stat_modifier(val)
                is_prof = getattr(char, f"st_prof_{stat}")
                save_mod = mod + (prof_bonus if is_prof else 0)
                prof_mark = "●" if is_prof else "○"
                saves_display.append(f"{prof_mark} {stat.title()[:3]}: {save_mod:+d}")

            embed.add_field(name=Strings.CHAR_VIEW_SAVES_FIELD, value="\n".join(saves_display), inline=True)

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
                    mark = "◗"
                else:
                    mark = "○"

                skills_display.append(f"{mark} {skill_name}: {skill_mod:+d}")

            # Split skills into two columns if needed, or just one
            embed.add_field(name=Strings.CHAR_VIEW_SKILLS_FIELD, value="\n".join(skills_display[:9]), inline=True)
            embed.add_field(name=Strings.CHAR_VIEW_SKILLS_CONT_FIELD, value="\n".join(skills_display[9:]), inline=True)

            await interaction.response.send_message(embed=embed)
            logger.info(f"/view_character completed for user {interaction.user.id}: viewed '{char.name}'")
        finally:
            db.close()

    @bot.tree.command(name="switch_character", description="Switch your active character in this server")
    @app_commands.describe(name="The name of the character to switch to")
    async def switch_character(interaction: discord.Interaction, name: str) -> None:
        logger.debug(f"Command /switch_character called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")
            if not char:
                await interaction.response.send_message(Strings.CHAR_NOT_FOUND_NAME.format(name=name), ephemeral=True)
                return

            # Deactivate all others, activate this one
            db.query(Character).filter_by(user=user, server=server).update({"is_active": False})
            char.is_active = True
            db.commit()
            logger.info(f"/switch_character completed for user {interaction.user.id}: switched to '{name}'")
            await interaction.response.send_message(Strings.CHAR_SWITCH_SUCCESS.format(name=name))
        finally:
            db.close()

    @switch_character.autocomplete("name")
    async def switch_character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """
        Provides real-time suggestions as the user types the 'name' argument.
        The 'current' string is what the user has typed so far.
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            if not user or not server:
                return []

            chars = db.query(Character).filter_by(user=user, server=server).all()
            # Return a list of app_commands.Choice objects (max 25 allowed by Discord).
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars if current.lower() in c.name.lower()
            ][:25]
        finally:
            db.close()

    @bot.tree.command(name="set_level", description="Set your character's level (1-20)")
    @app_commands.describe(level="Your character's level")
    async def set_level(interaction: discord.Interaction, level: int) -> None:
        logger.debug(f"Command /set_level called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with level: {level}")
        if not (1 <= level <= 20):
            await interaction.response.send_message(Strings.CHAR_LEVEL_LIMIT, ephemeral=True)
            return

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return

            char.level = level
            db.commit()
            logger.info(f"/set_level completed for user {interaction.user.id}: '{char.name}' set to level {level}")
            await interaction.response.send_message(Strings.CHAR_LEVEL_UPDATED.format(char_name=char.name, level=level))
        finally:
            db.close()

    @bot.tree.command(name="set_skill", description="Set proficiency status for a skill")
    @app_commands.describe(
        skill="The skill to set",
        status="Proficiency status"
    )
    # app_commands.choices creates a fixed dropdown menu for the user in the Discord UI.
    @app_commands.choices(status=[
        app_commands.Choice(name="Not Proficient", value="not_proficient"),
        app_commands.Choice(name="Proficient", value="proficient"),
        app_commands.Choice(name="Expertise", value="expertise"),
        app_commands.Choice(name="Jack of All Trades", value="jack_of_all_trades")
    ])
    async def set_skill(interaction: discord.Interaction, skill: str, status: str) -> None:
        logger.debug(f"Command /set_skill called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with skill: {skill}, status: {status}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return

            # Find matching skill from SKILL_TO_STAT keys
            matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == skill.lower()), None)
            if not matched_skill:
                logger.warning(f"User {interaction.user.id} sent unknown skill: '{skill}'")
                await interaction.response.send_message(Strings.CHAR_SKILL_UNKNOWN.format(skill=skill), ephemeral=True)
                return

            prof_enum = SkillProficiencyStatus(status)
            char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=matched_skill).first()

            if not char_skill:
                char_skill = CharacterSkill(character_id=char.id, skill_name=matched_skill, proficiency=prof_enum)
                db.add(char_skill)
            else:
                char_skill.proficiency = prof_enum

            db.commit()
            logger.info(f"/set_skill completed for user {interaction.user.id}: '{char.name}' {matched_skill} -> {prof_enum.name}")
            await interaction.response.send_message(Strings.CHAR_SKILL_UPDATED.format(skill=matched_skill, char_name=char.name, status=prof_enum.name.replace('_', ' ').title()))
        finally:
            db.close()

    @bot.tree.command(name="characters", description="View all of your characters in this server")
    async def characters(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /characters called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            # interaction.guild_id is only present if the command is run in a server (not a DM).
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if not user or not server:
                await interaction.response.send_message(Strings.CHAR_LIST_NONE, ephemeral=True)
                return

            chars = db.query(Character).filter_by(user=user, server=server).all()
            logger.debug(f"Character list for user {interaction.user.id}: found {len(chars)} character(s)")
            if not chars:
                await interaction.response.send_message(Strings.CHAR_LIST_NONE, ephemeral=True)
                return

            embed = discord.Embed(
                title=Strings.CHAR_LIST_TITLE.format(user_name=interaction.user.display_name),
                description=Strings.CHAR_LIST_DESC.format(server_name=interaction.guild.name),
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
            logger.info(f"/characters completed for user {interaction.user.id}: listed {len(chars)} character(s)")
        finally:
            db.close()

    @bot.tree.command(name="delete_character", description="Permanently delete one of your characters")
    @app_commands.describe(name="The name of the character to delete")
    async def delete_character(interaction: discord.Interaction, name: str) -> None:
        logger.debug(f"Command /delete_character called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id} with name: {name}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if not user or not server:
                await interaction.response.send_message(Strings.CHAR_LIST_NONE, ephemeral=True)
                return

            char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")
            if not char:
                await interaction.response.send_message(Strings.CHAR_NOT_FOUND_NAME.format(name=name), ephemeral=True)
                return

            # Block deletion if the character is in an active encounter
            active_turn = (
                db.query(EncounterTurn)
                .filter_by(character_id=char.id)
                .join(EncounterTurn.encounter)
                .filter_by(status=EncounterStatus.ACTIVE)
                .first()
            )
            if active_turn:
                await interaction.response.send_message(
                    f"**{char.name}** is in an active encounter. End the encounter before deleting this character.",
                    ephemeral=True,
                )
                return

            # Cascade delete handles character_skill, attack, and encounter_turn entries
            db.delete(char)
            db.commit()
            logger.info(f"/delete_character completed for user {interaction.user.id}: deleted '{name}'")
            await interaction.response.send_message(Strings.CHAR_DELETE_SUCCESS.format(name=name))
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