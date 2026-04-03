"""Hub view for the character creation wizard.

The hub is the central page users see between section visits.  Section button
colours convey completion state:

  🟢 Green  (success)  — user has explicitly configured this section.
  🔵 Blue   (primary)  — value will be auto-calculated from other settings.
  🔴 Red    (danger)   — section not yet touched and no auto-calc available.

Name is required to enable Save & Exit; all other sections are optional.
Initiative lives on the hub itself (opens a modal directly).
"""

from __future__ import annotations

import discord

from commands.wizard.state import WizardState, _WIZARD_TIMEOUT
from utils.strings import Strings


async def _show_hub(
    interaction: discord.Interaction, wizard_state: WizardState
) -> None:
    """Edit the current message to display the hub view."""
    embed = _build_hub_embed(wizard_state)
    view = HubView(wizard_state)
    await interaction.response.edit_message(embed=embed, view=view)


# Ordered list of (section_key, button_label, discord_row) for section buttons.
_SECTION_BUTTONS: list[tuple[str, str, int]] = [
    ("class_level", Strings.WIZARD_HUB_CLASS_LEVEL_BUTTON, 1),
    ("ability_scores", Strings.WIZARD_HUB_ABILITY_SCORES_BUTTON, 1),
    ("ac", Strings.WIZARD_HUB_AC_BUTTON, 1),
    ("saving_throws", Strings.WIZARD_HUB_SAVING_THROWS_BUTTON, 1),
    ("skills", Strings.WIZARD_HUB_SKILLS_BUTTON, 2),
    ("hp", Strings.WIZARD_HUB_HP_BUTTON, 2),
    ("weapons", Strings.WIZARD_HUB_WEAPONS_BUTTON, 2),
]


def _section_button_style(
    section_key: str, wizard_state: WizardState
) -> discord.ButtonStyle:
    """Return the appropriate button style for a given section.

    Sections whose values can be auto-calculated show blue (primary) rather
    than red (danger) when not explicitly configured but inferable.
    """
    if section_key == "saving_throws":
        if wizard_state.saves_explicitly_set:
            return discord.ButtonStyle.success
        if wizard_state.character_class is not None:
            # Saves were auto-applied from the selected class
            return discord.ButtonStyle.primary
        return discord.ButtonStyle.danger

    if section_key == "hp":
        if wizard_state.hp_override is not None:
            return discord.ButtonStyle.success
        if (
            wizard_state.character_class is not None
            and wizard_state.constitution is not None
        ):
            # HP will be auto-calculated at save time
            return discord.ButtonStyle.primary
        return discord.ButtonStyle.danger

    # Generic sections: green when in sections_completed, red otherwise
    return (
        discord.ButtonStyle.success
        if section_key in wizard_state.sections_completed
        else discord.ButtonStyle.danger
    )


def _build_hub_embed(wizard_state: WizardState) -> discord.Embed:
    """Build the hub embed showing completion status per section.

    In creation mode the Name field shows the current name or a
    "not set (required)" prompt.  In edit mode the title and description
    reflect the edit context and the name is always shown (not editable).
    """
    is_edit = wizard_state.edit_character_id is not None
    embed = discord.Embed(
        title=Strings.WIZARD_EDIT_HUB_TITLE if is_edit else Strings.WIZARD_HUB_TITLE,
        description=Strings.WIZARD_EDIT_HUB_DESC
        if is_edit
        else Strings.WIZARD_HUB_DESC,
        color=discord.Color.blurple(),
    )
    name_value = (
        wizard_state.name if wizard_state.name else Strings.WIZARD_HUB_NAME_NOT_SET
    )
    embed.add_field(
        name=Strings.WIZARD_HUB_NAME_FIELD_LABEL,
        value=name_value,
        inline=False,
    )
    return embed


