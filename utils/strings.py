class Strings:
    # Common
    CHARACTER_NOT_FOUND = "You don't have a character in this server. Use `/character create` first."
    ACTIVE_CHARACTER_NOT_FOUND = "You don't have an active character."
    SERVER_ERROR = "❌ An unexpected error occurred."

    # Resource limits
    ERROR_LIMIT_CHARACTERS = (
        "You have reached the maximum number of characters ({limit}) across all servers."
    )
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
    HELP_TITLE = "Thank you for using ORC - the Opensource Roleplaying Companion bot for D&D 5e"
    HELP_DESCRIPTION = "Check out our shared setting: [Open Source Gaming and Roleplaying environment (OGRE)](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/)"
    HELP_FOOTER = "Tip: Use autocomplete for character, party, and skill names!"
    HELP_NOT_YOUR_MENU = "This help menu belongs to someone else. Use `/help` to open your own."
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
        "**/attack add <name> <hit_mod> <damage>**: Save an attack (e.g., `/attack add Longsword 5 1d8+3`).\n"
        "**/attack list**: List all your saved attacks.\n"
        "**/attack roll <name> [target]**: Roll a to-hit and damage roll for a saved attack. "
        "In an active encounter, pass `target` as the enemy's position number to resolve the hit "
        "against their AC and automatically update their HP."
    )
    
    HELP_ROLLING_NAME = "🎲 Rolling"
    HELP_ROLLING_VALUE = (
        "**/roll <notation>**: Roll anything! Use skill names (e.g., `perception`), saves (e.g., `wis save`), or dice (e.g., `1d20+5`)."
    )
    
    HELP_HEALTH_NAME = "❤️ Health & HP"
    HELP_HEALTH_VALUE = (
        "**/hp**: View your active character's current HP and temporary HP.\n"
        "**/set_max_hp <max_hp>**: Set your active character's maximum HP.\n"
        "**/damage <amount> [partymember]**: Apply damage to yourself or a party member (GM only). Supports dice (e.g., `2d6+3`).\n"
        "**/heal <amount> [partymember]**: Heal yourself or a party member (GM only). Supports dice (e.g., `1d8+2`).\n"
        "**/add_temp_hp <amount>**: Add temporary HP to your active character.\n"
        "**/add_temp_hp_party <amount>**: Add temporary HP to all members of your active party."
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
        "**/party delete <name>**: Delete a party (GM only).\n"
        "**/party settings view [party]**: View the current settings for a party.\n"
        "**/party settings initiative_mode <party> <mode>**: Set how enemy initiative is rolled: `by_type` (default), `individual`, or `shared` (GM only).\n"
        "**/party settings enemy_ac <party> <true/false>**: Set whether enemy AC values are visible to all players (GM only)."
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
        "Finally, set your Max HP with `/set_max_hp`.\n"
        "**FOR GMs**\n"
        "It is recommended that you read all pages of the help command.\n"
        "That said for the very basics, if you want to create a party, do `/party create`, and add characters with `/party character_add`.\n"
        "Once you have a party, you can create encounters with `/encounter create`.\n"
        "Add monsters with `/encounter enemy`.\n"
        "Roll initiative and start the encounter with `/encounter start`."
    )
    GUILD_JOIN_WELCOME = (
        "Hi! I'm **ORC** (Open-Source Roleplaying Companion), a D&D 5e assistant bot.\n\n"
        "Use `/help` to see everything I can do — character sheets, dice rolls, party management, "
        "initiative tracking, and more!\n\n"
        "Check out the [GitHub](https://github.com/C-Norton/orc) and the "
        "[OGRE WorldAnvil Wiki](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/)."
    )

    HELP_CREDITS_NAME = "👨‍🔧 Credits & Support"
    HELP_CREDITS_VALUE = (
        "ORC was created by Channing Norton (Wobbix on Discord) and is open-source.\n"
        "Feel free to contribute, request features, or report issues on [GitHub](https://github.com/C-Norton/orc).\n"
        "As a measure of support, it would be appreciated if you checked out the Open Source Gaming and Roleplaying Environment (OGRE) "
        "[WorldAnvil Wiki](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/) "
        "and [Discord Server](https://discord.gg/2cBKmVTpHR)."
    )

    # Health Commands
    HP_SET_SUCCESS = "Set **{char_name}**'s HP to {current}/{max}."
    HP_VIEW = "**{char_name}** — HP: {current}/{max}"
    HP_VIEW_TEMP = " (+{temp} temp)"
    HP_DAMAGE_MSG = "**{char_name}** took {amount} damage! HP: {current}/{max}"
    HP_DEATH_MSG = "\n**{char_name} has died from massive damage!**\nMay they rest in peace."
    HP_HEAL_MSG = "**{char_name}** healed {amount} HP! HP: {current}/{max}"
    HP_TEMP_MSG = "**{char_name}** now has {temp} temporary HP."
    HP_TEMP_PARTY_HEADER = "Temporary HP updated for the party:\n"
    HP_TEMP_PARTY_LINE = "**{char_name}**: {temp} temp HP"
    
    ERROR_INVALID_MAX_HP = "Max HP must be at least 1."
    ERROR_NO_ACTIVE_PARTY = "No active party set."
    ERROR_GM_ONLY_DAMAGE = "Only the GM can apply damage to other party members."
    ERROR_PARTY_MEMBER_NOT_FOUND = "Party member '**{name}**' not found."
    ERROR_HP_NOT_SET = "HP not set. Use `/set_max_hp` first."

    # Attack Commands
    ATTACK_ADDED = "Added attack **{attack_name}** to **{char_name}**."
    ATTACK_UPDATED = "Updated attack **{attack_name}** for **{char_name}**."
    ATTACK_NOT_FOUND = "Attack '**{attack_name}**' not found."
    ATTACK_NO_ATTACKS = "**{char_name}** has no attacks saved. Use `/attack add` to add some!"
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
    ATTACK_TARGET_NO_ENCOUNTER = (
        "No active encounter found. Targeted attacks require an active combat encounter."
    )
    ATTACK_TARGET_NOT_FOUND = (
        "❌ No enemy named **{enemy_name}** found in the current encounter."
    )
    ATTACK_TARGET_NO_AC = (
        "❌ **{enemy_name}** has no AC set. Ask the GM to add it with `/encounter enemy`."
    )
    ATTACK_GM_DAMAGE_NOTIFY = (
        "⚔️ **{enemy_name}** took {damage} damage from {char_name}'s {attack_name}. "
        "HP: {current_hp}/{max_hp}"
    )
    ATTACK_GM_ENEMY_DEFEATED = (
        "💀 **{enemy_name}** was defeated by {char_name}'s {attack_name}!"
    )
    ENCOUNTER_GM_DM_EMBED_TITLE = "⚔️ {encounter_name}"
    ENCOUNTER_GM_DM_EMBED_FOOTER = "Party: {party_name}"

    ERROR_INVALID_DICE = "Invalid dice notation. Use format like '1d20' or '2d6+3'."
    ERROR_DICE_LIMIT = "Too many dice or too many sides! Keep it reasonable."

    # Roll Commands
    ROLL_RESULT_DICE = "🎲 **{notation}**\nRolls: `({rolls}){modifier}`\n**Total: {total}**"
    # {d20_roll} now accepts either "d20(15)" or "d20[15↑,9]" (advantage)
    ROLL_RESULT_CHAR = "**{char_name}**: {label} `{d20_roll} + {modifier}` = **{total}**"
    ROLL_RESULT_SIMPLE = "**{char_name}**: `{notation}` ({rolls}){modifier} = **{total}**"
    ROLL_RESULT_CHAR_EXPR = "**{char_name}**: `{notation}` → {breakdown} = **{total}**"
    ROLL_RESULT_DICE_EXPR = "🎲 **{notation}**\n{breakdown}\n**Total: {total}**"
    ROLL_ERROR_CHAR = "**{char_name}**: ❌ Error: {error}"

    # Character Commands
    CHAR_CREATE_NAME_LIMIT = "Character name cannot exceed 100 characters."
    CHAR_EXISTS = "You already have a character named **{name}** in this server."
    CHAR_CREATED_ACTIVE = (
        "Character **{name}** created as a level **{level}** **{char_class}** and set as active!\n"
        "Saving throw proficiencies have been set from your class.\n"
        "Next, set your stats with `/character stats`, your skill proficiencies with `/character skill`, "
        "and your Max HP with `/set_max_hp`.\n"
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
    CHAR_CLASS_REMOVED = "Removed **{char_class}** from **{char_name}**. (Total level: {total_level})"
    CHAR_CLASS_NOT_FOUND = "**{char_name}** does not have the **{char_class}** class."
    CHAR_CLASS_TOTAL_LEVEL_EXCEEDED = "Adding {level} level(s) of **{char_class}** would bring **{char_name}** above level 20 (current total: {current_total})."
    ERROR_CHAR_NO_CLASSES = "**{char_name}** has no class assigned yet. Use `/character class_add` first."
    CHAR_SKILL_UNKNOWN = "Unknown skill: {skill}"
    CHAR_SKILL_UPDATED = "Updated **{skill}** for **{char_name}** to **{status}**"
    CHAR_LIST_NONE = "You don't have any characters in this server."
    CHAR_LIST_TITLE = "Characters for {user_name}"
    CHAR_LIST_DESC = "In server: **{server_name}**"
    CHAR_NOT_FOUND_NAME = "You don't have a character named **{name}** in this server."
    CHAR_DELETE_SUCCESS = "Character **{name}** has been deleted."

    # Party Commands
    PARTY_CREATE_SUCCESS_EMPTY = "Empty party '**{party_name}**' created successfully!"
    PARTY_CREATE_SUCCESS_MEMBERS = "Party '**{party_name}**' created successfully with {count} characters!"
    PARTY_NOT_FOUND = "Party '**{party_name}**' not found."
    PARTY_ALREADY_EXISTS = "A party named '**{party_name}**' already exists in this server."
    PARTY_MEMBER_ALREADY_IN = "**{character_name}** is already in the party."
    PARTY_MEMBER_ADDED = "Added **{character_name}** (owned by <@{discord_id}>) to party '**{party_name}**'."
    PARTY_MEMBER_REMOVED = "Removed **{character_name}** from party '**{party_name}**'."
    PARTY_ACTIVE_SET = "Set '**{party_name}**' as your active party."
    PARTY_ACTIVE_VIEW = "Your active party is '**{party_name}**'.\nMembers: {char_names}"
    PARTY_ACTIVE_NONE = "You don't have an active party set."
    PARTY_ACTIVE_MEMBER_NOT_FOUND = "Member '**{member_name}**' not found in your active party."
    PARTY_ROLL_HEADER = "🎲 **Party Roll: {notation}** (Party: {party_name})\n"
    PARTY_VIEW_TITLE = "Party: {party_name}"
    PARTY_VIEW_GM = "GMs"
    PARTY_VIEW_MEMBERS = "Members"
    PARTY_VIEW_EMPTY = "This party has no members."
    PARTY_VIEW_MEMBER_LINE = "● **{char_name}** (Level {char_level}) - Controlled by <@{discord_id}>"
    PARTY_DELETE_SUCCESS = "Party '**{party_name}**' deleted successfully."
    PARTY_ROLL_EMPTY = "Your active party is empty."

    GM_ADDED = "Added <@{discord_id}> as a GM of '**{party_name}**'."
    GM_REMOVED = "Removed <@{discord_id}> as a GM of '**{party_name}**'."
    ERROR_GM_ALREADY = "<@{discord_id}> is already a GM of '**{party_name}**'."
    ERROR_GM_NOT_IN_PARTY = "<@{discord_id}> is not a GM of '**{party_name}**'."
    ERROR_GM_LAST = "Cannot remove the last GM from a party."
    ERROR_GM_TARGET_NOT_REGISTERED = "That user has no account in this bot. They need to use a command first."
    ERROR_GM_ONLY_ADD_GM = "Only a GM of this party can add other GMs."
    ERROR_GM_ONLY_REMOVE_GM = "Only a GM of this party can remove GMs."

    ERROR_GM_ONLY_PARTY_CREATE = "Only the GM of the party can create an encounter."  # reused in encounter
    ERROR_GM_ONLY_PARTY_ADD = "Only a GM of the party can add members."
    ERROR_GM_ONLY_PARTY_REMOVE = "Only a GM of the party can remove members."
    ERROR_GM_ONLY_PARTY_DELETE = "Only a GM can delete the party."
    ERROR_USER_SERVER_NOT_INIT = "User or Server not initialized."
    ERROR_PARTY_CHAR_NOT_FOUND = "\nCharacters not found: {names}"
    ERROR_PARTY_SET_ACTIVE_FIRST = "Set an active party first with `/party active`."

    # Character deletion confirmations
    CHAR_DELETE_CONFIRM = (
        "⚠️ Are you sure you want to permanently delete **{name}**? This cannot be undone."
    )
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
    PARTY_REMOVE_ENCOUNTER_CONFIRMED = (
        "Removed **{char_name}** from party '**{party_name}**' and from the initiative order."
    )
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
    PARTY_DELETE_ENCOUNTER_COMPLETED = (
        "Open encounter '**{encounter_name}**' was automatically completed before the party was deleted."
    )
    PARTY_GM_REMOVE_SELF_CONFIRM = (
        "⚠️ Are you sure you want to remove yourself as GM of '**{party_name}**'? "
        "You will no longer be able to manage this party."
    )
    PARTY_GM_REMOVE_SELF_CANCELLED = "GM removal cancelled."

    # Encounter Commands
    ENCOUNTER_ORDER_HEADER = "⚔️ **{name}** | Round {round_number}"
    ENCOUNTER_TURN_PING = "{ping} It is now **{name}**'s turn. When you have described your actions and made your rolls, end your turn with `/encounter next`."
    ENCOUNTER_CREATED = "⚔️ Encounter **{name}** created! Add enemies with `/encounter enemy`, then start combat with `/encounter start`."
    ENCOUNTER_ALREADY_OPEN = "This party already has an open encounter. End it with `/encounter end` first."
    ENCOUNTER_ENEMY_ADDED = "Added **{name}** (Initiative +{init_mod}, HP {hp}) to **{encounter_name}**."
    ENCOUNTER_ENEMY_ADDED_SINGLE = "Added **{name}** to **{encounter_name}** (Init: {init_mod:+d}, HP: {hp}, AC: {ac_str})."
    ENCOUNTER_ENEMIES_ADDED_BULK = "Added {count}× **{type_name}** to **{encounter_name}**:\n{enemy_lines}"
    ENCOUNTER_ENEMY_BULK_LINE = "• **{name}** — HP: {hp}{ac_part}"
    ENCOUNTER_INVALID_HP = "❌ Invalid HP value `{value}`. Use a number (e.g. `15`) or dice formula (e.g. `2d8+4`)."
    ENCOUNTER_ENEMY_COUNT_OVER_LIMIT = "❌ Cannot add {count} {enemy_word}: the encounter limit is {limit} and {remaining} slot(s) remain."
    ENCOUNTER_ALREADY_STARTED = "The encounter has already started."
    ENCOUNTER_NOT_STARTED = "Enemies can only be added before the encounter starts."
    ENCOUNTER_NO_ENEMIES = "Add at least one enemy with `/encounter enemy` before starting."
    ENCOUNTER_PARTY_NO_MEMBERS = "The party has no members."
    ENCOUNTER_NOT_ACTIVE = "There is no active encounter on this server."
    ENCOUNTER_NEXT_TURN_DENIED = "You can only use `/encounter next` on your own turn, or if you are the GM."
    ENCOUNTER_TURN_ADVANCED = "Turn advanced."
    ENCOUNTER_ENDED = "⚔️ Encounter **{encounter_name}** has ended."
    ENCOUNTER_NO_ACTIVE_TO_END = "No active encounter to end."
    ENCOUNTER_VIEW_TITLE = "⚔️ {name}"
    ENCOUNTER_VIEW_DESC = "Round {round_number}"
    ENCOUNTER_VIEW_ORDER_FIELD = "Initiative Order"
    
    ENCOUNTER_DAMAGE_HP_UPDATE = "⚔️ **{name}** takes {damage} damage. HP: {current_hp}/{max_hp}"
    ENCOUNTER_DAMAGE_ENEMY_DEFEATED = "💀 **{name}** has been defeated and removed from the initiative order!"
    ENCOUNTER_DAMAGE_INVALID_POSITION = "❌ Position {position} is not valid. The initiative order has {count} position(s)."
    ENCOUNTER_DAMAGE_NOT_ENEMY = "❌ Position {position} is a player character. Use `/hp damage` for player characters."
    ENCOUNTER_DAMAGE_MUST_BE_POSITIVE = "❌ Damage must be greater than zero."
    ENCOUNTER_VIEW_ENEMY_HP = "HP: {current_hp}/{max_hp}"
    ENCOUNTER_VIEW_ENEMY_HP_AC = "HP: {current_hp}/{max_hp} | AC: {ac}"
    ENCOUNTER_VIEW_CHARACTER_HP = "HP: {current_hp}/{max_hp}"
    ENCOUNTER_VIEW_CHARACTER_HP_UNKNOWN = "HP: unknown"
    ENCOUNTER_VIEW_GM_DETAILS_TITLE = "GM Details — {name}"
    ENCOUNTER_VIEW_GM_ENEMY_VALUE = "HP: {current_hp}/{max_hp} | AC: {ac_str} | Init mod: {init_mod:+d}"
    ERROR_GM_ONLY_ENCOUNTER_CREATE = "Only the GM of the party can create an encounter."
    ERROR_GM_ONLY_ENEMY_ADD = "Only the GM can add enemies."
    ERROR_GM_ONLY_ENCOUNTER_DAMAGE = "Only a GM can apply damage to enemies."
    ERROR_GM_ONLY_ENCOUNTER_END = "Only the GM can end the encounter."
    ERROR_NO_PENDING_ENCOUNTER = "No pending encounter found. Create one with `/encounter create`."

    # Party Settings
    PARTY_SETTINGS_UPDATED = (
        "✅ Setting **{setting}** updated to **{value}** for party '**{party_name}**'."
    )
    PARTY_SETTINGS_VIEW = (
        "⚙️ **Settings for '{party_name}'**\n"
        "Initiative Mode: **{initiative_mode}**\n"
        "Enemy AC visible to players: **{enemy_ac_public}**"
    )
    PARTY_SETTINGS_INVALID_MODE = (
        "❌ Invalid initiative mode. Choose from: `by_type`, `individual`, `shared`."
    )
    ERROR_GM_ONLY_PARTY_SETTINGS = "Only a GM of this party can change settings."


    NAT_20_ATTACK = ["Your attack connects with ruthless efficiency"]
    NAT_1_ATTACK = ["That'll be a miss", "Oops; did you intend to hit an ally? Or was that just happenstance?"]
    NAT_20_SKILLCHECK = []
    NAT_1_SKILLCHECK = []
    NAT_20_SAVE = []
    NAT_1_SAVE = []
