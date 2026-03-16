import discord
from discord import app_commands
from discord.ext import commands
from typing import List
from database import SessionLocal
from models import User, Server, Character
from dice_roller import roll_dice
from utils.constants import SKILL_TO_STAT, STAT_NAMES
from utils.dnd_logic import perform_roll
from utils.logging_config import get_logger

logger = get_logger(__name__)

def register_roll_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="roll", description="Roll a d20 skill check, Save, or standard dice notation.")
    @app_commands.describe(notation="Skill, attribute, save name or dice notation (e.g., 'insight', 'str', 'str save', '1d20+5')")
    async def roll(interaction: discord.Interaction, notation: str) -> None:
        """Unified roll command for skills, attributes, saves and dice notation."""
        logger.debug(f"Command /roll called by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id} with notation: {notation}")
        db = SessionLocal()
        try:
            # Normalize notation for matching
            clean_notation = notation.lower().strip()

            # Check if it's a saving throw
            is_save = False
            if "save" in clean_notation:
                stat_part = clean_notation.replace("save", "").replace("_", "").strip()
                if stat_part in STAT_NAMES:
                    is_save = True

            # Check if the notation matches a skill name (case-insensitive)
            matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean_notation), None)

            # Check if it's a flat attribute roll
            matched_stat = STAT_NAMES.get(clean_notation) if not is_save and not matched_skill else None

            # Check if it's initiative
            is_initiative = clean_notation in ["initiative", "init"]

            if matched_skill or is_save or matched_stat or is_initiative:
                # Character-based roll logic
                user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
                server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
                char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
                logger.debug(f"Character lookup for user {interaction.user.id}: {'found: ' + char.name if char else 'not found'}")

                if not char:
                    await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
                    return

                response = await perform_roll(char, notation, db)
                await interaction.response.send_message(response)
                logger.info(f"/roll completed for user {interaction.user.id}")
            else:
                # Standard dice notation logic
                rolls, modifier, total = roll_dice(notation)

                # Build a nice response message
                rolls_str = ", ".join(map(str, rolls))
                mod_str = f" {modifier:+d}" if modifier != 0 else ""

                response = f"🎲 **{notation}**\n"
                response += f"Rolls: `({rolls_str}){mod_str}`\n"
                response += f"**Total: {total}**"

                await interaction.response.send_message(response)
                logger.info(f"/roll completed for user {interaction.user.id}")

        except ValueError as e:
            logger.warning(f"ValueError in /roll (notation: {notation}): {e}")
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in /roll (notation: {notation}): {e}", exc_info=True)
            await interaction.response.send_message(f"❌ An unexpected error occurred.", ephemeral=True)
        finally:
            db.close()

    @roll.autocomplete("notation")
    async def roll_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for the roll command suggesting skill names, stats, and saves."""
        suggestions = []

        # Add skills
        skills = sorted(SKILL_TO_STAT.keys())
        suggestions.extend([skill for skill in skills])

        # Add initiative
        suggestions.append("Initiative")

        # Add attributes
        stats = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
        suggestions.extend(stats)

        # Add common abbreviations
        suggestions.extend(["Str", "Dex", "Con", "Int", "Wis", "Cha"])

        # Add saving throws
        for stat in stats:
            suggestions.append(f"{stat} Save")
        for stat in ["Str", "Dex", "Con", "Int", "Wis", "Cha"]:
            suggestions.append(f"{stat} Save")

        # Filter based on current input
        filtered = [
            app_commands.Choice(name=s, value=s)
            for s in suggestions if current.lower() in s.lower()
        ]

        # Sort: put matches starting with the input first
        filtered.sort(key=lambda c: (not c.name.lower().startswith(current.lower()), c.name))

        return filtered[:25]