class _NameButton(discord.ui.Button):
    """Opens the name modal so the user can set or update their character name."""

    def __init__(self, wizard_state: WizardState) -> None:
        is_set = bool(wizard_state.name)
        super().__init__(
            label=Strings.WIZARD_HUB_NAME_BUTTON,
            style=discord.ButtonStyle.success if is_set else discord.ButtonStyle.danger,
            row=0,
        )
        self.wizard_state = wizard_state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the name entry modal."""
        from commands.wizard.modals import _CharacterNameModal

        await interaction.response.send_modal(_CharacterNameModal(self.wizard_state))


class _SectionButton(discord.ui.Button):
    """A hub button that navigates to a specific wizard section.

    Colour reflects completion state via ``_section_button_style``:
    green = configured, blue = auto-calculated, red = not yet set.
    """

    def __init__(
        self,
        section_key: str,
        label: str,
        row: int,
        wizard_state: WizardState,
    ) -> None:
        super().__init__(
            label=label,
            style=_section_button_style(section_key, wizard_state),
            row=row,
        )
        self.section_key = section_key
        self.wizard_state = wizard_state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Navigate to the section view for this button."""
        from commands.wizard.section_views import (
            _ACView,
            _ClassLevelView,
            _HPView,
            _SavesView,
            _SkillsView,
            _StatsView,
            _WeaponsWizardView,
        )

        section_view_map = {
            "class_level": lambda: _ClassLevelView(self.wizard_state),
            "ability_scores": lambda: _StatsView(self.wizard_state),
            "ac": lambda: _ACView(self.wizard_state),
            "saving_throws": lambda: _SavesView(self.wizard_state),
            "skills": lambda: _SkillsView(self.wizard_state),
            "hp": lambda: _HPView(self.wizard_state),
            "weapons": lambda: _WeaponsWizardView(self.wizard_state),
        }
        view = section_view_map[self.section_key]()
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


class _SaveExitButton(discord.ui.Button):
    """Save the character and exit the wizard."""

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(
            label=Strings.WIZARD_HUB_SAVE_EXIT,
            style=discord.ButtonStyle.success,
            # Disabled until a name is provided
            disabled=not bool(wizard_state.name),
            row=3,
        )
        self.wizard_state = wizard_state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Commit the wizard and display the completion embed."""
        from commands.wizard import _finish_wizard

        await _finish_wizard(self.wizard_state, interaction)


class _HubCancelButton(discord.ui.Button):
    """Cancel the entire wizard without saving any character."""

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(
            label=Strings.WIZARD_HUB_CANCEL,
            style=discord.ButtonStyle.danger,
            row=3,
        )
        self.wizard_state = wizard_state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show cancellation embed and stop the view."""
        self.view.stop()
        is_edit = self.wizard_state.edit_character_id is not None
        title = Strings.WIZARD_EDIT_CANCELLED if is_edit else Strings.WIZARD_CANCELLED
        embed = discord.Embed(title=title, color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=None)


class _QuickSetupButton(discord.ui.Button):
    """Opens the manual single-form character creation modal."""

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(
            label=Strings.WIZARD_HUB_MANUAL_BUTTON,
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        self.wizard_state = wizard_state

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the manual setup modal."""
        from commands.wizard.modals import _ManualSetupModal

        await interaction.response.send_modal(
            _ManualSetupModal(
                user_discord_id=self.wizard_state.user_discord_id,
                guild_discord_id=self.wizard_state.guild_discord_id,
                guild_name=self.wizard_state.guild_name,
            )
        )


class HubView(discord.ui.View):
    """The central hub from which the user navigates to each wizard section.

    Section buttons are coloured green when completed and red when not.
    The Save & Exit button is disabled until the user has entered a name.
    """

    def __init__(self, wizard_state: WizardState) -> None:
        super().__init__(timeout=_WIZARD_TIMEOUT)
        self.wizard_state = wizard_state
        self._build_items()

    def _build_items(self) -> None:
        """Populate the view with all hub buttons.

        In edit mode the Name button and Quick Setup button are omitted: the
        character name is not editable via the edit wizard, and quick setup
        only applies to new characters.
        """
        from commands.wizard.buttons import _HubInitiativeButton

        self.clear_items()
        is_edit = self.wizard_state.edit_character_id is not None

        # Row 0: name (create mode only) + initiative (auto-calc aware)
        if not is_edit:
            self.add_item(_NameButton(self.wizard_state))
        self.add_item(_HubInitiativeButton(self.wizard_state, row=0))
        # Rows 1–2: section buttons
        for section_key, label, row in _SECTION_BUTTONS:
            self.add_item(
                _SectionButton(
                    section_key=section_key,
                    label=label,
                    row=row,
                    wizard_state=self.wizard_state,
                )
            )
        # Row 3: global actions
        self.add_item(_SaveExitButton(self.wizard_state))
        self.add_item(_HubCancelButton(self.wizard_state))

    async def on_timeout(self) -> None:
        """Show timeout message and release state reference."""
        self.wizard_state = None
        # ``message`` is set automatically by discord.py in some builds only;
        # use getattr so we don't crash when it is absent.
        message = getattr(self, "message", None)
        if message:
            try:
                embed = discord.Embed(
                    title=Strings.WIZARD_TIMEOUT_MSG,
                    color=discord.Color.red(),
                )
                await message.edit(embed=embed, view=None)
            except Exception:
                pass
