"""Character creation wizard for ORC bot.

Implements a multi-step guided flow that walks the user through:
  Name → Class & Level → Ability Scores → AC → Saving Throws → Skills
       → HP → Weapons → Complete

Each step can be skipped or finished early.  A "Back" button on every
step (except the intro) lets the user return to the previous step.  A
"Finish" button commits the character immediately with whatever data has
been entered so far.

Class & Level supports multiclassing: up to 5 classes, total level ≤ 20.
The Weapons step queues weapons from the SRD; they are saved alongside the
character when the wizard finishes.

Also provides the manual-setup modal (a single three-field form) and
the ``start_character_creation`` entry point called by /character create.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import discord

from database import SessionLocal
from enums.character_class import CharacterClass
from enums.ruleset_edition import RulesetEdition
from enums.skill_proficiency_status import SkillProficiencyStatus
from models import Attack, Character, CharacterSkill, ClassLevel
from utils.class_data import (
    apply_class_save_profs,
    calculate_max_hp,
    get_class_save_profs,
)
from utils.constants import SKILL_TO_STAT
from utils.db_helpers import get_or_create_user_server
from utils.limits import MAX_ATTACKS_PER_CHARACTER, MAX_CHARACTERS_PER_USER
from utils.logging_config import get_logger
from utils.strings import Strings
from utils.weapon_utils import (
    calculate_weapon_hit_modifier,
    fetch_weapons,
    parse_weapon_fields,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ALL_STATS: list[str] = [
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
]

_STAT_DISPLAY: dict[str, str] = {
    "strength": "STR",
    "dexterity": "DEX",
    "constitution": "CON",
    "intelligence": "INT",
    "wisdom": "WIS",
    "charisma": "CHA",
}

_SKILLS: list[str] = list(SKILL_TO_STAT.keys())

_TOTAL_STEPS = 8
_STEP_NAMES: dict[int, str] = {
    1: "Name",
    2: "Class & Level",
    3: "Ability Scores",
    4: "Armor Class",
    5: "Saving Throws",
    6: "Skills",
    7: "HP",
    8: "Weapons",
}

# Maximum number of classes a single character can have in the wizard.
_MAX_CLASSES = 5

# Wizard timeout in seconds (10 minutes)
_WIZARD_TIMEOUT = 600


# ---------------------------------------------------------------------------
# Wizard state
# ---------------------------------------------------------------------------


@dataclass
class WizardState:
    """All data collected across the character creation wizard steps.

    ``classes_and_levels`` stores (CharacterClass, level) pairs to support
    multiclassing.  Convenience properties ``character_class``, ``level``,
    and ``total_level`` provide quick access to common values.

    ``weapons_to_add`` holds raw Open5e weapon dicts queued in the Weapons
    step.  They are committed to the database when the wizard finishes.
    """

    user_discord_id: str
    guild_discord_id: str
    guild_name: str
    name: str = ""
    classes_and_levels: list[tuple[CharacterClass, int]] = field(default_factory=list)
    strength: Optional[int] = None
    dexterity: Optional[int] = None
    constitution: Optional[int] = None
    intelligence: Optional[int] = None
    wisdom: Optional[int] = None
    charisma: Optional[int] = None
    initiative_bonus: Optional[int] = None
    ac: Optional[int] = None
    hp_override: Optional[int] = None
    # Saving throws: stat_name -> bool (defaults to all False; updated when
    # first class is selected or user explicitly toggles)
    saving_throws: dict[str, bool] = field(
        default_factory=lambda: {s: False for s in _ALL_STATS}
    )
    # Skills toggled to Proficient in the Skills step
    skills: dict[str, bool] = field(default_factory=dict)
    # True when the user explicitly configured saves (not just relied on class defaults)
    saves_explicitly_set: bool = False
    # Steps where the user pressed the primary action (not just Skip)
    steps_visited: set[str] = field(default_factory=set)
    # Raw Open5e weapon dicts queued for creation when the wizard finishes
    weapons_to_add: list[dict] = field(default_factory=list)

    @property
    def character_class(self) -> Optional[CharacterClass]:
        """Return the first class in ``classes_and_levels``, or ``None``."""
        return self.classes_and_levels[0][0] if self.classes_and_levels else None

    @property
    def level(self) -> Optional[int]:
        """Return the level of the first class, or ``None``."""
        return self.classes_and_levels[0][1] if self.classes_and_levels else None

    @property
    def total_level(self) -> int:
        """Return the sum of all class levels."""
        return sum(lv for _, lv in self.classes_and_levels)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _add_attack_from_weapon_data(
    weapon_data: dict,
    character: Character,
    db,
) -> None:
    """Create an Attack record on *character* from a raw Open5e weapon dict.

    Calculates the to-hit modifier using the character's current stats.
    The caller is responsible for calling ``db.flush()`` / ``db.commit()``.
    """
    # Extract all weapon fields from the API dict in one call
    fields = parse_weapon_fields(weapon_data)
    hit_modifier_result = calculate_weapon_hit_modifier(
        character, fields.properties, fields.range_normal_float
    )
    db.add(
        Attack(
            character_id=character.id,
            name=fields.name,
            hit_modifier=hit_modifier_result.total,
            damage_formula=fields.damage_dice,
            damage_type=fields.damage_type_name,
            weapon_category=fields.weapon_category,
            two_handed_damage=fields.two_handed_damage,
            properties_json=fields.properties_json,
            is_imported=True,
        )
    )


# ---------------------------------------------------------------------------
# DB commit helper
# ---------------------------------------------------------------------------


def save_character_from_wizard(
    state: WizardState,
    interaction: discord.Interaction,
    db,
) -> tuple[Optional[Character], Optional[str]]:
    """Validate and persist a character from *state*.

    Creates all ClassLevel records for every entry in
    ``state.classes_and_levels``.  Save proficiencies from the first class
    are applied automatically (subsequent classes do not grant additional
    saving throw proficiencies per 5e 2024 rules).

    If ``state.hp_override`` is set it takes precedence over the
    auto-calculated value.

    Any weapons queued in ``state.weapons_to_add`` are created as Attack
    records, up to ``MAX_ATTACKS_PER_CHARACTER``.

    Returns ``(character, None)`` on success or ``(None, error_message)``
    on validation failure.  The caller is responsible for calling
    ``db.commit()`` after a successful return.
    """
    if len(state.name) > 100:
        return None, Strings.CHAR_CREATE_NAME_LIMIT

    user, server = get_or_create_user_server(db, interaction)

    char_count = (
        db.query(Character).filter_by(user_id=user.id, server_id=server.id).count()
    )
    if char_count >= MAX_CHARACTERS_PER_USER:
        return None, Strings.ERROR_LIMIT_CHARACTERS.format(limit=MAX_CHARACTERS_PER_USER)

    existing = (
        db.query(Character).filter_by(user=user, server=server, name=state.name).first()
    )
    if existing:
        return None, Strings.CHAR_EXISTS.format(name=state.name)

    # Deactivate all current characters for this user in this server
    db.query(Character).filter_by(user=user, server=server).update({"is_active": False})

    char = Character(name=state.name, user=user, server=server, is_active=True)
    db.add(char)
    db.flush()

    # Class & Level — first class gets save proficiencies applied
    for index, (class_enum, class_level) in enumerate(state.classes_and_levels):
        db.add(
            ClassLevel(
                character_id=char.id,
                class_name=class_enum.value,
                level=class_level,
            )
        )
        if index == 0:
            # Flush so that char.class_levels is populated for HP calc
            db.flush()
            db.refresh(char)
            apply_class_save_profs(char, class_enum)

    if state.classes_and_levels:
        db.flush()
        db.refresh(char)

    # Ability scores
    for stat in _ALL_STATS:
        value = getattr(state, stat)
        if value is not None:
            setattr(char, stat, value)
    if state.initiative_bonus is not None:
        char.initiative_bonus = state.initiative_bonus

    # HP — manual override takes precedence over auto-calculation
    if state.hp_override is not None:
        char.max_hp = state.hp_override
        char.current_hp = state.hp_override
    else:
        new_max = calculate_max_hp(char)
        if new_max != -1:
            char.max_hp = new_max
            char.current_hp = new_max

    # AC
    if state.ac is not None:
        char.ac = state.ac

    # Saving throws — explicit user configuration overrides class defaults
    if state.saves_explicitly_set:
        for stat in _ALL_STATS:
            setattr(char, f"st_prof_{stat}", state.saving_throws.get(stat, False))

    # Skill proficiencies — only store proficient entries
    for skill_name, is_proficient in state.skills.items():
        if is_proficient:
            db.add(
                CharacterSkill(
                    character_id=char.id,
                    skill_name=skill_name,
                    proficiency=SkillProficiencyStatus.PROFICIENT,
                )
            )

    # Weapons queued during the Weapons step
    weapon_count = 0
    for weapon_data in state.weapons_to_add:
        if weapon_count >= MAX_ATTACKS_PER_CHARACTER:
            break
        _add_attack_from_weapon_data(weapon_data, char, db)
        weapon_count += 1

    db.flush()
    return char, None


# ---------------------------------------------------------------------------
# Shared finish helper
# ---------------------------------------------------------------------------


async def _finish_wizard(
    state: WizardState,
    interaction: discord.Interaction,
) -> None:
    """Commit the wizard to the DB and display the completion embed."""
    db = SessionLocal()
    try:
        char, error = save_character_from_wizard(state, interaction, db)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        db.commit()
        logger.info(
            f"Wizard completed: created '{char.name}' for user "
            f"{interaction.user.id} in guild {interaction.guild_id}"
        )
        embed = _build_complete_embed(state, char)
        await interaction.response.edit_message(embed=embed, view=None)
    except Exception as exc:
        db.rollback()
        logger.error(
            f"Error committing character wizard for user {interaction.user.id}: {exc}",
            exc_info=True,
        )
        await interaction.response.send_message(Strings.ERROR_GENERIC, ephemeral=False)
    finally:
        db.close()


def _add_wizard_embed_field(
    embed: discord.Embed,
    label: str,
    value: Optional[str],
    skipped_command: str,
    inline: bool = False,
) -> None:
    """Add a field to the completion embed.

    When *value* is provided shows it under a 'Set' heading; when ``None``
    shows a 'Skipped' heading with the command to use later.
    """
    if value is not None:
        embed.add_field(
            name=Strings.WIZARD_COMPLETE_SET.format(label=label),
            value=value,
            inline=inline,
        )
    else:
        embed.add_field(
            name=Strings.WIZARD_COMPLETE_SKIPPED.format(
                label=label, command=skipped_command
            ),
            value="\u200b",
            inline=inline,
        )


def _build_complete_embed(state: WizardState, char: Character) -> discord.Embed:
    """Build the wizard completion embed summarising what was and wasn't set."""
    embed = discord.Embed(
        title=Strings.WIZARD_COMPLETE_TITLE.format(name=state.name),
        description=Strings.WIZARD_COMPLETE_DESC,
        color=discord.Color.green(),
    )

    # Class & Level (multiclass-aware display)
    if state.classes_and_levels:
        class_value = "\n".join(
            f"{cls.value} {lv}" for cls, lv in state.classes_and_levels
        )
    else:
        class_value = None
    _add_wizard_embed_field(
        embed, "Class & Level", class_value, "/character class_add", inline=True
    )

    # Ability Scores — show all set stats in a single inline block
    stats_set = [s for s in _ALL_STATS if getattr(state, s) is not None]
    if stats_set:
        stat_value = "  ".join(
            f"**{_STAT_DISPLAY[s]}** {getattr(state, s)}"
            for s in _ALL_STATS
            if getattr(state, s) is not None
        )
    else:
        stat_value = None
    _add_wizard_embed_field(embed, "Ability Scores", stat_value, "/character stats")

    # AC
    ac_value = str(state.ac) if state.ac is not None else None
    _add_wizard_embed_field(embed, "AC", ac_value, "/character ac", inline=True)

    # HP — distinguish manual override from auto-calculated
    if char.max_hp != -1:
        hp_label = (
            Strings.WIZARD_COMPLETE_HP_OVERRIDE
            if state.hp_override is not None
            else Strings.WIZARD_COMPLETE_HP_AUTO
        )
        hp_value = f"{char.max_hp} ({hp_label})"
    else:
        hp_value = None
    _add_wizard_embed_field(embed, "Max HP", hp_value, "/hp set_max", inline=True)

    # Saving Throws — shown when class was set or user explicitly toggled saves
    if state.saves_explicitly_set or state.character_class is not None:
        prof_saves = [
            _STAT_DISPLAY[s]
            for s in _ALL_STATS
            if state.saving_throws.get(s, False)
        ]
        saves_value = ", ".join(prof_saves) if prof_saves else "None"
    else:
        saves_value = None
    _add_wizard_embed_field(embed, "Saving Throws", saves_value, "/character saves")

    # Skills — list proficient ones, or mark skipped
    proficient_skills = [sk for sk, val in state.skills.items() if val]
    skills_value = ", ".join(proficient_skills) if proficient_skills else None
    _add_wizard_embed_field(embed, "Skills", skills_value, "/character skill")

    # Weapons — list queued weapon names, or mark skipped
    if state.weapons_to_add:
        weapons_value = ", ".join(
            w.get("name", "Unknown") for w in state.weapons_to_add
        )
    else:
        weapons_value = None
    _add_wizard_embed_field(embed, "Weapons", weapons_value, "/weapon search")

    embed.set_footer(text=Strings.WIZARD_COMPLETE_FOOTER)

    # Tip: remind users to set HP when auto-calc wasn't possible
    if char.max_hp == -1:
        embed.description = (
            f"{Strings.WIZARD_COMPLETE_DESC}\n\n{Strings.WIZARD_COMPLETE_TIP_HP}"
        )

    return embed


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------


