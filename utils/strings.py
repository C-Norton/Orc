class Strings:
    # Common
    CHARACTER_NOT_FOUND = "You don't have a character in this server. Use `/create_character` first."
    ACTIVE_CHARACTER_NOT_FOUND = "You don't have an active character."
    SERVER_ERROR = "❌ An unexpected error occurred."
    
    # Meta Commands
    HELP_TITLE = "Thank you for using [ORC](https://github.com/C-Norton/orc) (the Open-Source Roleplaying Companion) bot for D&D 5e"
    HELP_DESCRIPTION = "Check out our shared setting: [Open Source Gaming and Roleplaying environment (OGRE)](https://www.worldanvil.com/w/open-source-gaming-and-roleplaying-environment-wobbix/)"
    HELP_FOOTER = "Tip: Use autocomplete for character, party, and skill names!"
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
        "**/create_character <name>**: Create a new character for this server.\n"
        "**/characters**: View all your characters in this server.\n"
        "**/view_character**: See your active character's stats, skills, and saving throws.\n"
        "**/switch_character <name>**: Change which character is currently active.\n"
        "**/delete_character <name>**: Permanently delete one of your characters.\n"
        "**/set_level <level>**: Set your active character's level (1-20).\n"
        "**/set_stats**: Set your active character's 6 core ability scores, and initiative bonus.\n"
        "**/set_saving_throws**: Mark which saves your active character is proficient in.\n"
        "**/set_skill <skill> <status>**: Set proficiency for your active character."
    )
    
    HELP_COMBAT_NAME = "⚔️ Combat"
    HELP_COMBAT_VALUE = (
        "**/add_attack <name> <hit_mod> <damage>**: Save an attack (e.g., `/add_attack Longsword 5 1d8+3`).\n"
        "**/attacks**: List all your saved attacks.\n"
        "**/attack <name>**: Roll a to-hit and damage roll for a saved attack."
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
        "**/create_party <name>**: Create a new group of characters.\n"
        "**/party_add <party> <character>**: Add a character to a party (GM only).\n"
        "**/active_party <name>**: Set your current active party for quick rolling.\n"
        "**/rollas <member> <notation>**: Roll as a member of your active party.\n"
        "**/partyroll <notation>**: Roll for every member of your active party at once (e.g., `/partyroll stealth`).\n"
        "**/add_gm <party> <user>**: Add a Discord user as a GM of a party (GM only).\n"
        "**/remove_gm <party> <user>**: Remove a Discord user as a GM of a party (GM only).\n"
        "**/delete_party <name>**: Delete a party (GM only)."
    )
    
    HELP_ENCOUNTER_NAME = "⚔️ Encounter & Initiative Tracking"
    HELP_ENCOUNTER_VALUE = (
        "**Setup (GM only)**\n"
        "**/create_encounter <name>**: Open a new encounter for your active party.\n"
        "**/add_enemy <name> <init_mod> <max_hp>**: Add an enemy before combat starts. Repeat for each enemy.\n"
        "**/start_encounter**: Roll initiative for all party members and enemies, post the turn order, and ping whoever acts first.\n"
        "\n"
        "**During Combat**\n"
        "**/next_turn**: End the current turn and advance the order. Can only be used by the player whose turn it is, or the GM. "
        "The bot will edit the live turn-order message to show the new current actor and ping them. "
        "The round counter increments automatically when the order wraps.\n"
        "**/view_encounter**: Show the current initiative order and round number at any time.\n"
        "\n"
        "**Ending Combat**\n"
        "**/end_encounter**: Mark the encounter complete (GM only).\n"
        "\n"
        "**Turn order** is determined by each character's initiative roll (d20 + DEX modifier, or a custom bonus set with `/set_stats`). "
        "Enemies use their initiative modifier. Tied rolls give priority to players."
    )

    HELP_GETTING_STARTED_NAME = "⭐ QuickStart Guide"
    HELP_GETTING_STARTED_VALUE = (
        "**FOR PLAYERS**\n"
        "You can roll at any time with `/roll <dice notation>`.\n"
        "If you want to store a character sheet in ORC, you'll need a character.\n"
        "To get started, create a character with `/create_character` and set their stats with `/set_stats`.\n"
        "For accurate rolls, set your character's proficiencies with `/set_skill` and `/set_saving_throws`.\n"
        "Finally, set your Max HP with `/set_max_hp`.\n"
        "**FOR GMs**\n"
        "It is recommended that you read all pages of the help command.\n"
        "That said for the very basics, if you want to create a party, do /create_party, and add characters with /party_add.\n"
        "Once you have a party, you can create encounters with /create_encounter.\n"
        "Add monsters with /add_enemy\n"
        "Roll initiative and start the encounter with /start_encounter"
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
    ATTACK_NO_ATTACKS = "**{char_name}** has no attacks saved. Use `/add_attack` to add some!"
    ATTACK_LIST_TITLE = "Attacks for {char_name}"
    ATTACK_ROLL_MSG = "⚔️ **{char_name}** attacks with **{attack_obj_name}**!\n**To Hit**: `d20({d20_roll}) + {hit_modifier}` = **{hit_total}**\n**Damage**: `{damage_formula}` -> `{damage_detail}` = **{damage_total}**"
    
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
    CHAR_CREATED_ACTIVE = "Character **{name}** created successfully at level **{level}** and set as active!\nNext, set your stats with '/set_stats', your skill proficiencies with 'set_skill', your saving throw proficiencies with '/set_saving_throws'\n View your character at any time with '/view_character', and switch with '/switch_character'"
    CHAR_STATS_FIRST_TIME = "This is your first time setting stats for this character. Please provide all core stats (strength, dexterity, constitution, intelligence, wisdom, charisma)."
    CHAR_STAT_LIMIT = "{stat_name} score must be between 1 and 30."
    CHAR_STATS_UPDATED = "Stats updated for **{char_name}**!"
    CHAR_SAVES_UPDATED = "Saving throw proficiencies updated for **{char_name}**!"
    CHAR_VIEW_TITLE = "👤 {char_name}"
    CHAR_VIEW_DESC = "Level {char_level} Character"
    CHAR_VIEW_INIT = "\n**Initiative:** {init_bonus:+d}"
    CHAR_VIEW_STATS_FIELD = "Ability Scores"
    CHAR_VIEW_SAVES_FIELD = "Saving throws"
    CHAR_VIEW_SKILLS_FIELD = "Skills"
    CHAR_VIEW_SKILLS_CONT_FIELD = "Skills (cont.)"
    CHAR_SWITCH_SUCCESS = "Switched to character **{name}**!"
    CHAR_LEVEL_LIMIT = "Level must be between 1 and 20."
    CHAR_LEVEL_UPDATED = "**{char_name}** is now level **{level}**!"
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
    ERROR_PARTY_SET_ACTIVE_FIRST = "Set an active party first with `/active_party`."

    # Encounter Commands
    ENCOUNTER_ORDER_HEADER = "⚔️ **{name}** | Round {round_number}"
    ENCOUNTER_TURN_PING = "{ping} It is now **{name}**'s turn. When you have described your actions and made your rolls, end your turn with `/next_turn`."
    ENCOUNTER_CREATED = "⚔️ Encounter **{name}** created! Add enemies with `/add_enemy`, then start combat with `/start_encounter`."
    ENCOUNTER_ALREADY_OPEN = "This party already has an open encounter. End it with `/end_encounter` first."
    ENCOUNTER_ENEMY_ADDED = "Added **{name}** (Initiative +{init_mod}, HP {hp}) to **{encounter_name}**."
    ENCOUNTER_ALREADY_STARTED = "The encounter has already started."
    ENCOUNTER_NOT_STARTED = "Enemies can only be added before the encounter starts."
    ENCOUNTER_NO_ENEMIES = "Add at least one enemy with `/add_enemy` before starting."
    ENCOUNTER_PARTY_NO_MEMBERS = "The party has no members."
    ENCOUNTER_NOT_ACTIVE = "There is no active encounter on this server."
    ENCOUNTER_NEXT_TURN_DENIED = "You can only use `/next_turn` on your own turn, or if you are the GM."
    ENCOUNTER_TURN_ADVANCED = "Turn advanced."
    ENCOUNTER_ENDED = "⚔️ Encounter **{encounter_name}** has ended."
    ENCOUNTER_NO_ACTIVE_TO_END = "No active encounter to end."
    ENCOUNTER_VIEW_TITLE = "⚔️ {name}"
    ENCOUNTER_VIEW_DESC = "Round {round_number}"
    ENCOUNTER_VIEW_ORDER_FIELD = "Initiative Order"
    
    ERROR_GM_ONLY_ENCOUNTER_CREATE = "Only the GM of the party can create an encounter."
    ERROR_GM_ONLY_ENEMY_ADD = "Only the GM can add enemies."
    ERROR_GM_ONLY_ENCOUNTER_END = "Only the GM can end the encounter."
    ERROR_NO_PENDING_ENCOUNTER = "No pending encounter found. Create one with `/create_encounter`."


    NAT_20_ATTACK = ["Your attack connects with ruthless efficiency"]
    NAT_1_ATTACK = ["That'll be a miss", "Oops; did you intend to hit an ally? Or was that just happenstance?"]
    NAT_20_SKILLCHECK = []
    NAT_1_SKILLCHECK = []
    NAT_20_SAVE = []
    NAT_1_SAVE = []
