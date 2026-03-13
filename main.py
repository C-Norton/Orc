import os
import discord
from discord.ext import commands
from discord import app_commands
import dotenv
import random
from dice_roller import roll_dice
from database import SessionLocal
from models import User, Server, Character, CharacterSkill, Attack, Party, user_server_association
from sqlalchemy import update, select, delete
from enums.skill_proficiency_status import SkillProficiencyStatus

# Load environment variables
dotenv.load_dotenv()
TOKEN = os.getenv('DISCORD_API_TOKEN')

# Define bot intents
intents = discord.Intents.default()
intents.message_content = True

SKILL_TO_STAT = {
    "Acrobatics": "dexterity",
    "Animal Handling": "wisdom",
    "Arcana": "intelligence",
    "Athletics": "strength",
    "Deception": "charisma",
    "History": "intelligence",
    "Insight": "wisdom",
    "Intimidation": "charisma",
    "Investigation": "intelligence",
    "Medicine": "wisdom",
    "Nature": "intelligence",
    "Perception": "wisdom",
    "Performance": "charisma",
    "Persuasion": "charisma",
    "Religion": "intelligence",
    "Sleight of Hand": "dexterity",
    "Stealth": "dexterity",
    "Survival": "wisdom"
}

STAT_NAMES = {
    "strength": "strength",
    "dexterity": "dexterity",
    "constitution": "constitution",
    "intelligence": "intelligence",
    "wisdom": "wisdom",
    "charisma": "charisma",
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma"
}

def get_proficiency_bonus(level):
    return (level - 1) // 4 + 2

def get_stat_modifier(score):
    return (score - 10) // 2

class DnDBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        """Called by the bot to perform asynchronous setup tasks."""
        # This syncs the slash commands globally (or to specific guilds if needed)
        # Note: Global sync can take up to an hour to propagate.
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_guild_join(self, guild):
        """Update the database when the bot joins a new server."""
        db = SessionLocal()
        try:
            server = db.query(Server).filter_by(discord_id=str(guild.id)).first()
            if not server:
                server = Server(discord_id=str(guild.id), name=guild.name)
                db.add(server)
                db.commit()
                print(f"Added new server: {guild.name} ({guild.id})")
        finally:
            db.close()

bot = DnDBot()

@bot.tree.command(name="help", description="Show help for all bot commands")
async def help_command(interaction: discord.Interaction):
    """Show help for all bot commands and the party system."""
    embed = discord.Embed(
        title="🎲 Kaz-bot Help",
        description="Your D&D 5e companion for characters, rolls, and parties.",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="👤 Character Management",
        value=(
            "**/create_character <name>**: Create a new character for this server.\n"
            "**/view_character**: See your stats, skills, and saving throws.\n"
            "**/switch_character <name>**: Change which character is currently active.\n"
            "**/set_level <level>**: Set your character's level (1-20).\n"
            "**/set_stats**: Set your 6 core ability scores.\n"
            "**/set_saving_throws**: Mark which saves you are proficient in.\n"
            "**/set_skill <skill> <status>**: Set proficiency (Not Proficient, Proficient, Expertise, or Jack of All Trades)."
        ),
        inline=False
    )

    embed.add_field(
        name="⚔️ Combat & Attacks",
        value=(
            "**/add_attack <name> <hit_mod> <damage>**: Add/update an attack (e.g., `Longsword`, `5`, `1d8+3`).\n"
            "**/attack <name>**: Roll to hit and damage with a saved attack.\n"
            "**/attacks**: List all saved attacks for your character."
        ),
        inline=False
    )

    embed.add_field(
        name="🎲 Rolling",
        value=(
            "**/roll <notation>**: Roll dice, skills, stats, or saves.\n"
            "Examples: `1d20+5`, `2d6`, `insight`, `str`, `dex save`."
        ),
        inline=False
    )

    embed.add_field(
        name="👥 Party System",
        value=(
            "**What is a Party?** A group of characters in the same server. Each party has a **GM** (the creator).\n"
            "**/create_party <name> <members>**: Create a party with a comma-separated list of character names.\n"
            "**/party_add <party> <character>**: GM: Add a character to the party.\n"
            "**/party_remove <party> <character>**: GM: Remove a character from the party.\n"
            "**/delete_party <party>**: GM: Delete the party (characters are NOT deleted).\n"
            "**/active_party [name]**: Set or view your current active party for group rolls.\n"
            "**/rollas <member> <notation>**: Roll as a member of your active party.\n"
            "**/partyroll <notation>**: Roll for every member of your active party at once (e.g., `/partyroll perception`)."
        ),
        inline=False
    )

    embed.set_footer(text="Tip: Use autocomplete for character, party, and skill names!")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roll", description="Roll a d20 skill check, Save, or standard dice notation.")
