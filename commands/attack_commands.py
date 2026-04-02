import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
import random
from database import SessionLocal
from models import (
    User,
    Server,
    Character,
    Attack,
    Party,
    Encounter,
    EncounterTurn,
    Enemy,
)
from enums.encounter_status import EncounterStatus
from dice_roller import roll_dice
from enums.crit_rule import CritRule
from utils.crit_logic import apply_crit_damage
from utils.db_helpers import (
    get_active_character,
    get_active_party,
    get_or_create_user_server,
)
from utils.encounter_utils import (
    check_and_auto_end_encounter,
    notify_gms_hp_update,
    remove_enemy_turn_from_encounter,
)
from utils.limits import MAX_ATTACKS_PER_CHARACTER
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def register_attack_commands(bot: commands.Bot) -> None:
    """Register the /attack command group (add, roll, list)."""
    attack_group = app_commands.Group(
        name="attack", description="Manage and roll attacks for your active character"
    )

    @attack_group.command(
        name="add", description="Add or update an attack on your character"
    )
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
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            roll_dice(damage_formula)  # raises ValueError on invalid formula

            if not char:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            attack = db.query(Attack).filter_by(character_id=char.id, name=name).first()
            if attack:
                attack.hit_modifier = hit_mod
                attack.damage_formula = damage_formula
                msg = Strings.ATTACK_UPDATED.format(
                    attack_name=name, char_name=char.name
                )
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
            await interaction.response.send_message(msg, ephemeral=True)
        except ValueError as e:
            logger.error(f"Error adding attack for user {interaction.user.id}: {e}")
            await interaction.response.send_message(
                Strings.ERROR_ATTACK_ADD.format(error=e), ephemeral=True
            )
        finally:
            db.close()

    @attack_group.command(name="roll", description="Perform an attack roll")
    @app_commands.describe(
        attack_name="The name of the attack to use",
        target="Enemy name from the active encounter (optional — use autocomplete)",
    )
    async def attack_roll(
        interaction: discord.Interaction,
        attack_name: str,
        target: Optional[str] = None,
    ) -> None:
        """Roll to-hit and damage for a saved attack.

        When ``target`` is provided and an encounter is active, resolves the
        attack against the enemy's AC and automatically updates their HP.
        """
        logger.debug(
            f"Command /attack roll called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id} with attack_name: {attack_name}, target: {target}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
                return

            attack_obj = (
                db.query(Attack)
                .filter_by(character_id=char.id, name=attack_name)
                .first()
            )
            if not attack_obj:
                attack_obj = next(
                    (a for a in char.attacks if a.name.lower() == attack_name.lower()),
                    None,
                )
                if not attack_obj:
                    await interaction.response.send_message(
                        Strings.ATTACK_NOT_FOUND.format(attack_name=attack_name),
                        ephemeral=True,
                    )
                    return

            d20_roll = random.randint(1, 20)
            hit_total = d20_roll + attack_obj.hit_modifier
            is_crit = d20_roll == 20

            # ----------------------------------------------------------------
            # Determine crit rule and roll damage
            # ----------------------------------------------------------------
            party = get_active_party(db, user, server)
            crit_rule = CritRule.DOUBLE_DICE
            if is_crit and party and party.settings:
                crit_rule = party.settings.crit_rule

            try:
                if is_crit:
                    crit_result = apply_crit_damage(
                        attack_obj.damage_formula, crit_rule
                    )
                    rolls = crit_result.rolls
                    modifier = crit_result.modifier
                    damage_total = crit_result.total
                    grants_inspiration = crit_result.grants_inspiration
                else:
                    rolls, modifier, damage_total = roll_dice(attack_obj.damage_formula)
                    grants_inspiration = False

                rolls_str = ", ".join(map(str, rolls))
                mod_str = f" {modifier:+d}" if modifier != 0 else ""
                damage_detail = f"({rolls_str}){mod_str}"
            except ValueError as error:
                logger.warning(
                    f"ValueError in /attack roll (damage formula: {attack_obj.damage_formula}): {error}"
                )
                await interaction.response.send_message(
                    Strings.ERROR_DAMAGE_FORMULA.format(error=str(error)),
                    ephemeral=True,
                )
                return

            crit_prefix = (
                Strings.CRIT_HIT_HEADER
                if is_crit and crit_rule != CritRule.NONE
                else ""
            )
            if grants_inspiration:
                char.inspiration = True
                db.commit()
                inspiration_suffix = Strings.CRIT_PERKINS_INSPIRATION.format(
                    char_name=char.name
                )
            else:
                inspiration_suffix = ""

            # ----------------------------------------------------------------
            # Untargeted path
            # ----------------------------------------------------------------
            if target is None:
                response = (
                    crit_prefix
                    + Strings.ATTACK_ROLL_MSG.format(
                        char_name=char.name,
                        attack_obj_name=attack_obj.name,
                        d20_roll=d20_roll,
                        hit_modifier=attack_obj.hit_modifier,
                        hit_total=hit_total,
                        damage_formula=attack_obj.damage_formula,
                        damage_detail=damage_detail,
                        damage_total=damage_total,
                    )
                    + inspiration_suffix
                )
                await interaction.response.send_message(response)
                logger.info(
                    f"/attack roll completed for user {interaction.user.id}: "
                    f"{char.name} used {attack_obj.name}"
                    + (" (CRIT)" if is_crit else "")
                )
                return

            # ----------------------------------------------------------------
            # Targeted path — resolve against encounter enemy
            # ----------------------------------------------------------------
            if not party:
                await interaction.response.send_message(
                    Strings.ATTACK_TARGET_NO_ENCOUNTER, ephemeral=True
                )
                return

            encounter = (
                db.query(Encounter)
                .filter(
                    Encounter.party_id == party.id,
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )
            if not encounter:
                await interaction.response.send_message(
                    Strings.ATTACK_TARGET_NO_ENCOUNTER, ephemeral=True
                )
                return

            target_turn = next(
                (t for t in encounter.turns if t.enemy_id and t.enemy.name == target),
                None,
            )

            if target_turn is None:
                await interaction.response.send_message(
                    Strings.ATTACK_TARGET_NOT_FOUND.format(enemy_name=target),
                    ephemeral=True,
                )
                return

            enemy = target_turn.enemy

            if enemy.ac is None:
                await interaction.response.send_message(
                    Strings.ATTACK_TARGET_NO_AC.format(enemy_name=enemy.name),
                    ephemeral=True,
                )
                return

            if is_crit or hit_total >= enemy.ac:
                # Hit (nat 20 always hits) — apply damage and notify GMs
                new_hp = max(0, enemy.current_hp - damage_total)
                enemy.current_hp = new_hp

                hit_message = (
                    crit_prefix
                    + Strings.ATTACK_ROLL_HIT_TARGET.format(
                        char_name=char.name,
                        enemy_name=enemy.name,
                        attack_name=attack_obj.name,
                        d20_roll=d20_roll,
                        hit_modifier=attack_obj.hit_modifier,
                        hit_total=hit_total,
                        ac=enemy.ac,
                        damage_formula=attack_obj.damage_formula,
                        damage_detail=damage_detail,
                        damage_total=damage_total,
                    )
                    + inspiration_suffix
                )

                if new_hp == 0:
                    remove_enemy_turn_from_encounter(db, encounter, target_turn)
                    all_enemies_defeated = check_and_auto_end_encounter(db, encounter)
                    db.commit()

                    await interaction.response.send_message(hit_message)
                    await interaction.followup.send(
                        Strings.ENCOUNTER_DAMAGE_ENEMY_DEFEATED.format(name=enemy.name)
                    )
                    if all_enemies_defeated:
                        await interaction.followup.send(
                            Strings.ENCOUNTER_ALL_ENEMIES_DEFEATED.format(
                                encounter_name=encounter.name
                            )
                        )
                        logger.info(
                            f"/attack roll: all enemies defeated, encounter '{encounter.name}' auto-ended"
                        )
                    else:
                        logger.info(
                            f"/attack roll: '{enemy.name}' defeated by "
                            f"{char.name} in '{encounter.name}'"
                        )
                    gm_message = Strings.ATTACK_GM_ENEMY_DEFEATED.format(
                        enemy_name=enemy.name,
                        char_name=char.name,
                        attack_name=attack_obj.name,
                    )
                else:
                    db.commit()
                    await interaction.response.send_message(hit_message)
                    gm_message = Strings.ATTACK_GM_DAMAGE_NOTIFY.format(
                        enemy_name=enemy.name,
                        damage=damage_total,
                        char_name=char.name,
                        attack_name=attack_obj.name,
                        current_hp=new_hp,
                        max_hp=enemy.max_hp,
                    )
                    logger.info(
                        f"/attack roll: '{enemy.name}' took {damage_total} damage "
                        f"({new_hp}/{enemy.max_hp} HP) in '{encounter.name}'"
                    )

                await notify_gms_hp_update(
                    party, gm_message, interaction.client, encounter
                )

            else:
                # Miss — no HP change
                miss_message = Strings.ATTACK_ROLL_MISS_TARGET.format(
                    char_name=char.name,
                    enemy_name=enemy.name,
                    attack_name=attack_obj.name,
                    d20_roll=d20_roll,
                    hit_modifier=attack_obj.hit_modifier,
                    hit_total=hit_total,
                    ac=enemy.ac,
                )
                await interaction.response.send_message(miss_message)
                logger.info(
                    f"/attack roll: {char.name} missed '{enemy.name}' "
                    f"(rolled {hit_total} vs AC {enemy.ac}) in '{encounter.name}'"
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
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)

            if not char or not char.attacks:
                return []

            return [
                app_commands.Choice(name=a.name, value=a.name)
                for a in char.attacks
                if current.lower() in a.name.lower()
            ][:25]
        finally:
            db.close()

    @attack_roll.autocomplete("target")
    async def attack_roll_target_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Suggest enemy names from the active encounter's initiative order."""
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = get_active_party(db, user, server)
            if not party:
                return []

            encounter = (
                db.query(Encounter)
                .filter(
                    Encounter.party_id == party.id,
                    Encounter.status == EncounterStatus.ACTIVE,
                )
                .first()
            )
            if not encounter:
                return []

            enemy_names = [
                t.enemy.name
                for t in sorted(encounter.turns, key=lambda t: t.order_position)
                if t.enemy_id
            ]
            return [
                app_commands.Choice(name=name, value=name)
                for name in enemy_names
                if current.lower() in name.lower()
            ][:25]
        finally:
            db.close()

    @attack_group.command(
        name="list", description="List all attacks for your active character"
    )
    async def attack_list(interaction: discord.Interaction) -> None:
        logger.debug(
            f"Command /attack list called by {interaction.user} (ID: {interaction.user.id}) "
            f"for guild {interaction.guild_id}"
        )
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            logger.debug(
                f"Character lookup for user {interaction.user.id}: "
                f"{'found: ' + char.name if char else 'not found'}"
            )

            if not char:
                await interaction.response.send_message(
                    Strings.CHARACTER_NOT_FOUND, ephemeral=True
                )
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

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(
                f"/attack list completed for user {interaction.user.id}: "
                f"listed {len(char.attacks)} attacks"
            )
        finally:
            db.close()

    bot.tree.add_command(attack_group)