class _CharacterNameModal(discord.ui.Modal):
    """First wizard step: collect the character's name."""

    name_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_NAME_LABEL,
        placeholder=Strings.WIZARD_NAME_PLACEHOLDER,
        max_length=100,
        required=True,
    )

    def __init__(self, state: WizardState) -> None:
        super().__init__(title=Strings.WIZARD_NAME_MODAL_TITLE)
        self.state = state

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Save name and advance to the Class & Level step."""
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                Strings.WIZARD_NAME_REQUIRED, ephemeral=True
            )
            return
        self.state.name = name
        view = _ClassLevelView(self.state, step_number=2)
        await interaction.response.edit_message(
            embed=view._build_embed(), view=view
        )


class _LevelForClassModal(discord.ui.Modal):
    """Collect or update the level for a specific class in the wizard."""

    def __init__(
        self,
        state: WizardState,
        class_enum: CharacterClass,
        existing_index: Optional[int],
        parent_view: "_ClassLevelView",
    ) -> None:
        super().__init__(
            title=Strings.WIZARD_LEVEL_FOR_CLASS_TITLE.format(
                class_name=class_enum.value
            )
        )
        self.state = state
        self.class_enum = class_enum
        self.existing_index = existing_index
        self.parent_view = parent_view

        # Pre-fill with existing level when re-editing
        existing_level = (
            str(state.classes_and_levels[existing_index][1])
            if existing_index is not None
            else ""
        )
        self.level_input = discord.ui.TextInput(
            label=Strings.WIZARD_LEVEL_LABEL,
            placeholder=Strings.WIZARD_LEVEL_PLACEHOLDER,
            max_length=2,
            required=True,
            default=existing_level if existing_level else discord.utils.MISSING,
        )
        self.add_item(self.level_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate level, enforce total-level cap, and update state."""
        raw = self.level_input.value.strip()
        try:
            level = int(raw)
        except ValueError:
            await interaction.response.send_message(
                Strings.WIZARD_LEVEL_INVALID, ephemeral=True
            )
            return
        if not 1 <= level <= 20:
            await interaction.response.send_message(
                Strings.CHAR_LEVEL_LIMIT, ephemeral=True
            )
            return

        # Calculate what the new total would be
        current_total = self.state.total_level
        if self.existing_index is not None:
            # Editing: subtract the old level before adding the new one
            current_total -= self.state.classes_and_levels[self.existing_index][1]
        new_total = current_total + level
        if new_total > 20:
            await interaction.response.send_message(
                Strings.WIZARD_TOTAL_LEVEL_EXCEEDED.format(
                    added=level,
                    class_name=self.class_enum.value,
                    new_total=new_total,
                ),
                ephemeral=True,
            )
            return

        is_first_class = (
            self.existing_index is None and len(self.state.classes_and_levels) == 0
        )

        if self.existing_index is not None:
            self.state.classes_and_levels[self.existing_index] = (
                self.class_enum,
                level,
            )
        else:
            self.state.classes_and_levels.append((self.class_enum, level))

        # Auto-apply save proficiencies when the first class is first added
        if is_first_class and not self.state.saves_explicitly_set:
            class_profs = get_class_save_profs(self.class_enum)
            self.state.saving_throws = {s: s in class_profs for s in _ALL_STATS}

        self.state.steps_visited.add("class")
        await self.parent_view._refresh(interaction)


