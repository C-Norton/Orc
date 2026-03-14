import discord
from discord import app_commands
from discord.ext import commands
from typing import List
import random
from database import SessionLocal
from models import User, Server, Character, Attack
from dice_roller import roll_dice

def register_attack_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="add_attack", description="Add an attack to your character")
    @app_commands.describe(
        name="Name of the attack (e.g., Longsword)",
        hit_mod="Bonus to hit (e.g., 5)",
        damage_formula="Damage dice (e.g., 1d8+3)"
    )
    async def add_attack(interaction: discord.Interaction, name: str, hit_mod: int, damage_formula: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            
            if not char:
                await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
                return

            # Check if attack already exists
            attack = db.query(Attack).filter_by(character_id=char.id, name=name).first()
            if attack:
                attack.hit_modifier = hit_mod
                attack.damage_formula = damage_formula
                msg = f"Updated attack **{name}** for **{char.name}**."
            else:
                attack = Attack(character_id=char.id, name=name, hit_modifier=hit_mod, damage_formula=damage_formula)
                db.add(attack)
                msg = f"Added attack **{name}** to **{char.name}**."
            
            db.commit()
            await interaction.response.send_message(msg)
        finally:
            db.close()

    @bot.tree.command(name="attack", description="Perform an attack roll")
    @app_commands.describe(attack_name="The name of the attack to use")
    async def attack(interaction: discord.Interaction, attack_name: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            
            if not char:
                await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
                return

            attack_obj = db.query(Attack).filter_by(character_id=char.id, name=attack_name).first()
            if not attack_obj:
                # Try case-insensitive match
                attack_obj = next((a for a in char.attacks if a.name.lower() == attack_name.lower()), None)
                if not attack_obj:
                    await interaction.response.send_message(f"Attack '**{attack_name}**' not found.", ephemeral=True)
                    return

            # Hit roll
            d20_roll = random.randint(1, 20)
            hit_total = d20_roll + attack_obj.hit_modifier
            
            # Damage roll
            try:
                rolls, modifier, damage_total = roll_dice(attack_obj.damage_formula)
                rolls_str = ", ".join(map(str, rolls))
                mod_str = f" {modifier:+d}" if modifier != 0 else ""
                damage_detail = f"({rolls_str}){mod_str}"
            except ValueError as e:
                await interaction.response.send_message(f"❌ Error in damage formula: {str(e)}", ephemeral=True)
                return

            response = f"⚔️ **{char.name}** attacks with **{attack_obj.name}**!\n"
            response += f"**To Hit**: `d20({d20_roll}) + {attack_obj.hit_modifier}` = **{hit_total}**\n"
            response += f"**Damage**: `{attack_obj.damage_formula}` -> `{damage_detail}` = **{damage_total}**"
            
            await interaction.response.send_message(response)
        finally:
            db.close()

    @attack.autocomplete("attack_name")
    async def attack_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            
            if not char or not char.attacks:
                return []
                
            return [
                app_commands.Choice(name=a.name, value=a.name)
                for a in char.attacks if current.lower() in a.name.lower()
            ][:25]
        finally:
            db.close()

    @bot.tree.command(name="attacks", description="List all of your character's attacks")
    async def attacks_list(interaction: discord.Interaction) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            
            if not char:
                await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
                return

            if not char.attacks:
                await interaction.response.send_message(f"**{char.name}** has no attacks saved. Use `/add_attack` to add some!")
                return

            embed = discord.Embed(title=f"Attacks for {char.name}", color=discord.Color.red())
            for attack_obj in char.attacks:
                embed.add_field(
                    name=attack_obj.name,
                    value=f"To Hit: `+{attack_obj.hit_modifier}` | Damage: `{attack_obj.damage_formula}`",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed)
        finally:
            db.close()
