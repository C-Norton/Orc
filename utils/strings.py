import random


class Strings:
        # Common
    CHARACTER_NOT_FOUND = (
        "You don't have a character in this server. Use `/character create` first."
    )
    ACTIVE_CHARACTER_NOT_FOUND = "You don't have an active character."
    SERVER_ERROR = "❌ An unexpected error occurred."
    DEVELOPER_NOTIFIED_ERROR = (
        "ORC was unable to respond to your query. "
        "This issue has been logged and forwarded to the developers."
    )

    # Resource limits
    ERROR_LIMIT_CHARACTERS = "You have reached the maximum number of characters ({limit}) across all servers."
    ERROR_LIMIT_GM_PARTIES = (
        "You are already a GM of the maximum number of parties ({limit})."
    )
    ERROR_LIMIT_PARTY_MEMBERS = (
        "This party has reached the maximum number of characters ({limit})."
    )
    ERROR_LIMIT_ATTACKS = (
        "**{char_name}** already has the maximum number of saved attacks ({limit})."
    )
    ERROR_LIMIT_ENEMIES = (
        "This encounter has reached the maximum number of enemies ({limit})."
    )
    ERROR_LIMIT_PARTIES_SERVER = (
        "This server has reached the maximum number of parties ({limit})."
    )

    # Meta Commands
    HELP_TITLE = (
        "Thank you for using ORC - the Opensource Roleplaying Companion bot for D&D 5e"
    )
    HELP_DESCRIPTION = "Check out our shared setting: [Open Source Gaming and Roleplaying environment (OGRE)](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/)"
    HELP_FOOTER = "Tip: Use autocomplete for character, party, skill names, and more!"
    HELP_NOT_YOUR_MENU = (
        "This help menu belongs to someone else. Use `/help` to open your own."
    )
    HELP_TOC_DESCRIPTION = (
        "{description}\n\n"
        "Click a reaction below to see more information about each command category:\n\n"
        "⭐ **QuickStart Guide**\n"
        "👤 **Character Management**\n"
        "⚔️ **Combat**\n"
        "🎲 **Rolling**\n"
        "❤️ **Health & HP**\n"
        "👥 **Parties & GM Tools**\n"
        "🤼 **Encounter & Initiative**\n"
        "💫 **Inspiration Tracking**\n"
        "👨‍🔧 **Credits & Support**\n"
        "🏠 **Back to Home**"
    )

    HELP_CHAR_MGMT_NAME = "👤 Character Management"
    HELP_CHAR_MGMT_VALUE = (
        "**/character create <name> <class> <level>**: Create a new character for this server. Class save proficiencies are set automatically.\n"
        "**/character class_add <class> <level>**: Add or update a class on your active character (for levelling up or multiclassing).\n"
        "**/character class_remove <class>**: Remove a class from your active character.\n"
        "**/character list**: View all your characters in this server.\n"
        "**/character view**: See your active character's stats, skills, and saving throws.\n"
        "**/character switch <name>**: Change which character is currently active.\n"
        "**/character delete <name>**: Permanently delete one of your characters.\n"
        "**/character stats**: Set your active character's 6 core ability scores, and initiative bonus.\n"
        "**/character ac <ac>**: Set your active character's Armor Class (1-30).\n"
        "**/character saves**: Mark which saves your active character is proficient in.\n"
        "**/character skill <skill> <status>**: Set proficiency for your active character."
    )

    HELP_COMBAT_NAME = "⚔️ Combat"
    HELP_COMBAT_VALUE = (
        "**/weapon search <query>**: Search for weapons in the 2024 SRD (via Open5e). Shows up to 5 results.\n"
        "**/weapon add <number>**: Import a weapon from your last `/weapon search` results. "
        "Automatically computes the to-hit modifier from your character's stats.\n"
        "**/attack add <name> <hit_mod> <damage>**: Manually save an attack (e.g., `/attack add Longsword 5 1d8+3`).\n"
        "**/attack list**: List all your saved attacks.\n"
        "**/attack roll <name> [target]**: Roll a to-hit and damage roll for a saved attack. "
        "In an active encounter, pass `target` as the enemy's position number to resolve the hit "
        "against their AC and automatically update their HP.\n"
    )

    HELP_ROLLING_NAME = "🎲 Rolling"
    HELP_ROLLING_VALUE = (
        "**/roll <notation>**: Roll anything! Use skill names (e.g., `perception`), saves (e.g., `wis save`), or dice (e.g., `1d20+5`).\n"
        "**/roll death save**: Roll a death saving throw (autocomplete-only; only shown when your character is at 0 HP). "
        "3 successes stabilizes; 3 failures slays. Nat 20 behaviour is configurable per party.\n"
        "**/gmroll <notation>**: Roll secretly — you see the result as a message viewable only by you in the channel and every GM of your active character's parties "
        "receives a direct message with the full result. No public message is posted. Supports all the same notation as `/roll`.\n"
        "**/tip**: Get a random tip about ORC's features posted to the channel."
    )

    TIP_COMMAND_RESPONSE = "💡 **Tip:** {tip}"

    HELP_HEALTH_NAME = "❤️ Health & HP"
    HELP_HEALTH_VALUE = (
        "**/hp status**: View your active character's current HP and temporary HP.\n"
        "**/hp set_max <max_hp>**: Set your active character's maximum HP (also resets current HP to max).\n"
        "**/hp damage <amount> [partymember]**: Apply damage to yourself or a party member (GM only for others). Supports dice (e.g., `2d6+3`).\n"
        "**/hp heal <amount> [partymember]**: Heal yourself or any party member. Supports dice (e.g., `1d8+2`).\n"
        "**/hp temp <amount>**: Add temporary HP to your active character (5e rule: replaces if higher, keeps if lower).\n"
        "**/hp party_temp <amount>**: Add temporary HP to all members of your active party."
    )

    HELP_PARTIES_NAME = "👥 Parties & GM Tools"
    HELP_PARTIES_VALUE = (
        "**/party create <name>**: Create a new group of characters.\n"
        "**/party character_add <party> <character>**: Add a character to a party (GM only).\n"
        "**/party character_remove <party> <character>**: Remove a character from a party (GM only).\n"
        "**/party active <name>**: Set your current active party for quick rolling.\n"
        "**/party roll_as <member> <notation>**: Roll as a member of your active party.\n"
        "**/party roll <notation>**: Roll for every member of your active party at once (e.g., `/party roll stealth`).\n"
        "**/party gm_add <party> <user>**: Add a Discord user as a GM of a party (GM only).\n"
        "**/party gm_remove <party> <user>**: Remove a Discord user as a GM of a party (GM only).\n"
        "**/party view <name>**: View a party's members and GMs.\n"
        "**/party delete <name>**: Delete a party (GM only)."
    )

    HELP_PARTY_SETTINGS_NAME = "⚙️ Party Settings"
    HELP_PARTY_SETTINGS_VALUE = (
        "**/party settings view [party]**: View the current settings for a party.\n"
        "**/party settings initiative_mode <party> <mode>**: Set how enemy initiative is rolled: `by_type` (default), `individual`, or `shared` (GM only).\n"
        "**/party settings enemy_ac <party> <true/false>**: Set whether enemy AC values are visible to all players (GM only).\n"
        "**/party settings death_save_nat20 <party> <mode>**: Set how a natural 20 on a death save is resolved: "
        "`regain_hp` (5e 2024 RAW — regain 1 HP) or `double_success` (house rule — count as 2 successes) (GM only)."
    )

    HELP_ENCOUNTER_NAME = "⚔️ Encounter & Initiative Tracking"
    HELP_ENCOUNTER_VALUE = (
        "**Setup (GM only)**\n"
        "**/encounter create <name>**: Open a new encounter for your active party.\n"
        "**/encounter enemy <name> <init_mod> <max_hp> [count] [ac]**: Add one or more enemies before combat starts. `max_hp` accepts a flat number (`15`) or dice formula (`2d8+4`). `count` defaults to 1 and creates numbered enemies (e.g. `Goblin 1`–`Goblin N`).\n"
        "**/encounter start**: Roll initiative for all party members and enemies, post the turn order, and ping whoever acts first.\n"
        "\n"
        "**During Combat**\n"
        "**/encounter next**: End the current turn and advance the order. Can only be used by the player whose turn it is, or the GM. "
        "The bot will edit the live turn-order message to show the new current actor and ping them. "
        "The round counter increments automatically when the order wraps.\n"
        "**/encounter view**: Show the current initiative order and round number at any time.\n"
        "\n"
        "**Ending Combat**\n"
        "**/encounter end**: Mark the encounter complete (GM only).\n"
        "\n"
        "**Turn order** is determined by each character's initiative roll (d20 + DEX modifier, or a custom bonus set with `/character stats`). "
        "Enemies use their initiative modifier. Tied rolls give priority to players.\n"
        "\n"
        "**HP Management (GM only)**\n"
        "**/encounter damage <position> <damage>**: Apply damage to an enemy by their position number in the initiative order. "
        "The enemy is automatically removed from the order when their HP reaches 0, and a defeat announcement is posted publicly."
    )

    HELP_GETTING_STARTED_NAME = "⭐ QuickStart Guide"
    HELP_GETTING_STARTED_VALUE = (
        "**FOR PLAYERS**\n"
        "You can roll at any time with `/roll <dice notation>`.\n"
        "If you want to store a character sheet in ORC, you'll need a character.\n"
        "To get started, create a character with `/character create` (pick your class — save proficiencies are set automatically!).\n"
        "Then set your stats with `/character stats` — Max HP will be calculated automatically.\n"
        "For accurate rolls, set your skill proficiencies with `/character skill`.\n"
        "When you level up or multiclass, use `/character class_add`.\n"
        "Finally, set your Max HP with `/hp set_max` if it differs from the default calculation (e.g. rolled or tough feat).\n"
        "**FOR GMs**\n"
        "It is recommended that you read all pages of the help command.\n"
        "That said for the very basics, if you want to create a party, do `/party create`, and add characters with `/party character_add`.\n"
        "Once you have a party, you can create encounters with `/encounter create`.\n"
        "Add monsters with `/encounter enemy`.\n"
        "Roll initiative and start the encounter with `/encounter start`."
    )
    HELP_INSPIRATION_NAME = "💫 **Inspiration Tracking**"
    HELP_INSPIRATION_VALUE = (
        "**/inspiration grant [character name]**: Gives Inspiration to a character.\n"
        "**/inspiration remove [character name]**: Removes Inspiration from a character.\n"
        "**/inspiration status [character name]**: Checks if a character has inspiration.\n"
        "Note that only GMs can manage other characters' inspiration."
    )
    HELP_CREDITS_NAME = "👨‍🔧 Credits & Support"
    HELP_CREDITS_VALUE = (
        "ORC was created by Channing Norton (Wobbix on Discord) and is open-source.\n"
        "Feel free to contribute, request features, or report issues on [GitHub](https://github.com/C-Norton/orc).\n"
        "As a measure of support, it would be appreciated if you checked out the Open Source Gaming and Roleplaying Environment (OGRE) "
        "[WorldAnvil Wiki](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/) "
        "and [Discord Server](https://discord.gg/2cBKmVTpHR), where you can also receive support for ORC and stay updated on new features and bug fixes."
    )

    GUILD_JOIN_WELCOME = (
        "Hi! I'm **ORC** (Open-Source Roleplaying Companion), a D&D 5e assistant bot.\n\n"
        "Use `/help` to see everything I can do — character sheets, dice rolls, party management, "
        "initiative tracking, and more!\n\n"
        "Check out the [GitHub](https://github.com/C-Norton/orc), the [ORC & OGRE Discord](https://discord.gg/2cBKmVTpHR)"
        ", and the [OGRE WorldAnvil Wiki](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/)."
    )

    # Health Commands
    HP_SET_SUCCESS = "Set **{char_name}**'s HP to {current}/{max}."
    HP_VIEW = "**{char_name}** — HP: {current}/{max}"
    HP_VIEW_TEMP = " (+{temp} temp)"
    HP_DAMAGE_MSG = "**{char_name}** took {amount} damage! HP: {current}/{max}"
    HP_DEATH_MSG = (
        "\n**{char_name} has died from massive damage!**\nMay they rest in peace."
    )
    HP_HEAL_MSG = "**{char_name}** healed {amount} HP! HP: {current}/{max}"
    HP_TEMP_MSG = "**{char_name}** now has {temp} temporary HP."
    HP_TEMP_PARTY_HEADER = "Temporary HP updated for the party:\n"
    HP_TEMP_PARTY_LINE = "**{char_name}**: {temp} temp HP"

    ERROR_INVALID_MAX_HP = "Max HP must be at least 1."
    ERROR_NO_ACTIVE_PARTY = "No active party set."
    ERROR_GM_ONLY_DAMAGE = "Only the GM can apply damage to other party members."
    ERROR_PARTY_MEMBER_NOT_FOUND = "Party member '**{name}**' not found."
    ERROR_HP_NOT_SET = "HP not set. Use `/hp set_max` first."

    # Attack Commands
    ATTACK_ADDED = "Added attack **{attack_name}** to **{char_name}**."
    ATTACK_UPDATED = "Updated attack **{attack_name}** for **{char_name}**."
    ATTACK_NOT_FOUND = "Attack '**{attack_name}**' not found."
    ATTACK_NO_ATTACKS = (
        "**{char_name}** has no attacks saved. Use `/attack add` to add some!"
    )
    ATTACK_LIST_TITLE = "Attacks for {char_name}"
    ATTACK_ROLL_MSG = "⚔️ **{char_name}** attacks with **{attack_obj_name}**!\n**To Hit**: `d20({d20_roll}) + {hit_modifier}` = **{hit_total}**\n**Damage**: `{damage_formula}` -> `{damage_detail}` = **{damage_total}**"
    ATTACK_ROLL_HIT_TARGET = (
        "⚔️ **{char_name}** attacks **{enemy_name}** with **{attack_name}**!\n"
        "**To Hit**: `d20({d20_roll}) + {hit_modifier}` = **{hit_total}** vs AC {ac} — **HIT!**\n"
        "**Damage**: `{damage_formula}` → `{damage_detail}` = **{damage_total}**"
    )
    ATTACK_ROLL_MISS_TARGET = (
        "⚔️ **{char_name}** attacks **{enemy_name}** with **{attack_name}**!\n"
        "**To Hit**: `d20({d20_roll}) + {hit_modifier}` = **{hit_total}** vs AC {ac} — **MISS!**"
    )
    ATTACK_TARGET_NO_ENCOUNTER = "No active encounter found. Targeted attacks require an active combat encounter."
    ATTACK_TARGET_NOT_FOUND = (
        "❌ No enemy named **{enemy_name}** found in the current encounter."
    )
    ATTACK_TARGET_NO_AC = "❌ **{enemy_name}** has no AC set. Ask the GM to add it with `/encounter enemy`."
    ATTACK_GM_DAMAGE_NOTIFY = (
        "⚔️ **{enemy_name}** took {damage} damage from {char_name}'s {attack_name}. "
        "HP: {current_hp}/{max_hp}"
    )
    ATTACK_GM_ENEMY_DEFEATED = (
        "💀 **{enemy_name}** was defeated by {char_name}'s {attack_name}!"
    )

    ENCOUNTER_GM_DM_EMBED_TITLE = "⚔️ {encounter_name}"
    ENCOUNTER_GM_DM_EMBED_FOOTER = "Party: {party_name}"
    CRIT_HIT_HEADER = "🎯 **CRITICAL HIT!**\n"
    CRIT_PERKINS_INSPIRATION = "\n✨ **{char_name}** gains **Inspiration** from their critical hit! *(Perkins' Rule)*"

    # Inspiration Commands
    INSPIRATION_GRANTED = "✨ **{char_name}** now has **Inspiration**!"
    INSPIRATION_ALREADY_HAS = "**{char_name}** already has Inspiration."
    INSPIRATION_REMOVED = "**{char_name}** no longer has Inspiration."
    INSPIRATION_NOT_HELD = "**{char_name}** does not currently have Inspiration."
    INSPIRATION_STATUS_HAS = "✨ **{char_name}** has Inspiration."
    INSPIRATION_STATUS_NONE = "**{char_name}** does not have Inspiration."
    ERROR_GM_ONLY_INSPIRATION = (
        "Only a GM can grant or remove Inspiration for other party members."
    )
    PARTY_SETTINGS_INVALID_CRIT_RULE = "❌ Invalid crit rule. Valid options: `double_dice`, `perkins`, `double_damage`, `max_damage`, `none`."

    # Weapon Commands
    WEAPON_SEARCH_HEADER = 'Weapon search results for "{query}":'
    WEAPON_SEARCH_FOOTER = (
        "\n\nUse `/weapon add <number>` to add one to **{char_name}**.\n"
        "*(Results expire in 5 minutes)*"
    )
    WEAPON_SEARCH_NO_RESULTS = (
        '❌ No weapons found matching "{query}" in the 2024 SRD. '
        "Try a different search term."
    )
    WEAPON_SEARCH_SESSION_NOT_FOUND = (
        "❌ No weapon search results found. Run `/weapon search` first."
    )
    WEAPON_SEARCH_ERROR = "❌ Could not reach the Open5e API. Please try again later."
    WEAPON_ADD_SUCCESS_HEADER = "✅ Added **{name}** to **{char_name}**."
    WEAPON_ADD_UPDATED_HEADER = "✅ Updated **{name}** on **{char_name}**."
    WEAPON_ADD_HIT_LINE = "**To-hit**: {hit_modifier:+d} ({breakdown})"
    WEAPON_ADD_DAMAGE_LINE = "**Damage**: {damage_dice} {damage_type}"
    WEAPON_ADD_VERSATILE_SUFFIX = " ({two_handed_damage} two-handed)"
    WEAPON_ADD_PROPERTIES_LINE = "**Properties**: {properties}"
    WEAPON_ADD_FOOTER = "\n\nUse `/attack add` to adjust the hit modifier if needed."
    WEAPON_ADD_INVALID_INDEX = "❌ Please enter a number between 1 and {max_index}."

    ERROR_INVALID_DICE = "Invalid dice notation. Use format like '1d20' or '2d6+3'."
    ERROR_DICE_LIMIT = "Too many dice or too many sides! Keep it reasonable."

    # Roll Commands
    ROLL_RESULT_DICE = (
        "🎲 **{notation}**\nRolls: `({rolls}){modifier}`\n**Total: {total}**\n*Tip: {tip}*"
    )
    # {d20_roll} now accepts either "d20(15)" or "d20[15↑,9]" (advantage)
    ROLL_RESULT_CHAR = (
        "**{char_name}**: {label} `{d20_roll} + {modifier}` = **{total}**\n*Tip: {tip}*"
    )
    ROLL_RESULT_SIMPLE = (
        "**{char_name}**: `{notation}` ({rolls}){modifier} = **{total}**\n*Tip: {tip}*"
    )
    ROLL_RESULT_CHAR_EXPR = "**{char_name}**: `{notation}` → {breakdown} = **{total}**\n*Tip: {tip}*"
    ROLL_RESULT_DICE_EXPR = "🎲 **{notation}**\n{breakdown}\n**Total: {total}**\n*Tip: {tip}*"
    ROLL_ERROR_CHAR = "**{char_name}**: ❌ Error: {error}"

    GMROLL_GM_MESSAGE = "🎲 **{char_name}** secretly rolled **{notation}**:\n{result}\n*Tip: {tip}*"
    GMROLL_PLAYER_MESSAGE = "**{char_name}**: `{notation}` → {breakdown} = **{total}**\n*Tip: {tip}*"

    # Character Commands
    CHAR_CREATE_NAME_LIMIT = "Character name cannot exceed 100 characters."
    CHAR_EXISTS = "You already have a character named **{name}** in this server."
    CHAR_CREATED_ACTIVE = (
        "Character **{name}** created as a level **{level}** **{char_class}** and set as active!\n"
        "Saving throw proficiencies have been set from your class.\n"
        "Next, set your stats with `/character stats`, your skill proficiencies with `/character skill`, "
        "and your Max HP with `/hp set_max`.\n"
        "View your character at any time with `/character view`, and switch with `/character switch`."
    )
    CHAR_STATS_FIRST_TIME = "This is your first time setting stats for this character. Please provide all core stats (strength, dexterity, constitution, intelligence, wisdom, charisma)."
    CHAR_STAT_LIMIT = "{stat_name} score must be between 1 and 30."
    CHAR_STATS_UPDATED = "Stats updated for **{char_name}**!"
    CHAR_SAVES_UPDATED = "Saving throw proficiencies updated for **{char_name}**!"
    CHAR_VIEW_TITLE = "👤 {char_name}"
    CHAR_VIEW_DESC = "Level {char_level} {class_summary}"
    CHAR_VIEW_INIT = "\n**Initiative:** {init_bonus:+d}"
    CHAR_VIEW_STATS_FIELD = "Ability Scores"
    CHAR_VIEW_SAVES_FIELD = "Saving Throws"
    CHAR_VIEW_SKILLS_FIELD = "Skills"
    CHAR_VIEW_SKILLS_CONT_FIELD = "Skills (cont.)"

    # Character Sheet — multi-page (4 pages)
    CHAR_SHEET_FOOTER = "🏠 Overview  |  📊 Stats & Saves  |  🎯 Skills  |  ⚔️ Attacks"
    CHAR_SHEET_NOT_YOUR_SHEET = "This character sheet belongs to someone else. Use `/character view` to open your own."
    CHAR_VIEW_NOT_FOUND = "No character named **{name}** found among your characters or your active party."
    CHAR_SHEET_HP_FIELD = "HP"
    CHAR_SHEET_PROF_FIELD = "Proficiency Bonus"
    CHAR_SHEET_NO_STATS = "*Stats not set — use `/character stats`*"
    CHAR_SHEET_NO_ATTACKS = "*No attacks saved — use `/attack add`*"
    CHAR_SHEET_AC_NOT_SET = "🛡 AC: *Not set — use `/character ac`*"
    CHAR_SHEET_AC = "🛡 AC: **{ac}**"
    CHAR_SHEET_INTRO_TITLE = "👤 {char_name} — Character Sheet"
    CHAR_SHEET_INTRO_DESC = (
        "**Level {char_level}** — {class_summary}\n\n"
        "Use the reactions below to navigate:\n\n"
        "🏠 **This page** — overview & quick-reference\n"
        "📊 **Stats & Saves** — ability scores and saving throws\n"
        "🎯 **Skills** — all skill modifiers and proficiency marks\n"
        "⚔️ **Attacks** — saved attack entries"
    )
    CHAR_SHEET_INTRO_QUICK_REF = "Quick Reference"
    CHAR_SWITCH_SUCCESS = "Switched to character **{name}**!"
    CHAR_AC_UPDATED = "**{char_name}**'s Armor Class set to **{ac}**."
    CHAR_AC_LIMIT = "AC must be between 1 and 30."
    CHAR_LEVEL_LIMIT = "Level must be between 1 and 20."
    CHAR_LEVEL_UPDATED = "**{char_name}** is now level **{level}**!"

    # Class Commands
    CHAR_CLASS_ADDED = "**{char_name}** is now a level **{level}** **{char_class}**! (Total level: {total_level})"
    CHAR_CLASS_UPDATED = "**{char_name}**'s **{char_class}** level updated to **{level}**. (Total level: {total_level})"
    CHAR_CLASS_REMOVED = (
        "Removed **{char_class}** from **{char_name}**. (Total level: {total_level})"
    )
    CHAR_CLASS_NOT_FOUND = "**{char_name}** does not have the **{char_class}** class."
    CHAR_CLASS_TOTAL_LEVEL_EXCEEDED = "Adding {level} level(s) of **{char_class}** would bring **{char_name}** above level 20 (current total: {current_total})."
    ERROR_CHAR_NO_CLASSES = (
        "**{char_name}** has no class assigned yet. Use `/character class_add` first."
    )
    CHAR_SKILL_UNKNOWN = "Unknown skill: {skill}"
    CHAR_SKILL_UPDATED = "Updated **{skill}** for **{char_name}** to **{status}**"
    CHAR_LIST_NONE = "You don't have any characters in this server."
    CHAR_LIST_TITLE = "Characters for {user_name}"
    CHAR_LIST_DESC = "In server: **{server_name}**"
    CHAR_NOT_FOUND_NAME = "You don't have a character named **{name}** in this server."
    CHAR_DELETE_SUCCESS = "Character **{name}** has been deleted."

    # Party Commands
    PARTY_CREATE_SUCCESS_EMPTY = "Empty party '**{party_name}**' created successfully!"
    PARTY_CREATE_SUCCESS_MEMBERS = (
        "Party '**{party_name}**' created successfully with {count} characters!"
    )
    PARTY_NOT_FOUND = "Party '**{party_name}**' not found."
    PARTY_ALREADY_EXISTS = (
        "A party named '**{party_name}**' already exists in this server."
    )
    PARTY_MEMBER_ALREADY_IN = "**{character_name}** is already in the party."
    PARTY_MEMBER_ADDED = "Added **{character_name}** (owned by <@{discord_id}>) to party '**{party_name}**'."
    PARTY_MEMBER_REMOVED = "Removed **{character_name}** from party '**{party_name}**'."
    PARTY_ACTIVE_SET = "Set '**{party_name}**' as your active party."
    PARTY_ACTIVE_VIEW = (
        "Your active party is '**{party_name}**'.\nMembers: {char_names}"
    )
    PARTY_ACTIVE_NONE = "You don't have an active party set."
    PARTY_ACTIVE_MEMBER_NOT_FOUND = (
        "Member '**{member_name}**' not found in your active party."
    )
    PARTY_ROLL_HEADER = "🎲 **Party Roll: {notation}** (Party: {party_name})\n"
    PARTY_VIEW_TITLE = "Party: {party_name}"
    PARTY_VIEW_GM = "GMs"
    PARTY_VIEW_MEMBERS = "Members"
    PARTY_VIEW_EMPTY = "This party has no members."
    PARTY_VIEW_MEMBER_LINE = (
        "● **{char_name}** (Level {char_level}) - Controlled by <@{discord_id}>"
    )
    PARTY_DELETE_SUCCESS = "Party '**{party_name}**' deleted successfully."
    PARTY_ROLL_EMPTY = "Your active party is empty."

    GM_ADDED = "Added <@{discord_id}> as a GM of '**{party_name}**'."
    GM_REMOVED = "Removed <@{discord_id}> as a GM of '**{party_name}**'."
    ERROR_GM_ALREADY = "<@{discord_id}> is already a GM of '**{party_name}**'."
    ERROR_GM_NOT_IN_PARTY = "<@{discord_id}> is not a GM of '**{party_name}**'."
    ERROR_GM_LAST = "Cannot remove the last GM from a party."
    ERROR_GM_ONLY_ADD_GM = "Only a GM of this party can add other GMs."
    ERROR_GM_ONLY_REMOVE_GM = "Only a GM of this party can remove GMs."

    ERROR_GM_ONLY_PARTY_CREATE = (
        "Only the GM of the party can create an encounter."  # reused in encounter
    )
    ERROR_GM_ONLY_PARTY_ADD = "Only a GM of the party can add members."
    ERROR_GM_ONLY_PARTY_REMOVE = "Only a GM of the party can remove members."
    ERROR_GM_ONLY_PARTY_DELETE = "Only a GM can delete the party."
    ERROR_USER_SERVER_NOT_INIT = "User or Server not initialized."
    ERROR_PARTY_CHAR_NOT_FOUND = "\nCharacters not found: {names}"
    ERROR_PARTY_SET_ACTIVE_FIRST = "Set an active party first with `/party active`."

    # Character deletion confirmations
    CHAR_DELETE_CONFIRM = "⚠️ Are you sure you want to permanently delete **{name}**? This cannot be undone."
    CHAR_DELETE_ENCOUNTER_CONFIRM = (
        "⚠️ **{name}** is currently in the active encounter '**{encounter_name}**'.\n"
        "Deleting them will also remove their turn from the initiative order.\n\n"
        "This cannot be undone. Are you sure?"
    )
    CHAR_DELETE_CANCELLED = "Deletion cancelled."

    # Party — encounter-guard strings
    PARTY_REMOVE_ENCOUNTER_WARNING = (
        "⚠️ **{char_name}** is currently in the active encounter '**{encounter_name}**'.\n"
        "Removing them will also remove their turn from the initiative order.\n\n"
        "Do you want to proceed?"
    )
    PARTY_CHAR_REMOVE_CONFIRM = (
        "⚠️ Are you sure you want to remove **{char_name}** from '**{party_name}**'?"
    )
    PARTY_REMOVE_ENCOUNTER_CONFIRMED = "Removed **{char_name}** from party '**{party_name}**' and from the initiative order."
    PARTY_REMOVE_CANCELLED = "Removal cancelled."
    PARTY_DELETE_CONFIRM = (
        "⚠️ Are you sure you want to permanently delete party '**{party_name}**'? "
        "This cannot be undone."
    )
    PARTY_DELETE_ENCOUNTER_CONFIRM = (
        "⚠️ Party '**{party_name}**' has an open encounter: **{encounter_names}**.\n"
        "Deleting the party will automatically complete and remove it.\n\n"
        "Are you sure?"
    )
    PARTY_DELETE_CANCELLED = "Deletion cancelled."
    PARTY_DELETE_ENCOUNTER_COMPLETED = "Open encounter '**{encounter_name}**' was automatically completed before the party was deleted."
    PARTY_GM_REMOVE_SELF_CONFIRM = (
        "⚠️ Are you sure you want to remove yourself as GM of '**{party_name}**'? "
        "You will no longer be able to manage this party."
    )
    PARTY_GM_REMOVE_SELF_CANCELLED = "GM removal cancelled."

    # Encounter Commands
    ENCOUNTER_ORDER_HEADER = "⚔️ **{name}** | Round {round_number}"
    ENCOUNTER_TURN_PING = "{ping} It is now **{name}**'s turn. When you have described your actions and made your rolls, end your turn with `/encounter next`."
    ENCOUNTER_CREATED = "⚔️ Encounter **{name}** created! Add enemies with `/encounter enemy`, then start combat with `/encounter start`."
    ENCOUNTER_ALREADY_OPEN = (
        "This party already has an open encounter. End it with `/encounter end` first."
    )
    ENCOUNTER_ENEMY_ADDED = (
        "Added **{name}** (Initiative +{init_mod}, HP {hp}) to **{encounter_name}**."
    )
    ENCOUNTER_ENEMY_ADDED_SINGLE = "Added **{name}** to **{encounter_name}** (Init: {init_mod:+d}, HP: {hp}, AC: {ac_str})."
    ENCOUNTER_ENEMIES_ADDED_BULK = (
        "Added {count}× **{type_name}** to **{encounter_name}**:\n{enemy_lines}"
    )
    ENCOUNTER_ENEMY_BULK_LINE = "• **{name}** — HP: {hp}{ac_part}"
    ENCOUNTER_INVALID_HP = "❌ Invalid HP value `{value}`. Use a number (e.g. `15`) or dice formula (e.g. `2d8+4`)."
    ENCOUNTER_ENEMY_COUNT_OVER_LIMIT = "❌ Cannot add {count} {enemy_word}: the encounter limit is {limit} and {remaining} slot(s) remain."
    ENCOUNTER_ALREADY_STARTED = "The encounter has already started."
    ENCOUNTER_NOT_STARTED = "Enemies can only be added before the encounter starts."
    ENCOUNTER_NO_ENEMIES = (
        "Add at least one enemy with `/encounter enemy` before starting."
    )
    ENCOUNTER_PARTY_NO_MEMBERS = "The party has no members."
    ENCOUNTER_NOT_ACTIVE = "There is no active encounter on this server."
    ENCOUNTER_NEXT_TURN_DENIED = (
        "You can only use `/encounter next` on your own turn, or if you are the GM."
    )
    ENCOUNTER_TURN_ADVANCED = "Turn advanced."
    ENCOUNTER_ENDED = "⚔️ Encounter **{encounter_name}** has ended."
    ENCOUNTER_NO_ACTIVE_TO_END = "No active encounter to end."
    ENCOUNTER_VIEW_TITLE = "⚔️ {name}"
    ENCOUNTER_VIEW_DESC = "Round {round_number}"
    ENCOUNTER_VIEW_ORDER_FIELD = "Initiative Order"

    ENCOUNTER_DAMAGE_HP_UPDATE = (
        "⚔️ **{name}** takes {damage} damage. HP: {current_hp}/{max_hp}"
    )
    ENCOUNTER_DAMAGE_ENEMY_DEFEATED = (
        "💀 **{name}** has been defeated and removed from the initiative order!"
    )
    ENCOUNTER_ALL_ENEMIES_DEFEATED = (
        "🏆 All enemies have been defeated! Encounter **{encounter_name}** has ended."
    )
    ENCOUNTER_ENEMY_PLACEMENT_PROMPT = "⚔️ **{encounter_name}** is active. Where should {enemy_description} enter initiative?"
    ENCOUNTER_ENEMY_ADDED_TOP = (
        "✅ {enemy_description} added at the **top** of initiative."
    )
    ENCOUNTER_ENEMY_ADDED_BOTTOM = (
        "✅ {enemy_description} added at the **bottom** of initiative."
    )
    ENCOUNTER_ENEMY_ADDED_AFTER_CURRENT = (
        "✅ {enemy_description} added **after the current turn**."
    )
    ENCOUNTER_ENEMY_ADDED_ROLLED = "✅ {enemy_description} rolled into initiative."
    ENCOUNTER_ENEMY_PLACEMENT_EXPIRED = (
        "❌ No placement selected — no enemies were added."
    )
    ENCOUNTER_ENEMY_JOINED_PUBLIC = "⚔️ {enemy_description} joins **{encounter_name}**!"
    ENCOUNTER_DAMAGE_INVALID_POSITION = "❌ Position {position} is not valid. The initiative order has {count} position(s)."
    ENCOUNTER_DAMAGE_NOT_ENEMY = "❌ Position {position} is a player character. Use `/hp damage` for player characters."
    ENCOUNTER_DAMAGE_MUST_BE_POSITIVE = "❌ Damage must be greater than zero."
    ENCOUNTER_VIEW_ENEMY_HP = "HP: {current_hp}/{max_hp}"
    ENCOUNTER_VIEW_ENEMY_HP_AC = "HP: {current_hp}/{max_hp} | AC: {ac}"
    ENCOUNTER_VIEW_CHARACTER_HP = "HP: {current_hp}/{max_hp}"
    ENCOUNTER_VIEW_CHARACTER_HP_UNKNOWN = "HP: unknown"
    ENCOUNTER_VIEW_GM_DETAILS_TITLE = "GM Details — {name}"
    ENCOUNTER_VIEW_GM_ENEMY_VALUE = (
        "HP: {current_hp}/{max_hp} | AC: {ac_str} | Init mod: {init_mod:+d}"
    )
    ERROR_GM_ONLY_ENCOUNTER_CREATE = "Only the GM of the party can create an encounter."
    ERROR_GM_ONLY_ENEMY_ADD = "Only the GM can add enemies."
    ERROR_GM_ONLY_ENCOUNTER_DAMAGE = "Only a GM can apply damage to enemies."
    ERROR_GM_ONLY_ENCOUNTER_END = "Only the GM can end the encounter."
    ERROR_NO_PENDING_ENCOUNTER = (
        "No pending encounter found. Create one with `/encounter create`."
    )

    # Party Settings
    PARTY_SETTINGS_UPDATED = (
        "✅ Setting **{setting}** updated to **{value}** for party '**{party_name}**'."
    )
    PARTY_SETTINGS_VIEW = (
        "⚙️ **Settings for '{party_name}'**\n"
        "Initiative Mode: **{initiative_mode}**\n"
        "Enemy AC visible to players: **{enemy_ac_public}**\n"
        "Death save nat-20 rule: **{death_save_nat20_mode}**"
    )
    PARTY_SETTINGS_INVALID_MODE = (
        "❌ Invalid initiative mode. Choose from: `by_type`, `individual`, `shared`."
    )
    PARTY_SETTINGS_INVALID_NAT20_MODE = (
        "❌ Invalid nat-20 mode. Choose from: `regain_hp`, `double_success`."
    )
    PARTY_SETTINGS_NAT20_UPDATED = (
        "✅ Death save nat-20 rule updated to **{mode}** for party '**{party_name}**'."
    )
    ERROR_GM_ONLY_PARTY_SETTINGS = "Only a GM of this party can change settings."

    # Party List
    PARTY_LIST_EMBED_TITLE = "📋 Parties in {server_name}"
    PARTY_LIST_EMBED_FOOTER = "Page {page}/{total_pages} · {total_parties} total"
    PARTY_LIST_MEMBER_COUNT = "{count} member{plural}"
    PARTY_LIST_EMPTY = "No parties have been created on this server yet."

    # Death Save Strings
    DEATH_SAVE_NOT_DYING = "❌ **{char_name}** is not currently dying — death saves are only rolled at 0 HP."
    DEATH_SAVE_RESULT_SUCCESS = (
        "🎲 **Death Save — Success** (rolled {roll}): "
        "{successes}/3 successes, {failures}/3 failures."
    )
    DEATH_SAVE_RESULT_FAILURE = (
        "🎲 **Death Save — Failure** (rolled {roll}): "
        "{successes}/3 successes, {failures}/3 failures."
    )
    DEATH_SAVE_STABILIZED = "✅ **{char_name} has stabilized!** Three successes — death save counters reset."
    DEATH_SAVE_SLAIN = (
        ":skull: **{char_name} has been slain** after three failed death saves."
    )
    DEATH_SAVE_NAT20_HEAL = (
        "🌟 **Natural 20!** {char_name} regains 1 HP and is no longer dying."
    )
    DEATH_SAVE_NAT20_DOUBLE = "🌟 **Natural 20!** Two successes recorded."
    DEATH_SAVE_NAT1_DOUBLE = "💀 **Natural 1!** Two failures recorded."
    # tips
    TIPS = [
        "Love ORC? The best way to support us is a recommendation to others!",
        "Got a feature suggestion? [Join the Discord](https://discord.gg/2cBKmVTpHR), or reach out on [Github](https://github.com/c-norton/ORC)",
        "Join the [OGRE discord server](https://discord.gg/2cBKmVTpHR) for updates about ORC, including new features, bug fixes, and community feedback",
        "Have a funny nat1 or nat20 line? Let the dev know to add it. Reachable on [Discord](https://discord.gg/2cBKmVTpHR) or [Github](https://github.com/c-norton/ORC)",
        "Use /help to view a list of all commands and features",
        "If you create a character, you can roll with skill names, along with other benefits",
        "You can secretly roll dice with /gmroll",
        "Try `/roll perception` instead of `/roll 1d20` — once your character has skills set up, ORC adds the right proficiency bonus automatically.",
        "Set your skill proficiency to **Expertise** with `/character skill` and your rolls will include double proficiency. Jack of All Trades works too.",
        "Use `/gmroll` to roll privately. Your result is visible only to you — and every GM of your parties gets it as a DM automatically.",
        "Rolling with **advantage**? Both `/roll` and `/gmroll` have an optional advantage field. No need to roll twice and pick the higher manually.",
        "Once your character has stats set, `/roll initiative` uses your Dexterity modifier. Set an `initiative_bonus` override with `/character stats` if your class or feat gives you a bonus.",
        "ORC tracks **death saves** for you. When your character hits 0 HP, 'death save' will appear in `/roll`'s autocomplete. A natural 1 counts as two failures.",
        "Your party's GM can choose what a natural 20 does on a death save — it can heal you to 1 HP (5e 2024 rules) or count as two successes. Ask your GM which is set.",
        "Set your saving throw proficiencies with `/character saves`. Then `/roll str save` will include your proficiency bonus automatically.",
        "Save your attacks with `/attack add` and you'll never need to remember your to-hit bonus again. `/attack roll` handles the math.",
        "When rolling a saved attack against an enemy in an active encounter, ORC tracks the HP for you — and removes the enemy from initiative when they drop to 0.",
        "Critical hits aren't just double damage — your GM can configure the crit rule for your party. **Perkins rule** even grants you Inspiration on a nat 20.",
        "Complex expressions like `2d6+perception` or `1d20+strength` work in `/roll`. You can mix dice with stat names and skills to apply situation bonuses, if your table uses them.",
        "Use `/weapon search` to look up any weapon from the 2024 SRD, then `/weapon add` to import it directly to your character. ORC calculates the hit modifier for you.",
        "Finesse weapons? ORC figures out whether to use Strength or Dexterity automatically when you import with `/weapon add`.",
        "Temp HP follows the 5e rule: `/hp temp` replaces your temp HP only if the new amount is higher. It won't overwrite a larger pool.",
        "Damage while at 0 HP adds a death save failure automatically. Your GM doesn't need to track it manually.",
        "Party members can have their HP adjusted by the GM with `/hp damage` and `/hp heal` using the `partymember` field — no need for the player to be present.",
        "Add temp HP to your entire party at once with `/hp party_temp`. Useful after a short rest or a bardic performance.",
        "Use `/party roll perception` to roll Perception for every member of your party at once. Great for group checks.",
        "Your character sheet has four pages of information — stats, skills, and attacks are all one button press away in `/character view`.",
        "Multiclassing is supported. Use `/character class_add` to add a second class. ORC tracks each class separately and recalculates your proficiency bonus.",
        "Party GMs receive a DM whenever HP changes during an encounter — they always know the state of the fight even in a big session.",
        "Your party's GM can set **enemy initiative mode** to roll individually per enemy, per enemy type, or a single shared roll for all enemies.",
        "Enemy AC can be hidden from players and shown only to GMs. Your GM controls this with `/party settings enemy_ac`.",
        "Use `/encounter enemy` with a count to add multiple enemies at once. 'Goblin' with count 3 becomes Goblin 1, 2, and 3 in initiative.",
        "Enemy HP can be set as a dice formula — `/encounter enemy` accepts `2d8+4` for max HP, so each enemy rolls their own.",
        "Adding an enemy mid-encounter? ORC gives your GM a menu to place them at the top, bottom, after the current turn, or in initiative order by roll.",
        "The `/encounter view` command shows different information to GMs — they see exact HP, AC, and initiative modifiers that players don't.",
        "Inspiration can be granted by a GM to any party member, or to yourself if you earn it. Check your status with `/inspiration status`.",
        "Enter the world of OGRE, the Opensource Gaming and Roleplaying Environment. A shared 5e setting in the middle of a steampunk industrial revolution!",
    ]
    DEATH_SAVE_DAMAGE_FAILURE = (
        "💀 **{char_name}** took damage while dying — 1 failure recorded "
        "({failures}/3 failures)."
    )
    DEATH_SAVE_DAMAGE_SLAIN = (
        ":skull: **{char_name} has been slain** — three failures from taking damage."
    )
    DEATH_SAVE_HEAL_RESET = "Death save counters reset for **{char_name}**."
    DEATH_SAVE_TURN_PROMPT = (
        "{char_name} is **unconscious and dying** — use `/roll` → `death save` "
        "for your death saving throw."
    )
    DEATH_SAVE_COUNTER_DISPLAY = "(Dying: {successes}✓ {failures}✗)"






    NAT_20_ATTACK = ["Your attack connects with ruthless efficiency"]
    NAT_1_ATTACK = [
        "That'll be a miss",
        "Oops; did you intend to hit an ally? Or was that just happenstance?",
    ]
    NAT_20_SKILLCHECK = []
    NAT_1_SKILLCHECK = []
    NAT_20_SAVE = []
    NAT_1_SAVE = []