class _PhysicalStatsModal(discord.ui.Modal):
    """Collect the four physical/mental ability scores (STR/DEX/CON/INT)."""

    str_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_STR_LABEL, placeholder="e.g. 16", max_length=2, required=True
    )
    dex_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_DEX_LABEL, placeholder="e.g. 14", max_length=2, required=True
    )
    con_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_CON_LABEL, placeholder="e.g. 15", max_length=2, required=True
    )


    def __init__(self, state: WizardState, parent_view: "_StatsView") -> None:
        super().__init__(title=Strings.WIZARD_PRIMARY_STATS_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate and store STR/DEX/CON, refresh the Stats step view."""
        mapping = {
            "strength": self.str_input.value,
            "dexterity": self.dex_input.value,
            "constitution": self.con_input.value,
        }
        parsed = await _validate_stat_inputs(mapping, interaction)
        if parsed is None:
            return

        # Store all validated stats on the wizard state
        for stat, value in parsed.items():
            setattr(self.state, stat, value)

        self.state.steps_visited.add("stats_primary")
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


class _MentalStatsModal(discord.ui.Modal):
    """Collect Intelligence, Wisdom and Charisma; refreshes the Stats step."""

    wis_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_WIS_LABEL, placeholder="e.g. 12", max_length=2, required=True
    )
    cha_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_CHA_LABEL, placeholder="e.g. 8", max_length=2, required=True
    )
    int_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_INT_LABEL,
        placeholder="e.g. 10",
        max_length=2,
        required=True,
    )

    def __init__(self, state: WizardState, parent_view: "_StatsView") -> None:
        super().__init__(title=Strings.WIZARD_WIS_CHA_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate WIS and CHA, then refresh the Stats step."""
        mapping = {
            "intelligence": self.int_input.value,
            "wisdom": self.wis_input.value,
            "charisma": self.cha_input.value,
        }
        parsed = await _validate_stat_inputs(mapping, interaction)
        if parsed is None:
            return

        # Store all validated stats on the wizard state
        for stat, value in parsed.items():
            setattr(self.state, stat, value)

        self.state.steps_visited.add("stats")
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


class _InitiativeModal(discord.ui.Modal):
    """Collect an optional initiative bonus override; refreshes the Stats step."""

    init_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_INIT_LABEL,
        placeholder="e.g. +2 or -1",
        max_length=3,
        required=True,
    )

    def __init__(self, state: WizardState, parent_view: "_StatsView") -> None:
        super().__init__(title=Strings.WIZARD_INIT_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate and store the initiative override, then refresh the Stats step."""
        raw = self.init_input.value.strip().lstrip("+")
        try:
            self.state.initiative_bonus = int(raw)
        except ValueError:
            await interaction.response.send_message(
                Strings.WIZARD_STAT_NOT_NUMBER.format(stat="Initiative bonus"),
                ephemeral=True,
            )
            return
        self.state.steps_visited.add("stats")
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


class _ACModal(discord.ui.Modal):
    """Collect Armor Class; refreshes the AC step."""

    ac_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_AC_LABEL,
        placeholder=Strings.WIZARD_AC_PLACEHOLDER,
        max_length=2,
        required=True,
    )

    def __init__(self, state: WizardState, parent_view: "_ACView") -> None:
        super().__init__(title=Strings.WIZARD_AC_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate AC, then refresh the AC step."""
        raw = self.ac_input.value.strip()
        try:
            ac = int(raw)
        except ValueError:
            await interaction.response.send_message(
                Strings.WIZARD_AC_INVALID, ephemeral=True
            )
            return
        if not 1 <= ac <= 30:
            await interaction.response.send_message(
                Strings.CHAR_AC_LIMIT, ephemeral=True
            )
            return
        self.state.ac = ac
        self.state.steps_visited.add("ac")
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


class _HPModal(discord.ui.Modal):
    """Collect a manual max HP override."""

    def __init__(self, state: WizardState, parent_view: "_HPView") -> None:
        super().__init__(title=Strings.WIZARD_HP_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view
        self.hp_input = discord.ui.TextInput(
            label=Strings.WIZARD_HP_LABEL,
            placeholder=Strings.WIZARD_HP_PLACEHOLDER,
            max_length=3,
            required=True,
        )
        self.add_item(self.hp_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate HP and store the override."""
        raw = self.hp_input.value.strip()
        try:
            hp = int(raw)
        except ValueError:
            await interaction.response.send_message(
                Strings.WIZARD_HP_INVALID, ephemeral=True
            )
            return
        if not 1 <= hp <= 999:
            await interaction.response.send_message(
                Strings.WIZARD_HP_INVALID, ephemeral=True
            )
            return
        self.state.hp_override = hp
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


class _WeaponSearchModal(discord.ui.Modal):
    """Search for SRD weapons during the wizard's Weapons step.

    The response is deferred so the network request can complete within the
    15-minute followup window rather than the 3-second initial window.
    """

    def __init__(
        self, state: WizardState, weapons_view: "_WeaponsWizardView"
    ) -> None:
        super().__init__(title=Strings.WIZARD_WEAPONS_SEARCH_MODAL_TITLE)
        self.state = state
        self.weapons_view = weapons_view
        self.query_input = discord.ui.TextInput(
            label=Strings.WIZARD_WEAPONS_SEARCH_LABEL,
            placeholder=Strings.WIZARD_WEAPONS_SEARCH_PLACEHOLDER,
            max_length=50,
            required=True,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Fetch weapon results and show them for selection."""
        query = self.query_input.value.strip()
        await interaction.response.defer()
        try:
            results = await fetch_weapons(query, RulesetEdition.RULES_2024)
        except Exception as exc:
            logger.error(f"Wizard weapon search failed for {query!r}: {exc}", exc_info=True)
            await interaction.followup.send(
                Strings.WIZARD_WEAPONS_SEARCH_ERROR, ephemeral=True
            )
            return

        if not results:
            await interaction.edit_original_response(
                embed=self.weapons_view._build_embed(no_results_query=query),
                view=self.weapons_view,
            )
            return

        results_view = _WeaponResultsView(self.state, results, self.weapons_view)
        await interaction.edit_original_response(
            embed=results_view._build_embed(),
            view=results_view,
        )


class _ManualSetupModal(discord.ui.Modal):
    """Single-form manual character creation (name + optional class/level)."""

    name_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_MANUAL_NAME_LABEL,
        placeholder=Strings.WIZARD_NAME_PLACEHOLDER,
        max_length=100,
        required=True,
    )
    class_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_MANUAL_CLASS_LABEL,
        placeholder=Strings.WIZARD_MANUAL_CLASS_PLACEHOLDER,
        max_length=20,
        required=False,
    )
    level_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_MANUAL_LEVEL_LABEL,
        placeholder=Strings.WIZARD_MANUAL_LEVEL_PLACEHOLDER,
        max_length=2,
        required=False,
    )

    def __init__(
        self, user_discord_id: str, guild_discord_id: str, guild_name: str
    ) -> None:
        super().__init__(title=Strings.WIZARD_MANUAL_MODAL_TITLE)
        self.user_discord_id = user_discord_id
        self.guild_discord_id = guild_discord_id
        self.guild_name = guild_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate fields, create the character, show follow-up command list."""
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                Strings.WIZARD_NAME_REQUIRED, ephemeral=True
            )
            return

        character_class: Optional[CharacterClass] = None
        level = 1

        raw_class = self.class_input.value.strip() if self.class_input.value else ""
        if raw_class:
            try:
                character_class = CharacterClass(raw_class.title())
            except ValueError:
                valid = ", ".join(c.value for c in CharacterClass)
                await interaction.response.send_message(
                    Strings.WIZARD_CLASS_INVALID.format(
                        value=raw_class, valid_classes=valid
                    ),
                    ephemeral=True,
                )
                return

        raw_level = self.level_input.value.strip() if self.level_input.value else ""
        if raw_level:
            try:
                level = int(raw_level)
            except ValueError:
                await interaction.response.send_message(
                    Strings.WIZARD_LEVEL_INVALID, ephemeral=True
                )
                return
            if not 1 <= level <= 20:
                await interaction.response.send_message(
                    Strings.CHAR_LEVEL_LIMIT, ephemeral=True
                )
                return

        classes_and_levels = [(character_class, level)] if character_class else []
        state = WizardState(
            user_discord_id=self.user_discord_id,
            guild_discord_id=self.guild_discord_id,
            guild_name=self.guild_name,
            name=name,
            classes_and_levels=classes_and_levels,
        )
        # Auto-apply class saves so they are stored even in manual mode
        if character_class:
            class_profs = get_class_save_profs(character_class)
            state.saving_throws = {s: s in class_profs for s in _ALL_STATS}

        db = SessionLocal()
        try:
            char, error = save_character_from_wizard(state, interaction, db)
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return
            db.commit()
            logger.info(
                f"Manual setup: created '{name}' for user {interaction.user.id} "
                f"in guild {interaction.guild_id}"
            )
            await interaction.response.edit_message(
                content=Strings.WIZARD_MANUAL_SETUP_CMDS.format(name=name),
                embed=None,
                view=None,
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                f"Error in manual setup for user {interaction.user.id}: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(Strings.ERROR_GENERIC, ephemeral=True)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Shared button helpers
# ---------------------------------------------------------------------------


def _step_embed(step_number: int, description: str) -> discord.Embed:
    """Build a standard wizard step embed."""
    title = Strings.WIZARD_STEP_HEADER.format(
        step=step_number,
        total=_TOTAL_STEPS,
        step_name=_STEP_NAMES[step_number],
    )
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
    )


async def _validate_stat_inputs(
    mapping: dict[str, str],
    interaction: discord.Interaction,
) -> Optional[dict[str, int]]:
    """Parse and range-check a mapping of stat names to raw string values.

    Sends an ephemeral error and returns ``None`` on the first invalid entry.
    Returns the parsed ``{stat: int}`` dict on success.
    """
    parsed: dict[str, int] = {}
    for stat, raw in mapping.items():
        # Attempt integer conversion; reject non-numeric input
        try:
            value = int(raw.strip())
        except ValueError:
            await interaction.response.send_message(
                Strings.WIZARD_STAT_NOT_NUMBER.format(stat=stat.title()),
                ephemeral=True,
            )
            return None
        # D&D ability scores must fall within 1–30
        if not 1 <= value <= 30:
            await interaction.response.send_message(
                Strings.CHAR_STAT_LIMIT.format(stat_name=stat.title()),
                ephemeral=True,
            )
            return None
        parsed[stat] = value
    return parsed


async def _navigate_to_step(
    next_step_number: int,
    state: WizardState,
    interaction: discord.Interaction,
) -> None:
    """Edit the current message to show *next_step_number*, or finish the wizard.

    Called by Continue and Skip buttons which share identical navigation logic.
    """
    view = _view_for_step(next_step_number, state)
    if view is None:
        # Past the last step — commit and show completion
        await _finish_wizard(state, interaction)
    else:
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class _BackButton(discord.ui.Button):
    """Returns to the previous wizard step."""

    def __init__(
        self, prev_step_number: int, state: WizardState, row: int = 4
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_BUTTON_BACK,
            style=discord.ButtonStyle.secondary,
            custom_id=f"wiz_back_{prev_step_number}",
            row=row,
        )
        self.prev_step_number = prev_step_number
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Navigate back to the previous step."""
        view = _view_for_step(self.prev_step_number, self.state)
        if view is not None:
            await interaction.response.edit_message(
                embed=view._build_embed(), view=view
            )


