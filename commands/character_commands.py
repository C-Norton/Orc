import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from database import SessionLocal
from models import (
    User,
    Server,
    Character,
    CharacterSkill,
    ClassLevel,
    Encounter,
    EncounterTurn,
    Party,
)
from enums.character_class import CharacterClass
from enums.encounter_status import EncounterStatus
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.class_data import apply_class_save_profs, calculate_max_hp
from utils.constants import SKILL_TO_STAT
from utils.db_helpers import get_active_character, get_active_party, get_or_create_user_server
from utils.dnd_logic import get_proficiency_bonus, get_stat_modifier
from utils.limits import MAX_CHARACTERS_PER_USER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


class _ConfirmCharacterDeleteView(discord.ui.View):
    """Ephemeral confirmation shown before permanently deleting a character.

    If the character is in an active encounter the initial message explains
    that their turn will also be removed.  The confirm handler performs the
    cascade automatically regardless of encounter state.

    ✅ Delete — removes the active EncounterTurn (if any) then deletes the character.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, char_id: int, char_name: str) -> None:
        super().__init__(timeout=30)
        self.char_id = char_id
        self.char_name = char_name

    @discord.ui.button(label="Delete", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Delete the character, cascade-removing any active EncounterTurn first."""
        db = SessionLocal()
        try:
            char = db.get(Character, self.char_id)
            if not char:
                await interaction.response.edit_message(
                    content="Character no longer exists.", view=None
                )
                return

            # Cascade-remove active encounter turn if present
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

                if turn_count_after == 0:
                    encounter.current_turn_index = 0
                elif deleted_index < encounter.current_turn_index:
                    encounter.current_turn_index -= 1
                elif deleted_index == encounter.current_turn_index:
                    if encounter.current_turn_index >= turn_count_after:
                        encounter.current_turn_index = 0
                        encounter.round_number += 1

            db.delete(char)
            db.commit()
            logger.info(
                f"Confirmed deletion of character '{self.char_name}' (id={self.char_id})"
            )
            await interaction.response.edit_message(
                content=Strings.CHAR_DELETE_SUCCESS.format(name=self.char_name),
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
            content=Strings.CHAR_DELETE_CANCELLED, view=None
        )
        self.stop()


# ---------------------------------------------------------------------------
# Character-sheet page definitions
# ---------------------------------------------------------------------------

_STAT_NAMES = [
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
]
_STAT_ABBR = {
    "strength": "STR",
    "dexterity": "DEX",
    "constitution": "CON",
    "intelligence": "INT",
    "wisdom": "WIS",
    "charisma": "CHA",
}


