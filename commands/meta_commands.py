import discord
from discord.ext import commands

def register_meta_commands(bot: commands.Bot) -> None:
    @bot.tree.command(name="help", description="Show help for all bot commands")
    async def help_command(interaction: discord.Interaction) -> None:
        """Show help for all bot commands and the party system."""
        embed = discord.Embed(
            title="🎲 Orc Help",
            description="Your D&D 5e companion for characters, rolls, and parties.",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="👤 Character Management",
            value=(
                "**/create_character <name>**: Create a new character for this server.\n"
                "**/characters**: View all your characters in this server.\n"
                "**/view_character**: See your active character's stats, skills, and saving throws.\n"
                "**/switch_character <name>**: Change which character is currently active.\n"
                "**/delete_character <name>**: Permanently delete one of your characters.\n"
                "**/set_level <level>**: Set your active character's level (1-20).\n"
                "**/set_stats**: Set your active character's 6 core ability scores.\n"
                "**/set_saving_throws**: Mark which saves your active character is proficient in.\n"
                "**/set_skill <skill> <status>**: Set proficiency for your active character."
            ),
            inline=False
        )

        embed.add_field(
            name="⚔️ Combat",
            value=(
                "**/add_attack <name> <hit_mod> <damage>**: Save an attack (e.g., `/add_attack Longsword 5 1d8+3`).\n"
                "**/attacks**: List all your saved attacks.\n"
                "**/attack <name>**: Roll a to-hit and damage roll for a saved attack."
            ),
            inline=False
        )

        embed.add_field(
            name="🎲 Rolling",
            value=(
                "**/roll <notation>**: Roll anything! Use skill names (e.g., `perception`), saves (e.g., `wis save`), or dice (e.g., `1d20+5`)."
            ),
            inline=False
        )

        embed.add_field(
            name="👥 Parties & GM Tools",
            value=(
                "**/create_party <name>**: Create a new group of characters.\n"
                "**/party_add <party> <character>**: Add a character to a party (GM only).\n"
                "**/active_party <name>**: Set your current active party for quick rolling.\n"
                "**/rollas <member> <notation>**: Roll as a member of your active party.\n"
                "**/partyroll <notation>**: Roll for every member of your active party at once (e.g., `/partyroll perception`)."
            ),
            inline=False
        )

        embed.set_footer(text="Tip: Use autocomplete for character, party, and skill names!")
        
        await interaction.response.send_message(embed=embed)