@app_commands.describe(notation="Skill, attribute, save name or dice notation (e.g., 'insight', 'str', 'str save', '1d20+5')")
async def roll(interaction: discord.Interaction, notation: str):
    """Unified roll command for skills, attributes, saves and dice notation."""
    db = SessionLocal()
    try:
        # Normalize notation for matching
        clean_notation = notation.lower().strip()

        # Check if it's a saving throw (handles "str save", "strength save", "str_save", "strength_save")
        is_save = False
        save_stat = None
        if "save" in clean_notation:
            stat_part = clean_notation.replace("save", "").replace("_", "").strip()
            if stat_part in STAT_NAMES:
                is_save = True
                save_stat = STAT_NAMES[stat_part]

        # Check if the notation matches a skill name (case-insensitive)
        matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean_notation), None)

        # Check if it's a flat attribute roll
        matched_stat = STAT_NAMES.get(clean_notation) if not is_save and not matched_skill else None

        if matched_skill or is_save or matched_stat:
            # Character-based roll logic
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

            if not char:
                await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
                return

            response = await perform_roll(char, notation, db)
            await interaction.response.send_message(response)
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

    except ValueError as e:
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ An unexpected error occurred.", ephemeral=True)
        print(f"Unexpected error: {e}")
    finally:
        db.close()

