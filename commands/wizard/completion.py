"""Wizard completion logic and embed builders.

``_finish_wizard`` commits the wizard state to the database and displays the
completion summary.  ``_build_complete_embed`` and its helper
``_add_wizard_embed_field`` build the Discord embed shown on success.
"""

from __future__ import annotations

from typing import Optional

import discord

from commands.wizard.state import (
    WizardState,
    save_character_from_wizard,
    update_character_from_wizard,
    _ALL_STATS,
    _STAT_DISPLAY,
)
from database import SessionLocal
from models import Character
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


async def _finish_wizard(
    wizard_state: WizardState,
    interaction: discord.Interaction,
) -> None:
    """Commit the wizard to the DB and display the completion embed.

    Branches on ``wizard_state.edit_character_id``: calls
    ``update_character_from_wizard`` for edit mode and
    ``save_character_from_wizard`` for new-character creation.
    """
    is_edit = wizard_state.edit_character_id is not None
    db = SessionLocal()
    try:
        if is_edit:
            char, error = update_character_from_wizard(wizard_state, db)
        else:
            char, error = save_character_from_wizard(wizard_state, interaction, db)

        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        db.commit()

        if is_edit:
            logger.info(
                f"Wizard edit completed: updated '{char.name}' for user "
                f"{interaction.user.id} in guild {interaction.guild_id}"
            )
            embed = _build_edit_complete_embed(wizard_state, char)
            dismiss = Strings.WIZARD_EDIT_COMPLETE_EPHEMERAL_DISMISS
        else:
            logger.info(
                f"Wizard completed: created '{char.name}' for user "
                f"{interaction.user.id} in guild {interaction.guild_id}"
            )
            embed = _build_complete_embed(wizard_state, char)
            dismiss = Strings.WIZARD_COMPLETE_EPHEMERAL_DISMISS

        # Discord does not allow changing ephemeral status, so dismiss the
        # ephemeral wizard message and send the summary publicly.
        await interaction.response.edit_message(content=dismiss, embed=None, view=None)
        await interaction.followup.send(embed=embed, ephemeral=False)
    except Exception as exc:
        db.rollback()
        logger.error(
            f"Error committing character wizard for user {interaction.user.id}: {exc}",
            exc_info=True,
        )
        await interaction.response.send_message(Strings.ERROR_GENERIC, ephemeral=True)
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
            _STAT_DISPLAY[s] for s in _ALL_STATS if state.saving_throws.get(s, False)
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


def _build_edit_complete_embed(state: WizardState, char: Character) -> discord.Embed:
    """Build the edit-wizard completion embed showing the updated character state."""
    embed = discord.Embed(
        title=Strings.WIZARD_EDIT_COMPLETE_TITLE.format(name=state.name),
        description=Strings.WIZARD_EDIT_COMPLETE_DESC,
        color=discord.Color.green(),
    )

    # Class & Level
    if state.classes_and_levels:
        class_value = "\n".join(
            f"{cls.value} {lv}" for cls, lv in state.classes_and_levels
        )
    else:
        class_value = None
    _add_wizard_embed_field(
        embed, "Class & Level", class_value, "/character class_add", inline=True
    )

    # Ability Scores
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

    # HP
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

    # Saving Throws
    prof_saves = [
        _STAT_DISPLAY[s] for s in _ALL_STATS if state.saving_throws.get(s, False)
    ]
    saves_value = ", ".join(prof_saves) if prof_saves else "None"
    _add_wizard_embed_field(embed, "Saving Throws", saves_value, "/character saves")

    # Skills
    proficient_skills = [sk for sk, val in state.skills.items() if val]
    skills_value = ", ".join(proficient_skills) if proficient_skills else None
    _add_wizard_embed_field(embed, "Skills", skills_value, "/character skill")

    # Weapons — show remaining existing + newly added
    all_weapon_names = [name for _, name in state.existing_attacks] + [
        w.get("name", "Unknown") for w in state.weapons_to_add
    ]
    weapons_value = ", ".join(all_weapon_names) if all_weapon_names else None
    _add_wizard_embed_field(embed, "Weapons", weapons_value, "/weapon search")

    embed.set_footer(text=Strings.WIZARD_COMPLETE_FOOTER)

    if char.max_hp == -1:
        embed.description = (
            f"{Strings.WIZARD_EDIT_COMPLETE_DESC}\n\n{Strings.WIZARD_COMPLETE_TIP_HP}"
        )

    return embed
