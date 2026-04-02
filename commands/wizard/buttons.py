"""Shared button components for the character creation wizard.

Navigation buttons (``_SaveReturnButton``, ``_ReturnNoSaveButton``) are
placed on every section view.  ``_CancelWizardButton`` and
``_HubCancelButton`` are hub-only — cancel is not available on section pages.

Section-specific action buttons (opens-a-modal, toggles, remove) are also
defined here so they can be imported by both ``section_views`` and
``hub_view`` without circular imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from commands.wizard.state import WizardState, _ALL_STATS, _STAT_DISPLAY
from enums.character_class import CharacterClass
from utils.class_data import get_class_save_profs
from utils.strings import Strings

if TYPE_CHECKING:
    from commands.wizard.section_views import (
        _ClassLevelView,
        _StatsView,
        _ACView,
        _SavesView,
        _SkillsView,
        _HPView,
        _WeaponsWizardView,
    )


# ---------------------------------------------------------------------------
# Auto-calculated button style helpers
# ---------------------------------------------------------------------------


def _initiative_hub_style(state: WizardState) -> discord.ButtonStyle:
    """Return the hub button style for Initiative.

    Green  — explicit override is set.
    Blue   — will auto-calculate from Dexterity modifier.
    Red    — no initiative data available.
    """
    if state.initiative_bonus is not None:
        return discord.ButtonStyle.success
    if state.dexterity is not None:
        return discord.ButtonStyle.primary
    return discord.ButtonStyle.danger


# ---------------------------------------------------------------------------
# Hub navigation buttons
# ---------------------------------------------------------------------------


class _SaveReturnButton(discord.ui.Button):
    """Save the current section and return to the hub."""

    def __init__(self) -> None:
        super().__init__(
            label=Strings.WIZARD_SECTION_SAVE_RETURN,
            style=discord.ButtonStyle.success,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delegate to the parent view's save-and-return handler."""
        await self.view._save_and_return(interaction)