@roll.autocomplete("notation")
async def roll_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for the roll command suggesting skill names, stats, and saves."""
    suggestions = []

    # Add skills
    skills = sorted(SKILL_TO_STAT.keys())
    suggestions.extend([skill for skill in skills])

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



@bot.tree.command(name="create_character", description="Create a new DnD character for this server")
@app_commands.describe(name="The name of your character")
async def create_character(interaction: discord.Interaction, name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        if not user:
            user = User(discord_id=str(interaction.user.id))
            db.add(user)
            db.flush()

        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        if not server:
            server = Server(discord_id=str(interaction.guild_id), name=interaction.guild.name)
            db.add(server)
            db.flush()

        existing_char = db.query(Character).filter_by(user=user, server=server, name=name).first()
        if existing_char:
            await interaction.response.send_message(f"You already have a character named **{name}** in this server.", ephemeral=True)
            return

        # Deactivate all other characters for this user in this server
        db.query(Character).filter_by(user=user, server=server).update({"is_active": False})
        
        new_char = Character(name=name, user=user, server=server, is_active=True)
        db.add(new_char)
        db.commit()
        await interaction.response.send_message(f"Character **{name}** created successfully and set as active!\nNext, set your stats with '/set_stats', your skill proficiencies with 'set_skill', your saving throw proficiencies with '/set_saving_throws'\n View your character at any time with '/view_character', and switch with '/switch_character'")
    finally:
        db.close()

@bot.tree.command(name="set_stats", description="Set your character's core stats")
@app_commands.describe(
    strength="Strength score (1-30)",
    dexterity="Dexterity score (1-30)",
    constitution="Constitution score (1-30)",
    intelligence="Intelligence score (1-30)",
    wisdom="Wisdom score (1-30)",
    charisma="Charisma score (1-30)"
)
async def set_stats(
    interaction: discord.Interaction,
    strength: int, dexterity: int, constitution: int,
    intelligence: int, wisdom: int, charisma: int
):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

        if not char:
            await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
            return

        char.strength = strength
        char.dexterity = dexterity
        char.constitution = constitution
        char.intelligence = intelligence
        char.wisdom = wisdom
        char.charisma = charisma

        db.commit()
        await interaction.response.send_message(f"Stats updated for **{char.name}**!")
    finally:
        db.close()

@bot.tree.command(name="set_saving_throws", description="Set your character's saving throw proficiencies")
@app_commands.describe(
    st_str="Proficient in Strength saving throws?",
    st_dex="Proficient in Dexterity saving throws?",
    st_con="Proficient in Constitution saving throws?",
    st_int="Proficient in Intelligence saving throws?",
    st_wis="Proficient in Wisdom saving throws?",
    st_cha="Proficient in Charisma saving throws?"
)
async def set_saving_throws(
    interaction: discord.Interaction,
    st_str: bool = False, st_dex: bool = False, st_con: bool = False,
    st_int: bool = False, st_wis: bool = False, st_cha: bool = False
):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

        if not char:
            await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
            return

        char.st_prof_strength = st_str
        char.st_prof_dexterity = st_dex
        char.st_prof_constitution = st_con
        char.st_prof_intelligence = st_int
        char.st_prof_wisdom = st_wis
        char.st_prof_charisma = st_cha

        db.commit()
        await interaction.response.send_message(f"Saving throw proficiencies updated for **{char.name}**!")
    finally:
        db.close()

@bot.tree.command(name="view_character", description="View your character's stats, skills, and saving throws")
async def view_character(interaction: discord.Interaction):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()

        if not char:
            await interaction.response.send_message("You don't have a character in this server. Use `/create_character` first.", ephemeral=True)
            return

        prof_bonus = get_proficiency_bonus(char.level)

        # Build the message
        embed = discord.Embed(title=f"Character: {char.name}", color=discord.Color.blue())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Level", value=str(char.level), inline=True)
        embed.add_field(name="Proficiency Bonus", value=f"+{prof_bonus}", inline=True)

        # Stats and Saving Throws
        stats_text = ""
        saves_text = ""
        for stat_code, stat_name in [("str", "strength"), ("dex", "dexterity"), ("con", "constitution"),
                                     ("int", "intelligence"), ("wis", "wisdom"), ("cha", "charisma")]:
            score = getattr(char, stat_name)
            mod = get_stat_modifier(score)
            stats_text += f"**{stat_code.upper()}**: {score} ({mod:+d})\n"

            # Saving Throws
            is_prof = getattr(char, f"st_prof_{stat_name}")
            save_mod = mod + (prof_bonus if is_prof else 0)
            prof_mark = "●" if is_prof else "○"
            saves_text += f"{prof_mark} **{stat_code.upper()}**: {save_mod:+d}\n"

        embed.add_field(name="Core Stats", value=stats_text, inline=True)
        embed.add_field(name="Saving Throws", value=saves_text, inline=True)

        # Skills
        skills_by_stat = {}
        for skill_name, stat_name in SKILL_TO_STAT.items():
            if stat_name not in skills_by_stat:
                skills_by_stat[stat_name] = []
            skills_by_stat[stat_name].append(skill_name)

        # Sort skills by name
        sorted_skills = sorted(SKILL_TO_STAT.keys())

        skills_text = ""
        for skill_name in sorted_skills:
            stat_name = SKILL_TO_STAT[skill_name]
            stat_mod = get_stat_modifier(getattr(char, stat_name))

            char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=skill_name).first()
            prof_status = char_skill.proficiency if char_skill else SkillProficiencyStatus.NOT_PROFICIENT

            skill_mod = stat_mod
            prof_mark = "○"
            if prof_status == SkillProficiencyStatus.PROFICIENT:
                skill_mod += prof_bonus
                prof_mark = "●"
            elif prof_status == SkillProficiencyStatus.EXPERTISE:
                skill_mod += 2 * prof_bonus
                prof_mark = "◉"
            elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
                skill_mod += prof_bonus // 2
                prof_mark = "◐"

            skills_text += f"{prof_mark} {skill_name}: {skill_mod:+d}\n"

        # Split skills into two columns if needed, or just one long one.
        # Discord embed fields have 1024 char limit. 18 skills with ~20 chars each is ~360 chars.
        # We'll split them into two fields for better layout.
        mid = len(sorted_skills) // 2
        embed.add_field(name="Skills (A-I)", value=skills_text.splitlines()[:mid+1] and "\n".join(skills_text.splitlines()[:mid+1]), inline=False)
        embed.add_field(name="Skills (L-Z)", value=skills_text.splitlines()[mid+1:] and "\n".join(skills_text.splitlines()[mid+1:]), inline=False)

        embed.set_footer(text="● Proficient | ◉ Expertise | ◐ Jack of All Trades | ○ Not Proficient")

        # Attacks
        if char.attacks:
            attacks_text = ""
            for attack in char.attacks:
                attacks_text += f"**{attack.name}**: {attack.hit_modifier:+d} to hit, {attack.damage_formula} damage\n"
            embed.add_field(name="Attacks", value=attacks_text, inline=False)

        await interaction.response.send_message(embed=embed)
    finally:
        db.close()

@bot.tree.command(name="switch_character", description="Switch your active character in this server")
@app_commands.describe(name="The name of the character to switch to")
async def switch_character(interaction: discord.Interaction, name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        
        if not user or not server:
            await interaction.response.send_message("You don't have any characters in this server.", ephemeral=True)
            return

        char = db.query(Character).filter_by(user=user, server=server, name=name).first()
        if not char:
            await interaction.response.send_message(f"Character **{name}** not found.", ephemeral=True)
            return

        if char.is_active:
            await interaction.response.send_message(f"**{char.name}** is already your active character.", ephemeral=True)
            return

        # Deactivate all other characters
        db.query(Character).filter_by(user=user, server=server).update({"is_active": False})
        
        # Activate chosen character
        char.is_active = True
        db.commit()
        await interaction.response.send_message(f"Switched to character **{char.name}**!")
    finally:
        db.close()

@switch_character.autocomplete("name")
async def switch_character_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        
        if not user or not server:
            return []
            
        characters = db.query(Character).filter_by(user=user, server=server).all()
        return [
            app_commands.Choice(name=c.name, value=c.name)
            for c in characters if current.lower() in c.name.lower()
        ][:25]
    finally:
        db.close()

@bot.tree.command(name="set_level", description="Set your character's level")
@app_commands.describe(level="Your character's level (1-20)")
async def set_level(interaction: discord.Interaction, level: int):
    if not (1 <= level <= 20):
        await interaction.response.send_message("Level must be between 1 and 20.", ephemeral=True)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
        
        if not char:
            await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
            return

        char.level = level
        db.commit()
        prof_bonus = get_proficiency_bonus(level)
        await interaction.response.send_message(f"**{char.name}** is now level {level} (Proficiency Bonus: +{prof_bonus}).")
    finally:
        db.close()

@bot.tree.command(name="set_skill", description="Set your proficiency in a specific skill")
@app_commands.describe(
    skill="The skill to update",
    status="Proficiency level"
)
@app_commands.choices(skill=[
    app_commands.Choice(name=skill, value=skill) for skill in sorted(SKILL_TO_STAT.keys())
], status=[
    app_commands.Choice(name="Not Proficient", value="not_proficient"),
    app_commands.Choice(name="Proficient", value="proficient"),
    app_commands.Choice(name="Expertise", value="expertise"),
    app_commands.Choice(name="Jack of All Trades", value="jack_of_all_trades")
])
async def set_skill(interaction: discord.Interaction, skill: str, status: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
        
        if not char:
            await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
            return

        # Find or create skill entry
        char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=skill).first()
        if not char_skill:
            char_skill = CharacterSkill(character_id=char.id, skill_name=skill)
            db.add(char_skill)
        
        char_skill.proficiency = SkillProficiencyStatus(status)
        db.commit()
        await interaction.response.send_message(f"Updated **{skill}** for **{char.name}** to {status.replace('_', ' ').title()}.")
    finally:
        db.close()

@bot.tree.command(name="add_attack", description="Add an attack to your character")
@app_commands.describe(
    name="Name of the attack (e.g., Longsword)",
    hit_mod="Bonus to hit (e.g., 5)",
    damage_formula="Damage dice (e.g., 1d8+3)"
)
async def add_attack(interaction: discord.Interaction, name: str, hit_mod: int, damage_formula: str):
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
async def attack(interaction: discord.Interaction, attack_name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
        
        if not char:
            await interaction.response.send_message("You don't have a character in this server.", ephemeral=True)
            return

        attack = db.query(Attack).filter_by(character_id=char.id, name=attack_name).first()
        if not attack:
            # Try case-insensitive match
            attack = next((a for a in char.attacks if a.name.lower() == attack_name.lower()), None)
            if not attack:
                await interaction.response.send_message(f"Attack '**{attack_name}**' not found.", ephemeral=True)
                return

        # Hit roll
        d20_roll = random.randint(1, 20)
        hit_total = d20_roll + attack.hit_modifier
        
        # Damage roll
        try:
            rolls, modifier, damage_total = roll_dice(attack.damage_formula)
            rolls_str = ", ".join(map(str, rolls))
            mod_str = f" {modifier:+d}" if modifier != 0 else ""
            damage_detail = f"({rolls_str}){mod_str}"
        except ValueError as e:
            await interaction.response.send_message(f"❌ Error in damage formula: {str(e)}", ephemeral=True)
            return

        response = f"⚔️ **{char.name}** attacks with **{attack.name}**!\n"
        response += f"**To Hit**: `d20({d20_roll}) + {attack.hit_modifier}` = **{hit_total}**\n"
        response += f"**Damage**: `{attack.damage_formula}` -> `{damage_detail}` = **{damage_total}**"
        
        await interaction.response.send_message(response)
    finally:
        db.close()

@attack.autocomplete("attack_name")
async def attack_autocomplete(interaction: discord.Interaction, current: str):
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
async def attacks_list(interaction: discord.Interaction):
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
        for attack in char.attacks:
            embed.add_field(
                name=attack.name,
                value=f"**Hit**: +{attack.hit_modifier}\n**Damage**: {attack.damage_formula}",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed)
    finally:
        db.close()

# --- Party Commands ---

@bot.tree.command(name="create_party", description="Create a new party with a list of characters")
@app_commands.describe(
    party_name="The name of the new party",
    characters_list="Comma-separated list of character names to include in the party"
)
async def create_party(interaction: discord.Interaction, party_name: str, characters_list: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

        if not user or not server:
            await interaction.response.send_message("User or Server not initialized.", ephemeral=True)
            return

        existing_party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
        if existing_party:
            await interaction.response.send_message(f"A party named '**{party_name}**' already exists in this server.", ephemeral=True)
            return

        new_party = Party(name=party_name, gm=user, server=server)
        
        # Parse characters
        char_names = [name.strip() for name in characters_list.split(',')]
        found_chars = []
        not_found = []
        for name in char_names:
            char = db.query(Character).filter_by(name=name, server_id=server.id).first()
            if char:
                found_chars.append(char)
            else:
                not_found.append(name)

        new_party.characters = found_chars
        db.add(new_party)
        db.commit()

        # Set as active party for the creator
        stmt = update(user_server_association).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id
        ).values(active_party_id=new_party.id)
        db.execute(stmt)
        db.commit()

        msg = f"Party '**{party_name}**' created successfully with {len(found_chars)} characters!"
        if not_found:
            msg += f"\nCharacters not found: {', '.join(not_found)}"
        
        await interaction.response.send_message(msg)
    finally:
        db.close()

@bot.tree.command(name="party_add", description="Add a character to a party")
@app_commands.describe(
    party_name="The name of the party",
    character_name="The name of the character to add"
)
async def party_add(interaction: discord.Interaction, party_name: str, character_name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

        if not party:
            await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
            return

        if party.gm_id != user.id:
            await interaction.response.send_message("Only the GM of the party can add members.", ephemeral=True)
            return

        char = db.query(Character).filter_by(name=character_name, server_id=server.id).first()
        if not char:
            await interaction.response.send_message(f"Character '**{character_name}**' not found.", ephemeral=True)
            return

        if char in party.characters:
            await interaction.response.send_message(f"**{character_name}** is already in the party.", ephemeral=True)
            return

        party.characters.append(char)
        db.commit()
        await interaction.response.send_message(f"Added **{character_name}** to party '**{party_name}**'.")
    finally:
        db.close()

@party_add.autocomplete("party_name")
async def party_name_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    try:
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        if not server: return []
        parties = db.query(Party).filter(Party.server_id == server.id, Party.name.ilike(f"%{current}%")).all()
        return [app_commands.Choice(name=p.name, value=p.name) for p in parties][:25]
    finally:
        db.close()

@party_add.autocomplete("character_name")
async def character_name_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    try:
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        if not server: return []
        chars = db.query(Character).filter(Character.server_id == server.id, Character.name.ilike(f"%{current}%")).all()
        return [app_commands.Choice(name=c.name, value=c.name) for c in chars][:25]
    finally:
        db.close()

@bot.tree.command(name="party_remove", description="Remove a character from a party")
@app_commands.describe(
    party_name="The name of the party",
    character_name="The name of the character to remove"
)
async def party_remove(interaction: discord.Interaction, party_name: str, character_name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

        if not party:
            await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
            return

        if party.gm_id != user.id:
            await interaction.response.send_message("Only the GM of the party can remove members.", ephemeral=True)
            return

        char = next((c for c in party.characters if c.name.lower() == character_name.lower()), None)
        if not char:
            await interaction.response.send_message(f"Character '**{character_name}**' not found in this party.", ephemeral=True)
            return

        party.characters.remove(char)
        db.commit()
        await interaction.response.send_message(f"Removed **{character_name}** from party '**{party_name}**'.")
    finally:
        db.close()

@party_remove.autocomplete("party_name")
async def party_remove_party_autocomplete(interaction: discord.Interaction, current: str):
    return await party_name_autocomplete(interaction, current)

@party_remove.autocomplete("character_name")
async def party_remove_character_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    try:
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        party_name = interaction.namespace.party_name
        if not server or not party_name: return []
        party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
        if not party: return []
        return [app_commands.Choice(name=c.name, value=c.name) for c in party.characters if current.lower() in c.name.lower()][:25]
    finally:
        db.close()

@bot.tree.command(name="active_party", description="Set or view your active party")
@app_commands.describe(party_name="The name of the party to set as active (optional)")
async def active_party(interaction: discord.Interaction, party_name: str = None):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

        if party_name:
            party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
            if not party:
                await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
                return

            stmt = update(user_server_association).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            ).values(active_party_id=party.id)
            db.execute(stmt)
            db.commit()
            await interaction.response.send_message(f"Your active party is now '**{party.name}**'.")
        else:
            # View active party
            stmt = select(user_server_association.c.active_party_id).where(
                user_server_association.c.user_id == user.id,
                user_server_association.c.server_id == server.id
            )
            result = db.execute(stmt).first()
            if not result or not result.active_party_id:
                await interaction.response.send_message("You don't have an active party set. Use `/active_party <name>` to set one.")
                return

            party = db.get(Party, result.active_party_id)
            if not party:
                await interaction.response.send_message("Active party not found in database.")
                return

            member_list = "\n".join([f"- **{c.name}** (<@{c.user.discord_id}>)" for c in party.characters])
            await interaction.response.send_message(f"Your active party: **{party.name}** (GM: <@{party.gm.discord_id}>)\nMembers:\n{member_list}")
    finally:
        db.close()

@active_party.autocomplete("party_name")
async def active_party_autocomplete(interaction: discord.Interaction, current: str):
    return await party_name_autocomplete(interaction, current)

@bot.tree.command(name="rollas", description="Make a roll as a party member")
@app_commands.describe(
    member_name="The name of the party member",
    notation="Skill, attribute, save name or dice notation"
)
async def rollas(interaction: discord.Interaction, member_name: str, notation: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        
        # Get active party
        stmt = select(user_server_association.c.active_party_id).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id
        )
        result = db.execute(stmt).first()
        if not result or not result.active_party_id:
            await interaction.response.send_message("You don't have an active party set. Use `/active_party <name>`.", ephemeral=True)
            return

        party = db.get(Party, result.active_party_id)
        char = next((c for c in party.characters if c.name.lower() == member_name.lower()), None)
        
        if not char:
            await interaction.response.send_message(f"Character '**{member_name}**' is not in your active party.", ephemeral=True)
            return

        # Roll logic (shared with /roll)
        response = await perform_roll(char, notation, db)
        await interaction.response.send_message(response)
    finally:
        db.close()

@rollas.autocomplete("member_name")
async def rollas_member_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        stmt = select(user_server_association.c.active_party_id).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id
        )
        result = db.execute(stmt).first()
        if not result or not result.active_party_id: return []
        party = db.get(Party, result.active_party_id)
        if not party: return []
        return [app_commands.Choice(name=c.name, value=c.name) for c in party.characters if current.lower() in c.name.lower()][:25]
    finally:
        db.close()

@bot.tree.command(name="partyroll", description="Make a roll for each party member")
@app_commands.describe(notation="Skill, attribute, save name or dice notation")
async def partyroll(interaction: discord.Interaction, notation: str):
    await interaction.response.defer()
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        
        # Get active party
        stmt = select(user_server_association.c.active_party_id).where(
            user_server_association.c.user_id == user.id,
            user_server_association.c.server_id == server.id
        )
        result = db.execute(stmt).first()
        if not result or not result.active_party_id:
            await interaction.followup.send("You don't have an active party set. Use `/active_party <name>`.", ephemeral=True)
            return

        party = db.get(Party, result.active_party_id)
        if not party.characters:
            await interaction.followup.send("Your active party has no characters.", ephemeral=True)
            return

        responses = []
        for char in party.characters:
            res = await perform_roll(char, notation, db)
            responses.append(res)
        
        full_response = f"🎲 **Party Roll for '{party.name}'**: `{notation}`\n\n" + "\n\n".join(responses)
        # Handle message length limit
        if len(full_response) > 2000:
            parts = [full_response[i:i+1900] for i in range(0, len(full_response), 1900)]
            for i, part in enumerate(parts):
                if i == 0:
                    await interaction.followup.send(part)
                else:
                    await interaction.followup.send(f"(cont...)\n{part}")
        else:
            await interaction.followup.send(full_response)
    finally:
        db.close()

@bot.tree.command(name="delete_party", description="Delete a party")
@app_commands.describe(party_name="The name of the party to delete")
async def delete_party(interaction: discord.Interaction, party_name: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
        party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()

        if not party:
            await interaction.response.send_message(f"Party '**{party_name}**' not found.", ephemeral=True)
            return

        if party.gm_id != user.id:
            await interaction.response.send_message("Only the GM of the party can delete it.", ephemeral=True)
            return

        # Clear active_party_id for anyone who had it set
        stmt = update(user_server_association).where(
            user_server_association.c.active_party_id == party.id
        ).values(active_party_id=None)
        db.execute(stmt)

        db.delete(party)
        db.commit()
        await interaction.response.send_message(f"Party '**{party_name}**' deleted successfully.")
    finally:
        db.close()

@delete_party.autocomplete("party_name")
async def delete_party_autocomplete(interaction: discord.Interaction, current: str):
    return await party_name_autocomplete(interaction, current)

async def perform_roll(char, notation, db):
    """Shared roll logic extracted from /roll."""
    clean_notation = notation.lower().strip()
    is_save = False
    save_stat = None
    if "save" in clean_notation:
        stat_part = clean_notation.replace("save", "").replace("_", "").strip()
        if stat_part in STAT_NAMES:
            is_save = True
            save_stat = STAT_NAMES[stat_part]

    matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean_notation), None)
    matched_stat = STAT_NAMES.get(clean_notation) if not is_save and not matched_skill else None

    if matched_skill or is_save or matched_stat:
        prof_bonus = get_proficiency_bonus(char.level)
        d20_roll = random.randint(1, 20)

        if matched_skill:
            skill = matched_skill
            stat_name = SKILL_TO_STAT[skill]
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)

            char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=skill).first()
            prof_status = char_skill.proficiency if char_skill else SkillProficiencyStatus.NOT_PROFICIENT

            skill_mod = stat_mod
            if prof_status == SkillProficiencyStatus.PROFICIENT:
                skill_mod += prof_bonus
            elif prof_status == SkillProficiencyStatus.EXPERTISE:
                skill_mod += 2 * prof_bonus
            elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
                skill_mod += prof_bonus // 2

            total = d20_roll + skill_mod
            return f"**{char.name}**: {skill} ({stat_name.title()}) `d20({d20_roll}) + {skill_mod}` = **{total}**"

        elif is_save:
            stat_name = save_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            is_proficient = getattr(char, f"st_prof_{stat_name}")
            save_mod = stat_mod + (prof_bonus if is_proficient else 0)
            total = d20_roll + save_mod
            return f"**{char.name}**: {stat_name.title()} Save `d20({d20_roll}) + {save_mod}` = **{total}**"

        else: # matched_stat
            stat_name = matched_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            total = d20_roll + stat_mod
            return f"**{char.name}**: {stat_name.title()} Check `d20({d20_roll}) + {stat_mod}` = **{total}**"
    else:
        try:
            rolls, modifier, total = roll_dice(notation)
            rolls_str = ", ".join(map(str, rolls))
            mod_str = f" {modifier:+d}" if modifier != 0 else ""
            return f"**{char.name}**: `{notation}` ({rolls_str}){mod_str} = **{total}**"
        except ValueError as e:
            return f"**{char.name}**: ❌ Error: {str(e)}"

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_API_TOKEN not found in .env file.")
