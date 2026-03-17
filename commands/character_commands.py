import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from database import SessionLocal
from models import User, Server, Character, CharacterSkill, ClassLevel, EncounterTurn
from enums.character_class import CharacterClass
from enums.encounter_status import EncounterStatus
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.class_data import apply_class_save_profs, calculate_max_hp
from utils.constants import SKILL_TO_STAT
from utils.dnd_logic import get_proficiency_bonus, get_stat_modifier
from utils.limits import MAX_CHARACTERS_PER_USER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Character-sheet reaction state
# ---------------------------------------------------------------------------

# Maps message_id -> {"user_id": int, "char_id": int}
char_sheet_owners: dict[int, dict] = {}

CHAR_SHEET_EMOJIS = ["🏠", "📊", "🎯", "⚔️"]

_STAT_NAMES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
_STAT_ABBR = {"strength": "STR", "dexterity": "DEX", "constitution": "CON",
              "intelligence": "INT", "wisdom": "WIS", "charisma": "CHA"}


def _class_summary(char: Character) -> str:
    """Return e.g. 'Fighter 5' or 'Fighter 3 / Rogue 2'."""
    sorted_cls = sorted(char.class_levels, key=lambda cl: cl.id)
    return " / ".join(f"{cl.class_name} {cl.level}" for cl in sorted_cls) if sorted_cls else "No class"


def _build_sheet_page0(char: Character) -> discord.Embed:
    """Page 0 (🏠): intro/overview — identity, HP, initiative, proficiency bonus."""
    prof_bonus = get_proficiency_bonus(char.level)
    cls_summary = _class_summary(char)

    dex_mod = get_stat_modifier(char.dexterity)
    init_bonus = char.initiative_bonus if char.initiative_bonus is not None else dex_mod

    embed = discord.Embed(
        title=Strings.CHAR_SHEET_INTRO_TITLE.format(char_name=char.name),
        description=Strings.CHAR_SHEET_INTRO_DESC.format(
            char_level=char.level, class_summary=cls_summary
        ),
        color=discord.Color.blue(),
    )

    # Quick-reference block
    hp_str = (
        f"❤️ {char.current_hp}/{char.max_hp}"
        if char.max_hp != -1
        else "❤️ *Not set — use `/set_max_hp`*"
    )
    if char.temp_hp > 0:
        hp_str += f" (+{char.temp_hp} temp)"

    ac_str = (
        Strings.CHAR_SHEET_AC.format(ac=char.ac)
        if char.ac is not None
        else Strings.CHAR_SHEET_AC_NOT_SET
    )

    quick_lines = [
        hp_str,
        ac_str,
        f"🔰 Proficiency Bonus: **{prof_bonus:+d}**",
        f"⚡ Initiative: **{init_bonus:+d}**",
    ]
    embed.add_field(
        name=Strings.CHAR_SHEET_INTRO_QUICK_REF,
        value="\n".join(quick_lines),
        inline=False,
    )
    embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
    return embed


