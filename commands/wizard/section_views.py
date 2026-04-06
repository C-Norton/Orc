"""Section views for the character creation wizard hub model.

Each view corresponds to one configurable section of the character sheet.
All section views share two navigation buttons:
  - ``_SaveReturnButton``  — mark section complete and return to hub
  - ``_ReturnNoSaveButton`` — restore pre-entry snapshot and return to hub

Cancel is only available on the main hub page.
Section-specific action buttons (open modals, toggle proficiencies, etc.)
are defined in ``buttons.py``.
"""

from __future__ import annotations

import discord

from commands.wizard.buttons import (
    _BackToWeaponsButton,
    _ClassRemoveButton,
    _EnterACButton,
    _PrimaryStatsButton,
    _ReturnNoSaveButton,
    _SaveReturnButton,
    _SaveToggleButton,
    _SearchWeaponButton,
    _SetHPButton,
    _SkillToggleButton,
    _WeaponRemoveButton,
    _WeaponSelectButton,
    _IntWisChaButton,
)
from commands.wizard.state import (
    WizardState,
    _ALL_STATS,
    _MAX_CHARACTER_LEVEL,
    _MAX_CLASSES,
    _MAX_EXISTING_WEAPON_BUTTONS,
    _SKILLS,
    _STAT_DISPLAY,
    _WIZARD_TIMEOUT,
    restore_section,
    snapshot_section,
)
from enums.character_class import CharacterClass
from utils.strings import Strings


# ---------------------------------------------------------------------------
# Section view base class
# ---------------------------------------------------------------------------


def _section_embed(title: str, description: str) -> discord.Embed:
    """Build a standard section embed with a blurple colour."""
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
    )


