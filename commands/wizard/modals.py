"""Modal classes for the character creation wizard.

Each modal corresponds to one data-entry form.  After submission the modal
either returns the user to their section view (internal refresh) or to the
hub (name modal).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from commands.wizard.state import WizardState, _ALL_STATS, _MAX_CHARACTER_LEVEL
from enums.character_class import CharacterClass
from enums.ruleset_edition import RulesetEdition
from utils.class_data import get_class_save_profs
from utils.logging_config import get_logger
from utils.strings import Strings
from utils.weapon_utils import fetch_weapons

if TYPE_CHECKING:
    from commands.wizard.section_views import (
        _ACView,
        _ClassLevelView,
        _HPView,
        _StatsView,
        _WeaponsWizardView,
    )

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared validation helper
# ---------------------------------------------------------------------------


async def _validate_stat_inputs(
    mapping: dict[str, str],
    interaction: discord.Interaction,
) -> dict[str, int] | None:
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


# ---------------------------------------------------------------------------
# Name modal
# ---------------------------------------------------------------------------


class _CharacterNameModal(discord.ui.Modal):
    """Collect the character's name and return to the hub."""

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
        """Save name and return to the hub."""
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                Strings.WIZARD_NAME_REQUIRED, ephemeral=True
            )
            return
        self.state.name = name
        # Return to hub with name now set
        from commands.wizard import _show_hub

        await _show_hub(interaction, self.state)


# ---------------------------------------------------------------------------
# Class & level modal
# ---------------------------------------------------------------------------


class _LevelForClassModal(discord.ui.Modal):
    """Collect or update the level for a specific class in the wizard."""

    def __init__(
        self,
        state: WizardState,
        class_enum: CharacterClass,
        existing_index: int | None,
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
        if not 1 <= level <= _MAX_CHARACTER_LEVEL:
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
        if new_total > _MAX_CHARACTER_LEVEL:
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

        await self.parent_view._refresh(interaction)


# ---------------------------------------------------------------------------
# Ability score modals
# ---------------------------------------------------------------------------


class _PhysicalStatsModal(discord.ui.Modal):
    """Collect the four physical ability scores (STR/DEX/CON)."""

    str_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_STR_LABEL,
        placeholder="e.g. 16",
        max_length=2,
        required=True,
    )
    dex_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_DEX_LABEL,
        placeholder="e.g. 14",
        max_length=2,
        required=True,
    )
    con_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_CON_LABEL,
        placeholder="e.g. 15",
        max_length=2,
        required=True,
    )

    def __init__(self, state: WizardState, parent_view: "_StatsView") -> None:
        super().__init__(title=Strings.WIZARD_PRIMARY_STATS_MODAL_TITLE)
        self.state = state
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate and store STR/DEX/CON, refresh the Stats section view."""
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

        # Delegate to _refresh so button colours update immediately
        await self.parent_view._refresh(interaction)


class _MentalStatsModal(discord.ui.Modal):
    """Collect Intelligence, Wisdom, and Charisma; refreshes the Stats section."""

    wis_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_WIS_LABEL,
        placeholder="e.g. 12",
        max_length=2,
        required=True,
    )
    cha_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_CHA_LABEL,
        placeholder="e.g. 8",
        max_length=2,
        required=True,
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
        """Validate INT/WIS/CHA, then refresh the Stats section."""
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

        # Delegate to _refresh so button colours update immediately
        await self.parent_view._refresh(interaction)


class _InitiativeModal(discord.ui.Modal):
    """Collect an optional initiative bonus override; returns to the hub on submit."""

    init_input: discord.ui.TextInput = discord.ui.TextInput(
        label=Strings.WIZARD_INIT_LABEL,
        placeholder="e.g. +2 or -1  (leave blank to use Dex mod)",
        max_length=4,
        required=False,
    )

    def __init__(self, state: WizardState) -> None:
        super().__init__(title=Strings.WIZARD_INIT_MODAL_TITLE)
        self.state = state

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Store the initiative override, or clear it if left blank, then return to hub."""
        raw = self.init_input.value.strip().lstrip("+")
        if not raw:
            # Blank entry clears any override; initiative falls back to Dex mod.
            self.state.initiative_bonus = None
        else:
            try:
                self.state.initiative_bonus = int(raw)
            except ValueError:
                await interaction.response.send_message(
                    Strings.WIZARD_STAT_NOT_NUMBER.format(stat="Initiative bonus"),
                    ephemeral=True,
                )
                return
        from commands.wizard import _show_hub

        await _show_hub(interaction, self.state)


# ---------------------------------------------------------------------------
# AC modal
# ---------------------------------------------------------------------------


class _ACModal(discord.ui.Modal):
    """Collect Armor Class; refreshes the AC section."""

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
        """Validate AC, then refresh the AC section."""
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
        await interaction.response.edit_message(
            embed=self.parent_view._build_embed(), view=self.parent_view
        )


# ---------------------------------------------------------------------------
# HP modal
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Weapon search modal
# ---------------------------------------------------------------------------


class _WeaponSearchModal(discord.ui.Modal):
    """Search for SRD weapons during the wizard's Weapons section.

    The response is deferred so the network request can complete within the
    15-minute followup window rather than the 3-second initial window.
    """

    def __init__(self, state: WizardState, weapons_view: "_WeaponsWizardView") -> None:
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
        from commands.wizard.section_views import _WeaponResultsView

        query = self.query_input.value.strip()
        await interaction.response.defer()
        try:
            results = await fetch_weapons(query, RulesetEdition.RULES_2024)
        except Exception as exc:
            logger.error(
                f"Wizard weapon search failed for {query!r}: {exc}", exc_info=True
            )
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


# ---------------------------------------------------------------------------
# Manual setup modal
# ---------------------------------------------------------------------------


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
        from commands.wizard.state import save_character_from_wizard
        from database import db_session

        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                Strings.WIZARD_NAME_REQUIRED, ephemeral=True
            )
            return

        character_class: CharacterClass | None = None
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
            if not 1 <= level <= _MAX_CHARACTER_LEVEL:
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
        # Pre-fill saving throws on the state so it reflects the applied class profs.
        # save_character_from_wizard will also apply them directly via
        # apply_class_save_profs, keeping the character record consistent.
        if character_class:
            class_profs = get_class_save_profs(character_class)
            state.saving_throws = {s: s in class_profs for s in _ALL_STATS}

        with db_session() as db:
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
                await interaction.response.send_message(
                    Strings.ERROR_GENERIC, ephemeral=True
                )
