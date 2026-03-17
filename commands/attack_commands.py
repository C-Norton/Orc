import discord
from discord import app_commands
from discord.ext import commands
from typing import List
import random
from database import SessionLocal
from models import User, Server, Character, Attack
from dice_roller import roll_dice
from utils.limits import MAX_ATTACKS_PER_CHARACTER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def register_attack_commands(bot: commands.Bot) -> None:
    """Register the /attack command group (add, roll, list)."""
    attack_group = app_commands.Group(
        name="attack", description="Manage and roll attacks for your active character"
    )

    @attack_group.command(name="add", description="Add or update an attack on your character")
    @app_commands.describe(
        name="Name of the attack (e.g., Longsword)",
        hit_mod="Bonus to hit (e.g., 5)",
        damage_formula="Damage dice (e.g., 1d8+3)",
    )
    async def attack_add(
        interaction: discord.Interaction, name: str, hit_mod: int, damage_formula: str
    ) -> None:
        logger.debug(
            f"Command /attack add called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with name: {name}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            roll_dice(damage_formula)  # raises ValueError on invalid formula

            if not char:
                await interaction.response.send_message(Strings.CHARACTER_NOT_FOUND, ephemeral=True)
                return

            attack = db.query(Attack).filter_by(character_id=char.id, name=name).first()
            if attack:
                attack.hit_modifier = hit_mod
                attack.damage_formula = damage_formula
                msg = Strings.ATTACK_UPDATED.format(attack_name=name, char_name=char.name)
            else:
                attack_count = db.query(Attack).filter_by(character_id=char.id).count()
                if attack_count >= MAX_ATTACKS_PER_CHARACTER:
                    await interaction.response.send_message(
                        Strings.ERROR_LIMIT_ATTACKS.format(
                            char_name=char.name, limit=MAX_ATTACKS_PER_CHARACTER
                        ),
                        ephemeral=True,
                    )
                    return
                attack = Attack(
                    character_id=char.id,
                    name=name,
                    hit_modifier=hit_mod,
                    damage_formula=damage_formula,
                )
                db.add(attack)
                msg = Strings.ATTACK_ADDED.format(attack_name=name, char_name=char.name)

            db.commit()
            logger.info(f"/attack add completed for user {interaction.user.id}: {msg}")
            await interaction.response.send_message(msg)
        except ValueError as e:
            logger.error(f"Error adding attack for user {interaction.user.id}: {e}")
            await interaction.response.send_message(f"Error adding attack: {e}.", ephemeral=True)
        finally:
            db.close()

    @attack_group.command(name="roll", description="Perform an attack roll")
    @app_commands.describe(attack_name="The name of the attack to use")
    async def attack_roll(interaction: discord.Interaction, attack_name: str) -> None:
        logger.debug(
            f"Command /attack roll called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with attack_name: {attack_name}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(Strings.CHARACTER_NOT_FOUND, ephemeral=True)
                return

            attack_obj = db.query(Attack).filter_by(character_id=char.id, name=attack_name).first()
            if not attack_obj:
                attack_obj = next(
                    (a for a in char.attacks if a.name.lower() == attack_name.lower()), None
                )
                if not attack_obj:
                    await interaction.response.send_message(
                        Strings.ATTACK_NOT_FOUND.format(attack_name=attack_name), ephemeral=True
                    )
                    return

            d20_roll = random.randint(1, 20)
            hit_total = d20_roll + attack_obj.hit_modifier

            try:
                rolls, modifier, damage_total = roll_dice(attack_obj.damage_formula)
                rolls_str = ", ".join(map(str, rolls))
                mod_str = f" {modifier:+d}" if modifier != 0 else ""
                damage_detail = f"({rolls_str}){mod_str}"
            except ValueError as e:
                logger.warning(
                    f"ValueError in /attack roll (damage formula: {attack_obj.damage_formula}): {e}"
                )
                await interaction.response.send_message(
                    f"❌ Error in damage formula: {str(e)}", ephemeral=True
                )
                return

            response = Strings.ATTACK_ROLL_MSG.format(
                char_name=char.name,
                attack_obj_name=attack_obj.name,
                d20_roll=d20_roll,
                hit_modifier=attack_obj.hit_modifier,
                hit_total=hit_total,
                damage_formula=attack_obj.damage_formula,
                damage_detail=damage_detail,
                damage_total=damage_total,
            )

            await interaction.response.send_message(response)
            logger.info(
                f"/attack roll completed for user {interaction.user.id}: "
                f"{char.name} used {attack_obj.name}"
            )
        finally:
            db.close()

    @attack_roll.autocomplete("attack_name")
    async def attack_roll_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Suggest attacks belonging to the user's active character."""
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char or not char.attacks:
                return []

            return [
                app_commands.Choice(name=a.name, value=a.name)
                for a in char.attacks
                if current.lower() in a.name.lower()
            ][:25]
        finally:
            db.close()

    @attack_group.command(name="list", description="List all attacks for your active character")
    async def attack_list(interaction: discord.Interaction) -> None:
        logger.debug(
            f"Command /attack list called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(Strings.CHARACTER_NOT_FOUND, ephemeral=True)
                return

            if not char.attacks:
                await interaction.response.send_message(
                    Strings.ATTACK_NO_ATTACKS.format(char_name=char.name)
                )
                return

            embed = discord.Embed(
                title=Strings.ATTACK_LIST_TITLE.format(char_name=char.name),
                color=discord.Color.red(),
            )
            for attack_obj in char.attacks:
                embed.add_field(
                    name=attack_obj.name,
                    value=f"To Hit: `+{attack_obj.hit_modifier}` | Damage: `{attack_obj.damage_formula}`",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)
            logger.info(
                f"/attack list completed for user {interaction.user.id}: "
                f"listed {len(char.attacks)} attacks"
            )
        finally:
            db.close()

    bot.tree.add_command(attack_group)