def _build_sheet_page1(char: Character) -> discord.Embed:
    """Page 1 (📊): ability scores and saving throws."""
    prof_bonus = get_proficiency_bonus(char.level)
    cls_summary = _class_summary(char)

    embed = discord.Embed(
        title=Strings.CHAR_VIEW_TITLE.format(char_name=char.name),
        description=Strings.CHAR_VIEW_DESC.format(
            char_level=char.level, class_summary=cls_summary
        ),
        color=discord.Color.blue(),
    )

    stats_set = all(getattr(char, s) is not None for s in _STAT_NAMES)
    if not stats_set:
        embed.add_field(
            name=Strings.CHAR_VIEW_STATS_FIELD,
            value=Strings.CHAR_SHEET_NO_STATS,
            inline=False,
        )
        embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
        return embed

    # Ability scores — two rows of three, rendered as a compact table
    stats_lines = []
    for stat in _STAT_NAMES:
        val = getattr(char, stat)
        mod = get_stat_modifier(val)
        abbr = _STAT_ABBR[stat]
        stats_lines.append(f"**{abbr}** {val:>2} ({mod:+d})")
    # Two columns of three
    embed.add_field(
        name=Strings.CHAR_VIEW_STATS_FIELD,
        value="\n".join(stats_lines[:3]),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\n".join(stats_lines[3:]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    # Saving throws
    saves_lines = []
    for stat in _STAT_NAMES:
        val = getattr(char, stat)
        mod = get_stat_modifier(val)
        is_prof = getattr(char, f"st_prof_{stat}")
        save_mod = mod + (prof_bonus if is_prof else 0)
        mark = "●" if is_prof else "○"
        abbr = _STAT_ABBR[stat]
        saves_lines.append(f"{mark} **{abbr}**: {save_mod:+d}")
    embed.add_field(
        name=Strings.CHAR_VIEW_SAVES_FIELD,
        value="\n".join(saves_lines[:3]),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\n".join(saves_lines[3:]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
    return embed


def _build_sheet_page2(char: Character) -> discord.Embed:
    """Page 2 (🎯): skill proficiencies and modifiers."""
    prof_bonus = get_proficiency_bonus(char.level)

    embed = discord.Embed(
        title=Strings.CHAR_VIEW_TITLE.format(char_name=char.name),
        description=Strings.CHAR_VIEW_SKILLS_FIELD,
        color=discord.Color.green(),
    )

    stats_set = all(getattr(char, s) is not None for s in _STAT_NAMES)
    if not stats_set:
        embed.add_field(name="\u200b", value=Strings.CHAR_SHEET_NO_STATS, inline=False)
        embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
        return embed

    char_skills = {s.skill_name: s.proficiency for s in char.skills}
    skills_display = []
    for skill_name in sorted(SKILL_TO_STAT.keys()):
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
        skills_display.append(f"{mark} **{skill_name}**: {skill_mod:+d}")

    mid = (len(skills_display) + 1) // 2
    embed.add_field(name="\u200b", value="\n".join(skills_display[:mid]), inline=True)
    embed.add_field(name="\u200b", value="\n".join(skills_display[mid:]), inline=True)
    embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
    return embed


def _build_sheet_page3(char: Character) -> discord.Embed:
    """Page 3 (⚔️): saved attacks."""
    embed = discord.Embed(
        title=Strings.CHAR_VIEW_TITLE.format(char_name=char.name),
        description=Strings.HELP_COMBAT_NAME,
        color=discord.Color.red(),
    )

    if not char.attacks:
        embed.add_field(name="\u200b", value=Strings.CHAR_SHEET_NO_ATTACKS, inline=False)
    else:
        for atk in char.attacks:
            embed.add_field(
                name=atk.name,
                value=f"**To Hit:** +{atk.hit_modifier}  |  **Damage:** `{atk.damage_formula}`",
                inline=False,
            )

    embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
    return embed


_SHEET_PAGE_BUILDERS = {
    "🏠": _build_sheet_page0,
    "📊": _build_sheet_page1,
    "🎯": _build_sheet_page2,
    "⚔️": _build_sheet_page3,
}


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
    @app_commands.describe(
        name="The name of your character",
        character_class="Your character's starting class",
        level="Starting level in that class (1-20)",
    )
    @app_commands.choices(character_class=[
        app_commands.Choice(name=cls.value, value=cls.value) for cls in CharacterClass
    ])
    async def create_character(
        interaction: discord.Interaction, name: str, character_class: str, level: int
    ) -> None:
        logger.debug(
            f"Command /create_character called by {interaction.user} (ID: {interaction.user.id}) "
            f"in guild {interaction.guild_id} with name: {name}, class: {character_class}, level: {level}"
        )
        db = SessionLocal()

        if len(name) > 100:
            await interaction.response.send_message(Strings.CHAR_CREATE_NAME_LIMIT, ephemeral=True)
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

            char_count = db.query(Character).filter_by(user_id=user.id).count()
            if char_count >= MAX_CHARACTERS_PER_USER:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_CHARACTERS.format(limit=MAX_CHARACTERS_PER_USER),
                    ephemeral=True,
                )
                return

            existing_char = db.query(Character).filter_by(user=user, server=server, name=name).first()
            if existing_char:
                await interaction.response.send_message(Strings.CHAR_EXISTS.format(name=name), ephemeral=True)
                return
            if level < 1 or level > 20:
                await interaction.response.send_message(Strings.CHAR_LEVEL_LIMIT, ephemeral=True)
                return

            db.query(Character).filter_by(user=user, server=server).update({"is_active": False})

            new_char = Character(name=name, user=user, server=server, is_active=True)
            db.add(new_char)
            db.flush()

            cls_enum = CharacterClass(character_class)
            db.add(ClassLevel(character_id=new_char.id, class_name=cls_enum.value, level=level))
            db.flush()
            db.refresh(new_char)

            apply_class_save_profs(new_char, cls_enum)
            db.commit()
            logger.info(
                f"/create_character completed for user {interaction.user.id}: "
                f"created '{name}' as level {level} {character_class}"
            )
            await interaction.response.send_message(
                Strings.CHAR_CREATED_ACTIVE.format(name=name, level=level, char_class=character_class)
            )
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

            # Recalculate max HP whenever CON changes (class levels must already exist)
            if constitution is not None and char.class_levels:
                new_max = calculate_max_hp(char)
                if new_max != -1:
                    char.max_hp = new_max
                    char.current_hp = new_max

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

    @bot.tree.command(name="view_character", description="View your character sheet")
    async def view_character(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /view_character called by {interaction.user} (ID: {interaction.user.id}) for guild {interaction.guild_id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND + " Use `/create_character` or `/switch_character`.",
                    ephemeral=True,
                )
                return

            embed = _build_sheet_page0(char)
            await interaction.response.send_message(embed=embed)
            message = await interaction.original_response()

            char_sheet_owners[message.id] = {"user_id": interaction.user.id, "char_id": char.id}

            for emoji in CHAR_SHEET_EMOJIS:
                await message.add_reaction(emoji)

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

    @bot.tree.command(name="set_ac", description="Set your active character's Armor Class")
    @app_commands.describe(ac="Armor Class value (1-30)")
    async def set_ac(interaction: discord.Interaction, ac: int) -> None:
        logger.debug(f"Command /set_ac called by {interaction.user} (ID: {interaction.user.id}) with ac: {ac}")
        if not (1 <= ac <= 30):
            await interaction.response.send_message(Strings.CHAR_AC_LIMIT, ephemeral=True)
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

            char.ac = ac
            db.commit()
            logger.info(f"/set_ac completed for user {interaction.user.id}: '{char.name}' AC set to {ac}")
            await interaction.response.send_message(
                Strings.CHAR_AC_UPDATED.format(char_name=char.name, ac=ac)
            )
        finally:
            db.close()

    @bot.tree.command(name="add_class", description="Add or update a class level on your active character")
    @app_commands.describe(
        character_class="The class to add or update",
        level="Number of levels in this class",
    )
    @app_commands.choices(character_class=[
        app_commands.Choice(name=cls.value, value=cls.value) for cls in CharacterClass
    ])
    async def add_class(interaction: discord.Interaction, character_class: str, level: int) -> None:
        logger.debug(
            f"Command /add_class called by {interaction.user} (ID: {interaction.user.id}) "
            f"with class: {character_class}, level: {level}"
        )
        if level < 1 or level > 20:
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

            cls_enum = CharacterClass(character_class)
            existing_cl = db.query(ClassLevel).filter_by(
                character_id=char.id, class_name=cls_enum.value
            ).first()

            # Check total level cap (20)
            other_levels = sum(
                cl.level for cl in char.class_levels
                if cl.class_name != cls_enum.value
            )
            if other_levels + level > 20:
                await interaction.response.send_message(
                    Strings.CHAR_CLASS_TOTAL_LEVEL_EXCEEDED.format(
                        level=level,
                        char_class=character_class,
                        char_name=char.name,
                        current_total=char.level,
                    ),
                    ephemeral=True,
                )
                return

            is_first_class = not char.class_levels

            if existing_cl:
                existing_cl.level = level
                msg = Strings.CHAR_CLASS_UPDATED
            else:
                db.add(ClassLevel(character_id=char.id, class_name=cls_enum.value, level=level))
                msg = Strings.CHAR_CLASS_ADDED

            db.flush()
            db.refresh(char)

            # Apply save profs only when this is the very first class on the character
            if is_first_class:
                apply_class_save_profs(char, cls_enum)

            # Recalculate HP if stats are already set
            new_max = calculate_max_hp(char)
            if new_max != -1:
                char.max_hp = new_max
                char.current_hp = new_max

            db.commit()
            db.refresh(char)
            total = char.level
            logger.info(
                f"/add_class completed for user {interaction.user.id}: "
                f"'{char.name}' {character_class} level {level} (total {total})"
            )
            await interaction.response.send_message(
                msg.format(
                    char_name=char.name, char_class=character_class,
                    level=level, total_level=total
                )
            )
        finally:
            db.close()

    @bot.tree.command(name="remove_class", description="Remove a class from your active character")
    @app_commands.describe(character_class="The class to remove")
    @app_commands.choices(character_class=[
        app_commands.Choice(name=cls.value, value=cls.value) for cls in CharacterClass
    ])
    async def remove_class(interaction: discord.Interaction, character_class: str) -> None:
        logger.debug(
            f"Command /remove_class called by {interaction.user} (ID: {interaction.user.id}) "
            f"with class: {character_class}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return

            cls_enum = CharacterClass(character_class)
            cl = db.query(ClassLevel).filter_by(
                character_id=char.id, class_name=cls_enum.value
            ).first()
            if not cl:
                await interaction.response.send_message(
                    Strings.CHAR_CLASS_NOT_FOUND.format(
                        char_name=char.name, char_class=character_class
                    ),
                    ephemeral=True,
                )
                return

            db.delete(cl)
            db.flush()
            db.refresh(char)

            # Recalculate HP if stats are still set (or mark unset if no classes remain)
            new_max = calculate_max_hp(char)
            if new_max != -1:
                char.max_hp = new_max
                char.current_hp = new_max
            elif not char.class_levels:
                char.max_hp = -1
                char.current_hp = -1

            db.commit()
            db.refresh(char)
            total = char.level
            logger.info(
                f"/remove_class completed for user {interaction.user.id}: "
                f"removed {character_class} from '{char.name}' (total level now {total})"
            )
            await interaction.response.send_message(
                Strings.CHAR_CLASS_REMOVED.format(
                    char_name=char.name, char_class=character_class, total_level=total
                )
            )
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
                sorted_cls = sorted(char.class_levels, key=lambda cl: cl.id)
                if sorted_cls:
                    class_summary = " / ".join(f"{cl.class_name} {cl.level}" for cl in sorted_cls)
                else:
                    class_summary = "No class"
                embed.add_field(
                    name=f"{char.name}{status}",
                    value=f"Level {char.level} — {class_summary}",
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

    # ------------------------------------------------------------------
    # Character sheet reaction handler
    # ------------------------------------------------------------------

    async def on_char_sheet_reaction(reaction: discord.Reaction, user: discord.User) -> None:
        """Switch character sheet pages when the owner clicks a navigation reaction."""
        if user.bot:
            return

        entry = char_sheet_owners.get(reaction.message.id)
        if not entry or user.id != entry["user_id"]:
            return

        emoji = str(reaction.emoji)
        builder = _SHEET_PAGE_BUILDERS.get(emoji)
        if builder is None:
            return

        db = SessionLocal()
        try:
            char = db.get(Character, entry["char_id"])
            if char is None:
                return
            embed = builder(char)
        finally:
            db.close()

        await reaction.message.edit(embed=embed)
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except (discord.Forbidden, discord.HTTPException):
            pass

    bot.add_listener(on_char_sheet_reaction, "on_reaction_add")