class _ContinueButton(discord.ui.Button):
    """Advances the wizard to the next step (primary navigation action)."""

    def __init__(
        self, next_step_number: int, state: WizardState, row: int = 4
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_BUTTON_CONTINUE,
            style=discord.ButtonStyle.primary,
            custom_id=f"wiz_continue_{next_step_number}",
            row=row,
        )
        self.next_step_number = next_step_number
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Advance to the next step."""
        await _navigate_to_step(self.next_step_number, self.state, interaction)


class _SkipButton(discord.ui.Button):
    """Skips the current step entirely without entering data."""

    def __init__(
        self, next_step_number: int, state: WizardState, row: int = 4
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_BUTTON_SKIP,
            style=discord.ButtonStyle.secondary,
            custom_id=f"wiz_skip_{next_step_number}",
            row=row,
        )
        self.next_step_number = next_step_number
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Skip to the next step."""
        await _navigate_to_step(self.next_step_number, self.state, interaction)


class _FinishButton(discord.ui.Button):
    """Commits the wizard immediately with all data collected so far."""

    def __init__(self, state: WizardState, row: int = 4) -> None:
        super().__init__(
            label=Strings.WIZARD_BUTTON_FINISH,
            style=discord.ButtonStyle.success,
            custom_id="wiz_finish",
            row=row,
        )
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Commit and complete the wizard."""
        await _finish_wizard(self.state, interaction)


def _view_for_step(
    step_number: int, state: WizardState
) -> Optional[discord.ui.View]:
    """Return the view for *step_number*, or ``None`` if the wizard is complete.

    Step 1 returns the intro view so that Back buttons on Step 2 work
    consistently.
    """
    mapping = {
        1: lambda: _WizardIntroView(state),
        2: lambda: _ClassLevelView(state, step_number=2),
        3: lambda: _StatsView(state, step_number=3),
        4: lambda: _ACView(state, step_number=4),
        5: lambda: _SavesView(state, step_number=5),
        6: lambda: _SkillsView(state, step_number=6),
        7: lambda: _HPView(state, step_number=7),
        8: lambda: _WeaponsWizardView(state, step_number=8),
    }
    factory = mapping.get(step_number)
    return factory() if factory else None


# ---------------------------------------------------------------------------
# Toggle buttons for saves and skills
# ---------------------------------------------------------------------------


class _SaveToggleButton(discord.ui.Button):
    """A toggle button for a single saving throw proficiency."""

    def __init__(
        self, stat: str, is_proficient: bool, saves_view: "_SavesView"
    ) -> None:
        style = (
            discord.ButtonStyle.success if is_proficient else discord.ButtonStyle.secondary
        )
        row = 0 if stat in ("strength", "dexterity", "constitution") else 1
        super().__init__(
            label=f"{_STAT_DISPLAY[stat]} Save",
            style=style,
            custom_id=f"wiz_save_{stat}",
            row=row,
        )
        self.stat = stat
        self.saves_view = saves_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Toggle this save and refresh the view."""
        current = self.saves_view.state.saving_throws.get(self.stat, False)
        self.saves_view.state.saving_throws[self.stat] = not current
        self.saves_view.state.saves_explicitly_set = True
        await self.saves_view._refresh(interaction)