def _class_summary(char: Character) -> str:
    """Return e.g. 'Fighter 5' or 'Fighter 3 / Rogue 2'."""
    sorted_cls = sorted(char.class_levels, key=lambda cl: cl.id)
    return (
        " / ".join(f"{cl.class_name} {cl.level}" for cl in sorted_cls)
        if sorted_cls
        else "No class"
    )


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

    hp_str = (
        f"❤️ {char.current_hp}/{char.max_hp}"
        if char.max_hp != -1
        else "❤️ *Not set — use `/character ac`*"
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

    stats_lines = []
    for stat in _STAT_NAMES:
        val = getattr(char, stat)
        mod = get_stat_modifier(val)
        abbr = _STAT_ABBR[stat]
        stats_lines.append(f"**{abbr}** {val:>2} ({mod:+d})")
    embed.add_field(
        name=Strings.CHAR_VIEW_STATS_FIELD,
        value="\n".join(stats_lines[:3]),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\n".join(stats_lines[3:]), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

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
    embed.add_field(name="\u200b", value="\u200b", inline=True)

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
        embed.add_field(
            name="\u200b", value=Strings.CHAR_SHEET_NO_ATTACKS, inline=False
        )
    else:
        for atk in char.attacks:
            embed.add_field(
                name=atk.name,
                value=f"**To Hit:** +{atk.hit_modifier}  |  **Damage:** `{atk.damage_formula}`",
                inline=False,
            )

    embed.set_footer(text=Strings.CHAR_SHEET_FOOTER)
    return embed


# (emoji, button_label, page_builder)
_SHEET_PAGES: list[tuple[str, str, object]] = [
    ("🏠", "Overview", _build_sheet_page0),
    ("📊", "Stats", _build_sheet_page1),
    ("🎯", "Skills", _build_sheet_page2),
    ("⚔️", "Attacks", _build_sheet_page3),
]


class _CharacterSheetPageButton(discord.ui.Button):
    """Navigate to a specific character-sheet page, re-fetching from the DB."""

    def __init__(self, emoji: str, label: str, builder: object, char_id: int) -> None:
        super().__init__(
            emoji=emoji, label=label, style=discord.ButtonStyle.secondary, row=0
        )
        self._builder = builder
        self._char_id = char_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Re-fetch the character and render the selected page."""
        db = SessionLocal()
        try:
            char = db.get(Character, self._char_id)
            if char is None:
                await interaction.response.edit_message(
                    content=Strings.ACTIVE_CHARACTER_NOT_FOUND, view=None
                )
                return
            embed = self._builder(char)
        finally:
            db.close()
        await interaction.response.edit_message(embed=embed, view=self.view)


class CharacterSheetView(discord.ui.View):
    """Interactive character sheet with button-based page navigation.

    All four page buttons fit on a single row. The view re-fetches the
    character from the database on every button press so changes (e.g. HP)
    are always current.
    """

    def __init__(self, owner_id: int, char_id: int) -> None:
        super().__init__(timeout=300)
        self._owner_id = owner_id
        self._char_id = char_id
        self.message: discord.Message | None = None

        for emoji, label, builder in _SHEET_PAGES:
            self.add_item(
                _CharacterSheetPageButton(
                    emoji=emoji, label=label, builder=builder, char_id=char_id
                )
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restrict button interactions to the user who opened the sheet."""
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                Strings.CHAR_SHEET_NOT_YOUR_SHEET, ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        """Disable all buttons when the view times out."""
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def register_character_commands(bot: commands.Bot) -> None:
    """Register the /character command group."""
    character_group = app_commands.Group(
        name="character", description="Manage your D&D characters"
    )

    # ------------------------------------------------------------------
    # /character create
    # ------------------------------------------------------------------

    @character_group.command(
        name="create", description="Create a new D&D character for this server"
    )
    @app_commands.describe(
        name="The name of your character",
        character_class="Your character's starting class",
        level="Starting level in that class (1-20)",
    )
    @app_commands.choices(
        character_class=[
            app_commands.Choice(name=cls.value, value=cls.value)
            for cls in CharacterClass
        ]
    )
    async def character_create(
        interaction: discord.Interaction, name: str, character_class: str, level: int
    ) -> None:
        logger.debug(
            f"Command /character create called by {interaction.user} (ID: {interaction.user.id}) "
            f"in guild {interaction.guild_id} with name: {name}, class: {character_class}, level: {level}"
        )
        db = SessionLocal()

        if len(name) > 100:
            await interaction.response.send_message(
                Strings.CHAR_CREATE_NAME_LIMIT, ephemeral=True
            )
            return
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            if not user:
                user = User(discord_id=str(interaction.user.id))
                db.add(user)
                db.flush()

            server = (
                db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            )
            if not server:
                server = Server(
                    discord_id=str(interaction.guild_id), name=interaction.guild.name
                )
                db.add(server)
                db.flush()

            char_count = db.query(Character).filter_by(user_id=user.id).count()
            if char_count >= MAX_CHARACTERS_PER_USER:
                await interaction.response.send_message(
                    Strings.ERROR_LIMIT_CHARACTERS.format(
                        limit=MAX_CHARACTERS_PER_USER
                    ),
                    ephemeral=True,
                )
                return

            existing_char = (
                db.query(Character)
                .filter_by(user=user, server=server, name=name)
                .first()
            )
            if existing_char:
                await interaction.response.send_message(
                    Strings.CHAR_EXISTS.format(name=name), ephemeral=True
                )
                return
            if level < 1 or level > 20:
                await interaction.response.send_message(
                    Strings.CHAR_LEVEL_LIMIT, ephemeral=True
                )
                return

            db.query(Character).filter_by(user=user, server=server).update(
                {"is_active": False}
            )

            new_char = Character(name=name, user=user, server=server, is_active=True)
            db.add(new_char)
            db.flush()

            cls_enum = CharacterClass(character_class)
            db.add(
                ClassLevel(
                    character_id=new_char.id, class_name=cls_enum.value, level=level
                )
            )
            db.flush()
            db.refresh(new_char)

            apply_class_save_profs(new_char, cls_enum)
            db.commit()
            logger.info(
                f"/character create completed for user {interaction.user.id}: "
                f"created '{name}' as level {level} {character_class}"
            )
            await interaction.response.send_message(
                Strings.CHAR_CREATED_ACTIVE.format(
                    name=name, level=level, char_class=character_class
                )
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character stats
    # ------------------------------------------------------------------

    @character_group.command(
        name="stats", description="Set your character's core ability scores"
    )
    @app_commands.describe(
        strength="Strength score (1-30)",
        dexterity="Dexterity score (1-30)",
        constitution="Constitution score (1-30)",
        intelligence="Intelligence score (1-30)",
        wisdom="Wisdom score (1-30)",
        charisma="Charisma score (1-30)",
        initiative_bonus="Initiative bonus (optional, defaults to Dex mod)",
    )
    async def character_stats(
        interaction: discord.Interaction,
        strength: Optional[int] = None,
        dexterity: Optional[int] = None,
        constitution: Optional[int] = None,
        intelligence: Optional[int] = None,
        wisdom: Optional[int] = None,
        charisma: Optional[int] = None,
        initiative_bonus: Optional[int] = None,
    ) -> None:
        logger.debug(
            f"Command /character stats called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            is_first_time = any(
                getattr(char, s) is None
                for s in [
                    "strength",
                    "dexterity",
                    "constitution",
                    "intelligence",
                    "wisdom",
                    "charisma",
                ]
            )

            if is_first_time:
                if any(
                    s is None
                    for s in [
                        strength,
                        dexterity,
                        constitution,
                        intelligence,
                        wisdom,
                        charisma,
                    ]
                ):
                    await interaction.response.send_message(
                        Strings.CHAR_STATS_FIRST_TIME, ephemeral=True
                    )
                    return

            stats_to_update = {
                "strength": strength,
                "dexterity": dexterity,
                "constitution": constitution,
                "intelligence": intelligence,
                "wisdom": wisdom,
                "charisma": charisma,
            }

            for stat_name, value in stats_to_update.items():
                if value is not None:
                    if not (1 <= value <= 30):
                        await interaction.response.send_message(
                            Strings.CHAR_STAT_LIMIT.format(stat_name=stat_name.title()),
                            ephemeral=True,
                        )
                        return
                    setattr(char, stat_name, value)

            if initiative_bonus is not None:
                char.initiative_bonus = initiative_bonus

            if constitution is not None and char.class_levels:
                new_max = calculate_max_hp(char)
                if new_max != -1:
                    char.max_hp = new_max
                    char.current_hp = new_max

            db.commit()
            logger.info(
                f"/character stats completed for user {interaction.user.id}: "
                f"updated stats for '{char.name}'"
            )
            await interaction.response.send_message(
                Strings.CHAR_STATS_UPDATED.format(char_name=char.name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character saves
    # ------------------------------------------------------------------

    @character_group.command(
        name="saves", description="Set your character's saving throw proficiencies"
    )
    @app_commands.describe(
        strength="Proficient in Strength saving throws?",
        dexterity="Proficient in Dexterity saving throws?",
        constitution="Proficient in Constitution saving throws?",
        intelligence="Proficient in Intelligence saving throws?",
        wisdom="Proficient in Wisdom saving throws?",
        charisma="Proficient in Charisma saving throws?",
    )
    async def character_saves(
        interaction: discord.Interaction,
        strength: bool = False,
        dexterity: bool = False,
        constitution: bool = False,
        intelligence: bool = False,
        wisdom: bool = False,
        charisma: bool = False,
    ) -> None:
        logger.debug(
            f"Command /character saves called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            char.st_prof_strength = strength
            char.st_prof_dexterity = dexterity
            char.st_prof_constitution = constitution
            char.st_prof_intelligence = intelligence
            char.st_prof_wisdom = wisdom
            char.st_prof_charisma = charisma

            db.commit()
            logger.info(
                f"/character saves completed for user {interaction.user.id}: "
                f"updated saves for '{char.name}'"
            )
            await interaction.response.send_message(
                Strings.CHAR_SAVES_UPDATED.format(char_name=char.name)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character skill
    # ------------------------------------------------------------------

    @character_group.command(
        name="skill", description="Set proficiency status for a skill"
    )
    @app_commands.describe(skill="The skill to set", status="Proficiency status")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Not Proficient", value="not_proficient"),
            app_commands.Choice(name="Proficient", value="proficient"),
            app_commands.Choice(name="Expertise", value="expertise"),
            app_commands.Choice(name="Jack of All Trades", value="jack_of_all_trades"),
        ]
    )
    async def character_skill(
        interaction: discord.Interaction, skill: str, status: str
    ) -> None:
        logger.debug(
            f"Command /character skill called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with skill: {skill}, status: {status}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            matched_skill = next(
                (s for s in SKILL_TO_STAT.keys() if s.lower() == skill.lower()), None
            )
            if not matched_skill:
                logger.warning(
                    f"User {interaction.user.id} sent unknown skill: '{skill}'"
                )
                await interaction.response.send_message(
                    Strings.CHAR_SKILL_UNKNOWN.format(skill=skill), ephemeral=True
                )
                return

            prof_enum = SkillProficiencyStatus(status)
            char_skill = (
                db.query(CharacterSkill)
                .filter_by(character_id=char.id, skill_name=matched_skill)
                .first()
            )

            if not char_skill:
                char_skill = CharacterSkill(
                    character_id=char.id,
                    skill_name=matched_skill,
                    proficiency=prof_enum,
                )
                db.add(char_skill)
            else:
                char_skill.proficiency = prof_enum

            db.commit()
            logger.info(
                f"/character skill completed for user {interaction.user.id}: "
                f"'{char.name}' {matched_skill} -> {prof_enum.name}"
            )
            await interaction.response.send_message(
                Strings.CHAR_SKILL_UPDATED.format(
                    skill=matched_skill,
                    char_name=char.name,
                    status=prof_enum.name.replace("_", " ").title(),
                )
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character ac
    # ------------------------------------------------------------------

    @character_group.command(
        name="ac", description="Set your active character's Armor Class"
    )
    @app_commands.describe(ac="Armor Class value (1-30)")
    async def character_ac(interaction: discord.Interaction, ac: int) -> None:
        logger.debug(
            f"Command /character ac called by {interaction.user} (ID: {interaction.user.id}) "
            f"with ac: {ac}"
        )
        if not (1 <= ac <= 30):
            await interaction.response.send_message(
                Strings.CHAR_AC_LIMIT, ephemeral=True
            )
            return
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            char.ac = ac
            db.commit()
            logger.info(
                f"/character ac completed for user {interaction.user.id}: "
                f"'{char.name}' AC set to {ac}"
            )
            await interaction.response.send_message(
                Strings.CHAR_AC_UPDATED.format(char_name=char.name, ac=ac)
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character view
    # ------------------------------------------------------------------

    @character_group.command(
        name="view",
        description="View a character sheet (defaults to your active character)",
    )
    @app_commands.describe(
        name="Character name — your characters or anyone in your active party (leave blank for your active character)"
    )
    async def character_view(
        interaction: discord.Interaction, name: Optional[str] = None
    ) -> None:
        """Display a paginated character sheet.

        With no argument, shows the invoking user's active character.  When a
        name is supplied the lookup checks the user's own characters first,
        then falls back to characters in their active party.
        """
        logger.debug(
            f"Command /character view called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
            + (f" — requested name: '{name}'" if name else "")
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if name is None:
                char = get_active_character(db, user, server)
                if not char:
                    await interaction.response.send_message(
                        Strings.ACTIVE_CHARACTER_NOT_FOUND
                        + " Use `/character create` or `/character switch`.",
                        ephemeral=True,
                    )
                    return
            else:
                # Own characters first
                char = (
                    db.query(Character)
                    .filter_by(user=user, server=server, name=name)
                    .first()
                )
                # Fall back to active party characters
                if not char:
                    party = get_active_party(db, user, server)
                    if party:
                        char = next(
                            (c for c in party.characters if c.name == name), None
                        )
                if not char:
                    await interaction.response.send_message(
                        Strings.CHAR_VIEW_NOT_FOUND.format(name=name), ephemeral=True
                    )
                    return

            logger.debug(f"Character lookup resolved to '{char.name}'")
            embed = _build_sheet_page0(char)
            char_id = char.id
            view = CharacterSheetView(owner_id=interaction.user.id, char_id=char_id)
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()

            logger.info(
                f"/character view completed for user {interaction.user.id}: viewed '{char.name}'"
            )
        finally:
            db.close()

    @character_view.autocomplete("name")
    async def character_view_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Suggest own characters first, then active party members' characters."""
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            if not user or not server:
                return []

            seen_names: set[str] = set()
            choices: list[app_commands.Choice[str]] = []

            own_chars = db.query(Character).filter_by(user=user, server=server).all()
            for character in own_chars:
                if current.lower() in character.name.lower():
                    choices.append(
                        app_commands.Choice(name=character.name, value=character.name)
                    )
                    seen_names.add(character.name)

            party = get_active_party(db, user, server)
            if party:
                for character in party.characters:
                    if (
                        character.name not in seen_names
                        and current.lower() in character.name.lower()
                    ):
                        choices.append(
                            app_commands.Choice(
                                name=f"{character.name} (party)",
                                value=character.name,
                            )
                        )
                        seen_names.add(character.name)

            return choices[:25]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character list
    # ------------------------------------------------------------------

    @character_group.command(
        name="list", description="View all of your characters in this server"
    )
    async def character_list(interaction: discord.Interaction) -> None:
        logger.debug(
            f"Command /character list called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if not user or not server:
                await interaction.response.send_message(
                    Strings.CHAR_LIST_NONE, ephemeral=True
                )
                return

            chars = db.query(Character).filter_by(user=user, server=server).all()
            logger.debug(
                f"Character list for user {interaction.user.id}: found {len(chars)} character(s)"
            )
            if not chars:
                await interaction.response.send_message(
                    Strings.CHAR_LIST_NONE, ephemeral=True
                )
                return

            embed = discord.Embed(
                title=Strings.CHAR_LIST_TITLE.format(
                    user_name=interaction.user.display_name
                ),
                description=Strings.CHAR_LIST_DESC.format(
                    server_name=interaction.guild.name
                ),
                color=discord.Color.blue(),
            )

            for char in chars:
                status = " (Active)" if char.is_active else ""
                sorted_cls = sorted(char.class_levels, key=lambda cl: cl.id)
                if sorted_cls:
                    class_summary = " / ".join(
                        f"{cl.class_name} {cl.level}" for cl in sorted_cls
                    )
                else:
                    class_summary = "No class"
                embed.add_field(
                    name=f"{char.name}{status}",
                    value=f"Level {char.level} — {class_summary}",
                    inline=True,
                )

            await interaction.response.send_message(embed=embed)
            logger.info(
                f"/character list completed for user {interaction.user.id}: "
                f"listed {len(chars)} character(s)"
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character switch
    # ------------------------------------------------------------------

    @character_group.command(
        name="switch", description="Switch your active character in this server"
    )
    @app_commands.describe(name="The name of the character to switch to")
    async def character_switch(interaction: discord.Interaction, name: str) -> None:
        logger.debug(
            f"Command /character switch called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            char = (
                db.query(Character)
                .filter_by(user=user, server=server, name=name)
                .first()
            )
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )
            if not char:
                await interaction.response.send_message(
                    Strings.CHAR_NOT_FOUND_NAME.format(name=name), ephemeral=True
                )
                return

            db.query(Character).filter_by(user=user, server=server).update(
                {"is_active": False}
            )
            char.is_active = True
            db.commit()
            logger.info(
                f"/character switch completed for user {interaction.user.id}: switched to '{name}'"
            )
            await interaction.response.send_message(
                Strings.CHAR_SWITCH_SUCCESS.format(name=name)
            )
        finally:
            db.close()

    @character_switch.autocomplete("name")
    async def character_switch_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Suggest character names owned by this user on this server."""
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            if not user or not server:
                return []

            chars = db.query(Character).filter_by(user=user, server=server).all()
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars
                if current.lower() in c.name.lower()
            ][:25]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character delete
    # ------------------------------------------------------------------

    @character_group.command(
        name="delete", description="Permanently delete one of your characters"
    )
    @app_commands.describe(name="The name of the character to delete")
    async def character_delete(interaction: discord.Interaction, name: str) -> None:
        logger.debug(
            f"Command /character delete called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {name}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if not user or not server:
                await interaction.response.send_message(
                    Strings.CHAR_LIST_NONE, ephemeral=True
                )
                return

            char = (
                db.query(Character)
                .filter_by(user=user, server=server, name=name)
                .first()
            )
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )
            if not char:
                await interaction.response.send_message(
                    Strings.CHAR_NOT_FOUND_NAME.format(name=name), ephemeral=True
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
                confirm_msg = Strings.CHAR_DELETE_ENCOUNTER_CONFIRM.format(
                    name=char.name, encounter_name=active_turn.encounter.name
                )
            else:
                confirm_msg = Strings.CHAR_DELETE_CONFIRM.format(name=char.name)

            view = _ConfirmCharacterDeleteView(char_id=char.id, char_name=char.name)
            logger.debug(
                f"/character delete showing confirmation for user {interaction.user.id}: '{name}'"
            )
            await interaction.response.send_message(
                confirm_msg, view=view, ephemeral=True
            )
        finally:
            db.close()

    @character_delete.autocomplete("name")
    async def character_delete_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            if not user or not server:
                return []

            chars = db.query(Character).filter_by(user=user, server=server).all()
            return [
                app_commands.Choice(name=c.name, value=c.name)
                for c in chars
                if current.lower() in c.name.lower()
            ]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character class_add
    # ------------------------------------------------------------------

    @character_group.command(
        name="class_add",
        description="Add or update a class level on your active character",
    )
    @app_commands.describe(
        character_class="The class to add or update",
        level="Number of levels in this class",
    )
    @app_commands.choices(
        character_class=[
            app_commands.Choice(name=cls.value, value=cls.value)
            for cls in CharacterClass
        ]
    )
    async def character_class_add(
        interaction: discord.Interaction, character_class: str, level: int
    ) -> None:
        logger.debug(
            f"Command /character class_add called by {interaction.user} (ID: {interaction.user.id}) "
            f"with class: {character_class}, level: {level}"
        )
        if level < 1 or level > 20:
            await interaction.response.send_message(
                Strings.CHAR_LEVEL_LIMIT, ephemeral=True
            )
            return
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            cls_enum = CharacterClass(character_class)
            existing_cl = (
                db.query(ClassLevel)
                .filter_by(character_id=char.id, class_name=cls_enum.value)
                .first()
            )

            other_levels = sum(
                cl.level for cl in char.class_levels if cl.class_name != cls_enum.value
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
                db.add(
                    ClassLevel(
                        character_id=char.id, class_name=cls_enum.value, level=level
                    )
                )
                msg = Strings.CHAR_CLASS_ADDED

            db.flush()
            db.refresh(char)

            if is_first_class:
                apply_class_save_profs(char, cls_enum)

            new_max = calculate_max_hp(char)
            if new_max != -1:
                char.max_hp = new_max
                char.current_hp = new_max

            db.commit()
            db.refresh(char)
            total = char.level
            logger.info(
                f"/character class_add completed for user {interaction.user.id}: "
                f"'{char.name}' {character_class} level {level} (total {total})"
            )
            await interaction.response.send_message(
                msg.format(
                    char_name=char.name,
                    char_class=character_class,
                    level=level,
                    total_level=total,
                )
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # /character class_remove
    # ------------------------------------------------------------------

    @character_group.command(
        name="class_remove", description="Remove a class from your active character"
    )
    @app_commands.describe(character_class="The class to remove")
    @app_commands.choices(
        character_class=[
            app_commands.Choice(name=cls.value, value=cls.value)
            for cls in CharacterClass
        ]
    )
    async def character_class_remove(
        interaction: discord.Interaction, character_class: str
    ) -> None:
        logger.debug(
            f"Command /character class_remove called by {interaction.user} (ID: {interaction.user.id}) "
            f"with class: {character_class}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            cls_enum = CharacterClass(character_class)
            cl = (
                db.query(ClassLevel)
                .filter_by(character_id=char.id, class_name=cls_enum.value)
                .first()
            )
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
                f"/character class_remove completed for user {interaction.user.id}: "
                f"removed {character_class} from '{char.name}' (total level now {total})"
            )
            await interaction.response.send_message(
                Strings.CHAR_CLASS_REMOVED.format(
                    char_name=char.name, char_class=character_class, total_level=total
                )
            )
        finally:
            db.close()

    bot.tree.add_command(character_group)