class _ReturnNoSaveButton(discord.ui.Button):
    """Return to hub discarding changes made in this section."""

    def __init__(self) -> None:
        super().__init__(
            label=Strings.WIZARD_SECTION_RETURN_NO_SAVE,
            style=discord.ButtonStyle.secondary,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delegate to the parent view's discard-and-return handler."""
        await self.view._return_no_save(interaction)


class _CancelWizardButton(discord.ui.Button):
    """Cancel the entire wizard without saving."""

    def __init__(self) -> None:
        super().__init__(
            label=Strings.WIZARD_SECTION_CANCEL,
            style=discord.ButtonStyle.danger,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delegate to the parent view's cancel handler."""
        await self.view._cancel_wizard(interaction)


# ---------------------------------------------------------------------------
# Saving throw toggle
# ---------------------------------------------------------------------------


class _SaveToggleButton(discord.ui.Button):
    """A toggle button for a single saving throw proficiency."""

    def __init__(
        self, stat: str, is_proficient: bool, saves_view: "_SavesView"
    ) -> None:
        style = (
            discord.ButtonStyle.success
            if is_proficient
            else discord.ButtonStyle.secondary
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
        current = self.saves_view.wizard_state.saving_throws.get(self.stat, False)
        self.saves_view.wizard_state.saving_throws[self.stat] = not current
        self.saves_view.wizard_state.saves_explicitly_set = True
        await self.saves_view._refresh(interaction)


# ---------------------------------------------------------------------------
# Skill toggle
# ---------------------------------------------------------------------------


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
            discord.ButtonStyle.success
            if is_proficient
            else discord.ButtonStyle.secondary
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
        current = self.skills_view.wizard_state.skills.get(self.skill, False)
        self.skills_view.wizard_state.skills[self.skill] = not current
        await self.skills_view._refresh(interaction)


# ---------------------------------------------------------------------------
# Class remove button
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
# Stats section buttons
# ---------------------------------------------------------------------------


def _physical_stats_complete(state: WizardState) -> bool:
    """Return True when STR, DEX, and CON are all set."""
    return all(
        getattr(state, s) is not None for s in ("strength", "dexterity", "constitution")
    )


def _mental_stats_complete(state: WizardState) -> bool:
    """Return True when INT, WIS, and CHA are all set."""
    return all(
        getattr(state, s) is not None for s in ("intelligence", "wisdom", "charisma")
    )


class _PrimaryStatsButton(discord.ui.Button):
    """Opens the primary stats modal (STR/DEX/CON).

    Green when all three physical stats are set; red when any is missing.
    """

    def __init__(self, state: WizardState, parent_view: "_StatsView", row: int) -> None:
        style = (
            discord.ButtonStyle.success
            if _physical_stats_complete(state)
            else discord.ButtonStyle.danger
        )
        super().__init__(
            label=Strings.WIZARD_PHYSICAL_STATS_BUTTON,
            style=style,
            custom_id="wiz_physical_stats",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the primary stats modal."""
        from commands.wizard.modals import _PhysicalStatsModal

        await interaction.response.send_modal(
            _PhysicalStatsModal(self.state, self.parent_view)
        )


class _WisChaButton(discord.ui.Button):
    """Opens the INT/WIS/CHA modal.

    Green when all three mental stats are set; red when any is missing.
    """

    def __init__(self, state: WizardState, parent_view: "_StatsView", row: int) -> None:
        style = (
            discord.ButtonStyle.success
            if _mental_stats_complete(state)
            else discord.ButtonStyle.danger
        )
        super().__init__(
            label=Strings.WIZARD_MENTAL_STATS_BUTTON,
            style=style,
            custom_id="wiz_mental_stats",
            row=row,
        )
        self.state = state
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the INT/WIS/CHA modal."""
        from commands.wizard.modals import _MentalStatsModal

        await interaction.response.send_modal(
            _MentalStatsModal(self.state, self.parent_view)
        )


class _HubInitiativeButton(discord.ui.Button):
    """Hub button for Initiative — opens the override modal directly from the hub.

    Green when an explicit override is set; primary (blue) when initiative will
    be auto-calculated from Dexterity; red when neither is available.
    """

    def __init__(self, state: WizardState, row: int) -> None:
        style = _initiative_hub_style(state)
        super().__init__(
            label=Strings.WIZARD_HUB_INITIATIVE_BUTTON,
            style=style,
            custom_id="wiz_hub_initiative",
            row=row,
        )
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the Initiative override modal; submitting returns to hub."""
        from commands.wizard.modals import _InitiativeModal

        await interaction.response.send_modal(_InitiativeModal(self.state))


# ---------------------------------------------------------------------------
# AC section button
# ---------------------------------------------------------------------------


class _EnterACButton(discord.ui.Button):
    """Opens the AC modal."""

    def __init__(self, state: WizardState, parent_view: "_ACView", row: int) -> None:
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
        from commands.wizard.modals import _ACModal

        await interaction.response.send_modal(_ACModal(self.state, self.parent_view))


# ---------------------------------------------------------------------------
# HP section button
# ---------------------------------------------------------------------------


class _SetHPButton(discord.ui.Button):
    """Opens the HP override modal."""

    def __init__(self, state: WizardState, parent_view: "_HPView", row: int) -> None:
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
        from commands.wizard.modals import _HPModal

        await interaction.response.send_modal(_HPModal(self.state, self.parent_view))


# ---------------------------------------------------------------------------
# Weapons section buttons
# ---------------------------------------------------------------------------


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
        from commands.wizard.modals import _WeaponSearchModal

        await interaction.response.send_modal(
            _WeaponSearchModal(self.state, self.weapons_view)
        )


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
        """Queue the weapon and return to the weapons section view."""
        weapon_name = self.weapon_data.get("name", "Unknown")
        already_queued = any(
            w.get("name") == weapon_name for w in self.state.weapons_to_add
        )
        already_existing = any(
            name == weapon_name for _, name in self.state.existing_attacks
        )
        if already_queued or already_existing:
            await interaction.response.send_message(
                Strings.WIZARD_WEAPONS_ALREADY_QUEUED.format(name=weapon_name),
                ephemeral=True,
            )
            return
        self.state.weapons_to_add.append(self.weapon_data)
        await interaction.response.edit_message(
            embed=self.weapons_view._build_embed(), view=self.weapons_view
        )


class _WeaponRemoveButton(discord.ui.Button):
    """Removes an existing attack from the edit wizard's tracked list.

    Clicking this button pops the attack from ``state.existing_attacks`` and
    adds its ID to ``state.weapons_to_remove`` so the attack is deleted when
    the wizard saves.  Only used in edit mode.
    """

    def __init__(
        self,
        attack_id: int,
        attack_name: str,
        state: WizardState,
        weapons_view: "_WeaponsWizardView",
        row: int,
    ) -> None:
        super().__init__(
            label=Strings.WIZARD_WEAPONS_REMOVE_BUTTON.format(name=attack_name[:70]),
            style=discord.ButtonStyle.danger,
            custom_id=f"wiz_remove_attack_{attack_id}",
            row=row,
        )
        self.attack_id = attack_id
        self.state = state
        self.weapons_view = weapons_view

    async def callback(self, interaction: discord.Interaction) -> None:
        """Remove the attack from state and refresh the weapons view."""
        self.state.existing_attacks = [
            (aid, aname)
            for aid, aname in self.state.existing_attacks
            if aid != self.attack_id
        ]
        if self.attack_id not in self.state.weapons_to_remove:
            self.state.weapons_to_remove.append(self.attack_id)
        await self.weapons_view._refresh(interaction)


class _BackToWeaponsButton(discord.ui.Button):
    """Returns to the weapons section without selecting any weapon."""

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