class _SkillToggleButton(discord.ui.Button):
    """A toggle button for a single skill proficiency."""

    def __init__(
        self,
        skill: str,
        is_proficient: bool,
        skills_view: "_SkillsView",
        row: int,
    ) -> None:
        style = (
            discord.ButtonStyle.success if is_proficient else discord.ButtonStyle.secondary
        )
        super().__init__(
            label=skill,
            style=style,
            custom_id=f"wiz_skill_{skill.lower().replace(' ', '_')}",
            row=row,
        )
        self.skill = skill
        self.skills_view = skills_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Toggle this skill and refresh the view."""
        current = self.skills_view.state.skills.get(self.skill, False)
        self.skills_view.state.skills[self.skill] = not current
        await self.skills_view._refresh(interaction)


# ---------------------------------------------------------------------------
# Class-level remove button (defined before _ClassLevelView)
# ---------------------------------------------------------------------------


class _ClassRemoveButton(discord.ui.Button):
    """Removes a single class from the wizard's class list."""

    def __init__(
        self,
        state: WizardState,
        class_enum: CharacterClass,
        parent_view: "_ClassLevelView",
        row: int,
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_CLASS_REMOVE_BUTTON.format(
                class_name=class_enum.value
            ),
            style=discord.ButtonStyle.danger,
            custom_id=f"wiz_remove_{class_enum.value.lower()}",
            row=row,
        )
        self.state = state
        self.class_enum = class_enum
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Remove the class and update saving throw defaults if needed."""
        was_first = (
            bool(self.state.classes_and_levels)
            and self.state.classes_and_levels[0][0] == self.class_enum
        )
        self.state.classes_and_levels = [
            (cls, lv)
            for cls, lv in self.state.classes_and_levels
            if cls != self.class_enum
        ]
        # When the first class is removed and saves were not explicitly
        # configured, update them to match the new first class (or clear).
        if was_first and not self.state.saves_explicitly_set:
            if self.state.classes_and_levels:
                new_first = self.state.classes_and_levels[0][0]
                profs = get_class_save_profs(new_first)
                self.state.saving_throws = {s: s in profs for s in _ALL_STATS}
            else:
                self.state.saving_throws = {s: False for s in _ALL_STATS}
        await self.parent_view._refresh(interaction)


# ---------------------------------------------------------------------------
# Step views
# ---------------------------------------------------------------------------


class _WizardIntroView(discord.ui.View):
    """Initial wizard view presenting the Wizard and Manual Setup options."""

    def __init__(self, state: WizardState) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state

    def _build_embed(self) -> discord.Embed:
        """Build the intro embed (used when returning to Step 1 via Back)."""
        return discord.Embed(
            title=Strings.WIZARD_INTRO_TITLE,
            description=Strings.WIZARD_INTRO_DESC,
            color=discord.Color.blurple(),
        )

    @discord.ui.button(
        label=Strings.WIZARD_BUTTON_WIZARD,
        style=discord.ButtonStyle.primary,
        custom_id="wiz_start",
    )
    async def start_wizard(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Open the name modal to begin the wizard."""
        modal = _CharacterNameModal(self.state)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label=Strings.WIZARD_BUTTON_MANUAL,
        style=discord.ButtonStyle.secondary,
        custom_id="wiz_manual",
    )
    async def manual_setup(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Open the manual-setup modal (name + optional class/level)."""
        modal = _ManualSetupModal(
            user_discord_id=self.state.user_discord_id,
            guild_discord_id=self.state.guild_discord_id,
            guild_name=self.state.guild_name,
        )
        await interaction.response.send_modal(modal)


class _ClassLevelView(discord.ui.View):
    """Step 2: Class selection with multiclass support.

    The class dropdown opens a level modal on selection.  Each added class
    shows a remove button.  Up to ``_MAX_CLASSES`` classes may be added;
    total level across all classes may not exceed 20.
    """

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number
        self._build_items()

    def _build_items(self) -> None:
        """Rebuild all buttons and selects from current state."""
        self.clear_items()

        # Row 0: class dropdown
        options = [
            discord.SelectOption(label=cls.value, value=cls.value)
            for cls in CharacterClass
        ]
        self._class_select = discord.ui.Select(
            placeholder=Strings.WIZARD_CLASS_SELECT_PLACEHOLDER,
            options=options,
            custom_id="wiz_class_select",
            row=0,
        )
        self._class_select.callback = self._on_class_selected
        self.add_item(self._class_select)

        # Row 1: one remove button per added class
        for class_enum, _ in self.state.classes_and_levels:
            self.add_item(
                _ClassRemoveButton(
                    state=self.state,
                    class_enum=class_enum,
                    parent_view=self,
                    row=1,
                )
            )

        # Row 2: navigation
        self.add_item(_BackButton(prev_step_number=1, state=self.state, row=2))
        self.add_item(_ContinueButton(next_step_number=3, state=self.state, row=2))
        self.add_item(_SkipButton(next_step_number=3, state=self.state, row=2))
        self.add_item(_FinishButton(self.state, row=2))

    async def _on_class_selected(
        self, interaction: discord.Interaction
    ) -> None:
        """Open a level modal for the selected class."""
        selected = self._class_select.values[0]
        class_enum = CharacterClass(selected)

        existing_index: Optional[int] = next(
            (
                i
                for i, (cls, _) in enumerate(self.state.classes_and_levels)
                if cls == class_enum
            ),
            None,
        )

        if (
            existing_index is None
            and len(self.state.classes_and_levels) >= _MAX_CLASSES
        ):
            await interaction.response.send_message(
                Strings.WIZARD_CLASS_MAX_REACHED.format(max=_MAX_CLASSES),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            _LevelForClassModal(
                self.state, class_enum, existing_index, self
            )
        )

    def _build_embed(self) -> discord.Embed:
        """Build the Class & Level step embed."""
        embed = _step_embed(self.step_number, Strings.WIZARD_CLASS_LEVEL_DESC)
        if self.state.classes_and_levels:
            class_lines = "\n".join(
                f"**{cls.value}** Lv {lv}"
                for cls, lv in self.state.classes_and_levels
            )
            embed.add_field(
                name=Strings.WIZARD_CLASS_TOTAL_LEVEL.format(
                    total=self.state.total_level, max=20
                ),
                value=class_lines,
                inline=False,
            )
        embed.add_field(
            name="\u200b",
            value=Strings.WIZARD_TIP_MULTICLASS,
            inline=False,
        )
        return embed

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild items and re-render the embed."""
        self._build_items()
        await interaction.response.edit_message(
            embed=self._build_embed(), view=self
        )


class _PrimaryStatsButton(discord.ui.Button):
    """Opens the primary stats modal (STR/DEX/CON)."""

    def __init__(
        self, state: WizardState, parent_view: "_StatsView", row: int
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_PHYSICAL_STATS_BUTTON,
            style=discord.ButtonStyle.primary,
            custom_id="wiz_physical_stats",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the primary stats modal."""
        await interaction.response.send_modal(
            _PhysicalStatsModal(self.state, self.parent_view)
        )


class _WisChaButton(discord.ui.Button):
    """Opens the WIS/CHA modal."""

    def __init__(
        self, state: WizardState, parent_view: "_StatsView", row: int
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_MENTAL_STATS_BUTTON,
            style=discord.ButtonStyle.primary,
            custom_id="wiz_mental_stats",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the WIS/CHA modal."""
        await interaction.response.send_modal(
            _MentalStatsModal(self.state, self.parent_view)
        )


class _InitiativeButton(discord.ui.Button):
    """Opens the Initiative override modal."""

    def __init__(
        self, state: WizardState, parent_view: "_StatsView", row: int
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_INIT_BUTTON,
            style=discord.ButtonStyle.secondary,
            custom_id="wiz_initiative",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the Initiative override modal."""
        await interaction.response.send_modal(
            _InitiativeModal(self.state, self.parent_view)
        )


class _StatsView(discord.ui.View):
    """Step 3: Ability scores entry (three modal buttons)."""

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number

        self.add_item(_PrimaryStatsButton(state, self, row=0))
        self.add_item(_WisChaButton(state, self, row=1))
        self.add_item(_InitiativeButton(state, self, row=2))
        self.add_item(_BackButton(prev_step_number=2, state=state, row=3))
        self.add_item(_ContinueButton(next_step_number=4, state=state, row=3))
        self.add_item(_SkipButton(next_step_number=4, state=state, row=3))
        self.add_item(_FinishButton(state, row=3))

    def _build_embed(self) -> discord.Embed:
        embed = _step_embed(self.step_number, Strings.WIZARD_STATS_DESC)
        set_stats = {
            s: getattr(self.state, s)
            for s in _ALL_STATS
            if getattr(self.state, s) is not None
        }
        if set_stats:
            stat_text = "  ".join(
                f"**{_STAT_DISPLAY[s]}** {v}" for s, v in set_stats.items()
            )
            embed.add_field(name="Currently set", value=stat_text, inline=False)
        return embed


class _EnterACButton(discord.ui.Button):
    """Opens the AC modal."""

    def __init__(
        self, state: WizardState, parent_view: "_ACView", row: int
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_AC_BUTTON,
            style=discord.ButtonStyle.primary,
            custom_id="wiz_enter_ac",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the AC modal."""
        await interaction.response.send_modal(
            _ACModal(self.state, self.parent_view)
        )


class _ACView(discord.ui.View):
    """Step 4: Armor Class entry (modal button)."""

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number

        self.add_item(_EnterACButton(state, self, row=0))
        self.add_item(_BackButton(prev_step_number=3, state=state, row=1))
        self.add_item(_ContinueButton(next_step_number=5, state=state, row=1))
        self.add_item(_SkipButton(next_step_number=5, state=state, row=1))
        self.add_item(_FinishButton(state, row=1))

    def _build_embed(self) -> discord.Embed:
        embed = _step_embed(self.step_number, Strings.WIZARD_AC_DESC)
        if self.state.ac is not None:
            embed.add_field(name="AC", value=str(self.state.ac), inline=True)
        return embed


class _SavesView(discord.ui.View):
    """Step 5: Six saving throw toggle buttons."""

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number
        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add save toggle buttons and navigation buttons."""
        for stat in _ALL_STATS:
            is_prof = self.state.saving_throws.get(stat, False)
            self.add_item(_SaveToggleButton(stat, is_prof, self))
        self.add_item(_BackButton(prev_step_number=4, state=self.state, row=2))
        self.add_item(_ContinueButton(next_step_number=6, state=self.state, row=2))
        self.add_item(_SkipButton(next_step_number=6, state=self.state, row=2))
        self.add_item(_FinishButton(self.state, row=2))

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild buttons and re-render the embed."""
        self.clear_items()
        self._add_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self) -> discord.Embed:
        if self.state.character_class is not None:
            desc = Strings.WIZARD_SAVES_DESC_CLASS.format(
                char_class=self.state.character_class.value
            )
        else:
            desc = Strings.WIZARD_SAVES_DESC_NO_CLASS
        return _step_embed(self.step_number, desc)


class _SkillsView(discord.ui.View):
    """Step 6: Eighteen skill toggle buttons."""

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number
        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add all 18 skill toggles across rows 0–3, navigation on row 4."""
        for index, skill in enumerate(_SKILLS):
            row = index // 5  # rows 0–3
            is_prof = self.state.skills.get(skill, False)
            self.add_item(_SkillToggleButton(skill, is_prof, self, row=row))
        self.add_item(_BackButton(prev_step_number=5, state=self.state, row=4))
        self.add_item(_ContinueButton(next_step_number=7, state=self.state, row=4))
        self.add_item(_SkipButton(next_step_number=7, state=self.state, row=4))
        self.add_item(_FinishButton(self.state, row=4))

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild buttons and re-render the embed."""
        self.clear_items()
        self._add_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self) -> discord.Embed:
        return _step_embed(self.step_number, Strings.WIZARD_SKILLS_DESC)


class _SetHPButton(discord.ui.Button):
    """Opens the HP override modal."""

    def __init__(
        self, state: WizardState, parent_view: "_HPView", row: int
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_HP_BUTTON,
            style=discord.ButtonStyle.primary,
            custom_id="wiz_set_hp",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the HP modal."""
        await interaction.response.send_modal(_HPModal(self.state, self.parent_view))


class _HPView(discord.ui.View):
    """Step 7: Optional manual HP override."""

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number

        self.add_item(_SetHPButton(state, self, row=0))
        self.add_item(_BackButton(prev_step_number=6, state=state, row=1))
        self.add_item(_ContinueButton(next_step_number=8, state=state, row=1))
        self.add_item(_SkipButton(next_step_number=8, state=state, row=1))
        self.add_item(_FinishButton(state, row=1))

    def _build_embed(self) -> discord.Embed:
        """Build the HP step embed, showing override value or auto-calc hint."""
        embed = _step_embed(self.step_number, Strings.WIZARD_HP_STEP_DESC)

        if self.state.hp_override is not None:
            embed.add_field(
                name="Max HP",
                value=Strings.WIZARD_HP_SET.format(hp=self.state.hp_override),
                inline=False,
            )
        else:
            can_auto_calc = (
                bool(self.state.classes_and_levels)
                and self.state.constitution is not None
            )
            hint = (
                Strings.WIZARD_HP_WILL_AUTO_CALC
                if can_auto_calc
                else Strings.WIZARD_HP_CANNOT_AUTO_CALC
            )
            embed.add_field(name="HP Status", value=hint, inline=False)
        return embed


class _SearchWeaponButton(discord.ui.Button):
    """Opens the weapon search modal."""

    def __init__(
        self,
        state: WizardState,
        weapons_view: "_WeaponsWizardView",
        row: int,
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_WEAPONS_SEARCH_BUTTON,
            style=discord.ButtonStyle.primary,
            custom_id="wiz_search_weapon",
            row=row,
        )
        self.state = state
        self.weapons_view = weapons_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the weapon search modal."""
        await interaction.response.send_modal(
            _WeaponSearchModal(self.state, self.weapons_view)
        )


class _WeaponsWizardView(discord.ui.View):
    """Step 8: Optional SRD weapon search and queue.

    Weapons are stored in ``state.weapons_to_add`` and created as Attack
    records when the wizard commits.  The step can be skipped; the Finish
    button saves the character with whatever has been collected so far
    (including any queued weapons).
    """

    def __init__(self, state: WizardState, step_number: int) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.state = state
        self.step_number = step_number

        self.add_item(_SearchWeaponButton(state, self, row=0))
        self.add_item(_BackButton(prev_step_number=7, state=state, row=1))
        self.add_item(_FinishButton(state, row=1))

    def _build_embed(
        self, no_results_query: Optional[str] = None
    ) -> discord.Embed:
        """Build the weapons step embed."""
        embed = _step_embed(self.step_number, Strings.WIZARD_WEAPONS_STEP_DESC)

        if self.state.weapons_to_add:
            weapon_list = "\n".join(
                f"• {w.get('name', 'Unknown')}"
                for w in self.state.weapons_to_add
            )
            embed.add_field(
                name=Strings.WIZARD_WEAPONS_QUEUED.format(
                    count=len(self.state.weapons_to_add)
                ),
                value=weapon_list,
                inline=False,
            )

        if no_results_query:
            embed.add_field(
                name=Strings.WIZARD_WEAPONS_NO_RESULTS_TITLE,
                value=Strings.WIZARD_WEAPONS_NO_RESULTS.format(
                    query=no_results_query
                ),
                inline=False,
            )

        embed.add_field(
            name="\u200b",
            value=Strings.WIZARD_TIP_WEAPONS,
            inline=False,
        )
        return embed


class _WeaponSelectButton(discord.ui.Button):
    """Adds a search result weapon to ``state.weapons_to_add``."""

    def __init__(
        self,
        state: WizardState,
        weapon_data: dict,
        weapons_view: "_WeaponsWizardView",
    ) -> None:
        super().__init__(
            label=weapon_data.get("name", "Unknown")[:80],
            style=discord.ButtonStyle.primary,
            row=0,
        )
        self.state = state
        self.weapon_data = weapon_data
        self.weapons_view = weapons_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Queue the weapon and return to the weapons step view."""
        weapon_name = self.weapon_data.get("name", "Unknown")
        already_queued = any(
            w.get("name") == weapon_name for w in self.state.weapons_to_add
        )
        if already_queued:
            await interaction.response.send_message(
                Strings.WIZARD_WEAPONS_ALREADY_QUEUED.format(name=weapon_name),
                ephemeral=True,
            )
            return
        self.state.weapons_to_add.append(self.weapon_data)
        await interaction.response.edit_message(
            embed=self.weapons_view._build_embed(), view=self.weapons_view
        )


class _BackToWeaponsButton(discord.ui.Button):
    """Returns to the weapons step without selecting any weapon."""

    def __init__(
        self,
        weapons_view: "_WeaponsWizardView",
        row: int,
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_WEAPONS_BACK_TO_SEARCH,
            style=discord.ButtonStyle.secondary,
            custom_id="wiz_cancel_weapon_results",
            row=row,
        )
        self.weapons_view = weapons_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Return to the weapons view."""
        await interaction.response.edit_message(
            embed=self.weapons_view._build_embed(), view=self.weapons_view
        )


class _WeaponResultsView(discord.ui.View):
    """Shows weapon search results; clicking a weapon queues it."""

    def __init__(
        self,
        state: WizardState,
        results: list[dict],
        weapons_view: "_WeaponsWizardView",
    ) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        for weapon_data in results:
            self.add_item(_WeaponSelectButton(state, weapon_data, weapons_view))
        self.add_item(_BackToWeaponsButton(weapons_view, row=1))

    def _build_embed(self) -> discord.Embed:
        """Build the results selection embed."""
        embed = _step_embed(8, Strings.WIZARD_WEAPONS_RESULTS_DESC)
        embed.add_field(
            name=Strings.WIZARD_WEAPONS_RESULT_SELECT,
            value="\u200b",
            inline=False,
        )
        return embed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def start_character_creation(interaction: discord.Interaction) -> None:
    """Respond to /character create with the wizard intro message."""
    logger.debug(
        f"Command /character create called by {interaction.user} "
        f"(ID: {interaction.user.id}) in guild {interaction.guild_id}"
    )
    state = WizardState(
        user_discord_id=str(interaction.user.id),
        guild_discord_id=str(interaction.guild_id),
        guild_name=getattr(interaction.guild, "name", str(interaction.guild_id)),
    )
    embed = discord.Embed(
        title=Strings.WIZARD_INTRO_TITLE,
        description=Strings.WIZARD_INTRO_DESC,
        color=discord.Color.blurple(),
    )
    view = _WizardIntroView(state)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