class _WizardSectionView(discord.ui.View):
    """Base class for all wizard section views.

    Provides the three methods shared by every section:

    - ``_save_and_return`` — marks section complete and returns to hub.
    - ``_return_no_save`` — restores pre-entry snapshot and returns to hub.
    - ``on_timeout`` — clears the state reference to prevent memory leaks.

    Subclasses must set ``_section_key`` and ``_section_snapshot`` before
    calling these methods.  Override ``_save_and_return`` if extra work is
    needed before marking the section complete (e.g. ``_SavesView``).
    """

    _section_key: str
    _section_snapshot: dict

    def __init__(self, wizard_state: WizardState, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.wizard_state = wizard_state

    async def _save_and_return(self, interaction: discord.Interaction) -> None:
        """Mark section complete and return to hub."""
        from commands.wizard import _show_hub

        self.wizard_state.sections_completed.add(self._section_key)
        await _show_hub(interaction, self.wizard_state)

    async def _return_no_save(self, interaction: discord.Interaction) -> None:
        """Restore snapshot and return to hub without saving."""
        from commands.wizard import _show_hub

        restore_section(self.wizard_state, self._section_key, self._section_snapshot)
        await _show_hub(interaction, self.wizard_state)

    async def on_timeout(self) -> None:
        """Clear state reference to prevent memory leak."""
        self.wizard_state = None


# ---------------------------------------------------------------------------
# Class & Level section
# ---------------------------------------------------------------------------


class _ClassLevelView(_WizardSectionView):
    """Class & Level section: class selection with multiclass support.

    The class dropdown opens a level modal on selection.  Each added class
    shows a remove button.  Up to ``_MAX_CLASSES`` classes may be added;
    total level across all classes may not exceed ``_MAX_CHARACTER_LEVEL``.
    """

    _section_key = "class_level"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)
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
        for class_enum, _ in self.wizard_state.classes_and_levels:
            self.add_item(
                _ClassRemoveButton(
                    state=self.wizard_state,
                    class_enum=class_enum,
                    parent_view=self,
                    row=1,
                )
            )

        # Row 2: navigation back to hub
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    async def _on_class_selected(self, interaction: discord.Interaction) -> None:
        """Open a level modal for the selected class."""
        from commands.wizard.modals import _LevelForClassModal

        selected = self._class_select.values[0]
        class_enum = CharacterClass(selected)

        existing_index: int | None = next(
            (
                i
                for i, (cls, _) in enumerate(self.wizard_state.classes_and_levels)
                if cls == class_enum
            ),
            None,
        )

        if (
            existing_index is None
            and len(self.wizard_state.classes_and_levels) >= _MAX_CLASSES
        ):
            await interaction.response.send_message(
                Strings.WIZARD_CLASS_MAX_REACHED.format(max=_MAX_CLASSES),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            _LevelForClassModal(self.wizard_state, class_enum, existing_index, self)
        )

    def _build_embed(self) -> discord.Embed:
        """Build the Class & Level section embed."""
        embed = _section_embed(
            Strings.WIZARD_HUB_CLASS_LEVEL_BUTTON, Strings.WIZARD_CLASS_LEVEL_DESC
        )
        if self.wizard_state.classes_and_levels:
            class_lines = "\n".join(
                f"**{cls.value}** Lv {lv}"
                for cls, lv in self.wizard_state.classes_and_levels
            )
            embed.add_field(
                name=Strings.WIZARD_CLASS_TOTAL_LEVEL.format(
                    total=self.wizard_state.total_level, max=_MAX_CHARACTER_LEVEL
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
        """Rebuild items and re-render the embed (called by level modal)."""
        self._build_items()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


# ---------------------------------------------------------------------------
# Ability Scores section
# ---------------------------------------------------------------------------


class _StatsView(_WizardSectionView):
    """Ability Scores section: STR/DEX/CON and INT/WIS/CHA modal buttons.

    Each button is green when all stats in its group are set, red otherwise.
    Buttons are rebuilt on every refresh so colours stay current after modal
    submissions.  Initiative has moved to the hub page.
    """

    _section_key = "ability_scores"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)
        self._build_items()

    def _build_items(self) -> None:
        """Rebuild buttons with current completion-based styles."""
        self.clear_items()
        self.add_item(_PrimaryStatsButton(self.wizard_state, self, row=0))
        self.add_item(_IntWisChaButton(self.wizard_state, self, row=1))
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    def _build_embed(self) -> discord.Embed:
        """Build the Ability Scores section embed, listing all set stats."""
        embed = _section_embed(
            Strings.WIZARD_HUB_ABILITY_SCORES_BUTTON, Strings.WIZARD_STATS_DESC
        )
        set_stats = {
            s: getattr(self.wizard_state, s)
            for s in _ALL_STATS
            if getattr(self.wizard_state, s) is not None
        }
        if set_stats:
            stat_text = "  ".join(
                f"**{_STAT_DISPLAY[s]}** {v}" for s, v in set_stats.items()
            )
            embed.add_field(
                name=Strings.WIZARD_STATS_CURRENTLY_SET, value=stat_text, inline=False
            )
        return embed

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild items (updating button colours) then re-render the embed."""
        self._build_items()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


# ---------------------------------------------------------------------------
# Armor Class section
# ---------------------------------------------------------------------------


class _ACView(_WizardSectionView):
    """Armor Class section: single modal-opening button."""

    _section_key = "ac"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)

        self.add_item(_EnterACButton(wizard_state, self, row=0))
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    def _build_embed(self) -> discord.Embed:
        """Build the AC section embed."""
        embed = _section_embed(Strings.WIZARD_HUB_AC_BUTTON, Strings.WIZARD_AC_DESC)
        if self.wizard_state.ac is not None:
            embed.add_field(
                name=Strings.WIZARD_AC_FIELD_NAME,
                value=str(self.wizard_state.ac),
                inline=True,
            )
        return embed


# ---------------------------------------------------------------------------
# Saving Throws section
# ---------------------------------------------------------------------------


class _SavesView(_WizardSectionView):
    """Saving Throws section: six toggle buttons."""

    _section_key = "saving_throws"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)
        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add save toggle buttons and navigation buttons."""
        for stat in _ALL_STATS:
            is_prof = self.wizard_state.saving_throws.get(stat, False)
            self.add_item(_SaveToggleButton(stat, is_prof, self))
        # Toggle buttons occupy rows 0 and 1; nav on row 2
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild buttons and re-render the embed."""
        self.clear_items()
        self._add_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self) -> discord.Embed:
        """Build the Saving Throws section embed."""
        if self.wizard_state.character_class is not None:
            desc = Strings.WIZARD_SAVES_DESC_CLASS.format(
                char_class=self.wizard_state.character_class.value
            )
        else:
            desc = Strings.WIZARD_SAVES_DESC_NO_CLASS
        return _section_embed(Strings.WIZARD_HUB_SAVING_THROWS_BUTTON, desc)

    async def _save_and_return(self, interaction: discord.Interaction) -> None:
        """Record that saves were explicitly configured, then return to hub."""
        # Flag must be set before the base-class call marks the section complete
        self.wizard_state.saves_explicitly_set = True
        await super()._save_and_return(interaction)


# ---------------------------------------------------------------------------
# Skills section
# ---------------------------------------------------------------------------


class _SkillsView(_WizardSectionView):
    """Skills section: eighteen skill toggle buttons."""

    _section_key = "skills"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)
        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add all 18 skill toggles across rows 0–3, navigation on row 4."""
        for index, skill in enumerate(_SKILLS):
            row = index // 5  # rows 0–3
            is_prof = self.wizard_state.skills.get(skill, False)
            self.add_item(_SkillToggleButton(skill, is_prof, self, row=row))
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild buttons and re-render the embed."""
        self.clear_items()
        self._add_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self) -> discord.Embed:
        """Build the Skills section embed."""
        return _section_embed(
            Strings.WIZARD_HUB_SKILLS_BUTTON, Strings.WIZARD_SKILLS_DESC
        )


# ---------------------------------------------------------------------------
# Hit Points section
# ---------------------------------------------------------------------------


class _HPView(_WizardSectionView):
    """Hit Points section: optional manual HP override."""

    _section_key = "hp"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)

        self.add_item(_SetHPButton(wizard_state, self, row=0))
        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    def _build_embed(self) -> discord.Embed:
        """Build the HP section embed, showing override value or auto-calc hint."""
        embed = _section_embed(
            Strings.WIZARD_HUB_HP_BUTTON, Strings.WIZARD_HP_STEP_DESC
        )
        if self.wizard_state.hp_override is not None:
            embed.add_field(
                name=Strings.WIZARD_HP_MAX_HP_FIELD,
                value=Strings.WIZARD_HP_SET.format(hp=self.wizard_state.hp_override),
                inline=False,
            )
        else:
            can_auto_calc = (
                bool(self.wizard_state.classes_and_levels)
                and self.wizard_state.constitution is not None
            )
            hint = (
                Strings.WIZARD_HP_WILL_AUTO_CALC
                if can_auto_calc
                else Strings.WIZARD_HP_CANNOT_AUTO_CALC
            )
            embed.add_field(
                name=Strings.WIZARD_HP_STATUS_FIELD, value=hint, inline=False
            )
        return embed


# ---------------------------------------------------------------------------
# Weapons section
# ---------------------------------------------------------------------------


class _WeaponsWizardView(_WizardSectionView):
    """Weapons section: SRD weapon search and queue.

    In creation mode, ``wizard_state.weapons_to_add`` holds raw Open5e weapon
    dicts queued for creation when the wizard commits.

    In edit mode, ``wizard_state.existing_attacks`` holds (id, name) pairs
    for attacks already on the character.  Each is shown with a remove button;
    clicking one marks the attack's ID in ``wizard_state.weapons_to_remove``
    so it is deleted at commit time.  Up to ``_MAX_EXISTING_WEAPON_BUTTONS``
    existing attacks can be shown as remove buttons (rows 1–3, five per row).
    """

    _section_key = "weapons"

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(wizard_state, timeout=_WIZARD_TIMEOUT)
        self._section_snapshot = snapshot_section(wizard_state, self._section_key)
        self._build_items()

    def _build_items(self) -> None:
        """Rebuild all buttons from current state."""
        self.clear_items()
        self.add_item(_SearchWeaponButton(self.wizard_state, self, row=0))

        # Remove buttons for existing attacks (edit mode only), rows 1–3
        for index, (attack_id, attack_name) in enumerate(
            self.wizard_state.existing_attacks[:_MAX_EXISTING_WEAPON_BUTTONS]
        ):
            row = 1 + index // 5
            self.add_item(
                _WeaponRemoveButton(
                    attack_id, attack_name, self.wizard_state, self, row=row
                )
            )

        self.add_item(_SaveReturnButton())
        self.add_item(_ReturnNoSaveButton())

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild buttons from current state and update the message."""
        self._build_items()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self, no_results_query: str | None = None) -> discord.Embed:
        """Build the Weapons section embed."""
        embed = _section_embed(
            Strings.WIZARD_HUB_WEAPONS_BUTTON, Strings.WIZARD_WEAPONS_STEP_DESC
        )

        # Show attacks currently on the character (edit mode)
        if self.wizard_state.existing_attacks:
            existing_list = "\n".join(
                f"• {name}" for _, name in self.wizard_state.existing_attacks
            )
            embed.add_field(
                name=Strings.WIZARD_WEAPONS_EXISTING.format(
                    count=len(self.wizard_state.existing_attacks)
                ),
                value=existing_list,
                inline=False,
            )

        if self.wizard_state.weapons_to_add:
            weapon_list = "\n".join(
                f"• {w.get('name', 'Unknown')}"
                for w in self.wizard_state.weapons_to_add
            )
            embed.add_field(
                name=Strings.WIZARD_WEAPONS_QUEUED.format(
                    count=len(self.wizard_state.weapons_to_add)
                ),
                value=weapon_list,
                inline=False,
            )

        if no_results_query:
            embed.add_field(
                name=Strings.WIZARD_WEAPONS_NO_RESULTS_TITLE,
                value=Strings.WIZARD_WEAPONS_NO_RESULTS.format(query=no_results_query),
                inline=False,
            )

        embed.add_field(
            name="\u200b",
            value=Strings.WIZARD_TIP_WEAPONS,
            inline=False,
        )
        return embed


# ---------------------------------------------------------------------------
# Weapon search results sub-view (no section key; child of weapons section)
# ---------------------------------------------------------------------------


class _WeaponResultsView(discord.ui.View):
    """Shows weapon search results; clicking a weapon queues it.

    This is a transient sub-view of ``_WeaponsWizardView``.  Navigating
    back returns the user to the parent weapons view rather than the hub.
    """

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
        embed = _section_embed(
            Strings.WIZARD_HUB_WEAPONS_BUTTON, Strings.WIZARD_WEAPONS_RESULTS_DESC
        )
        embed.add_field(
            name=Strings.WIZARD_WEAPONS_RESULT_SELECT,
            value="\u200b",
            inline=False,
        )
        return embed
