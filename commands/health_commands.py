import discord
from discord import app_commands
from discord.ext import commands

from database import SessionLocal
from models import Character, User, Server, Party
from utils.db_helpers import get_active_character, get_active_party, get_or_create_user_server
from utils.death_save_logic import character_is_dying
from utils.hp_logic import apply_damage, apply_healing, apply_temp_hp, parse_amount
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def register_health_commands(bot: commands.Bot) -> None:
    """Register the /hp command group."""

    hp_group = app_commands.Group(
        name="hp",
        description="Manage your character's hit points",
    )

    @hp_group.command(name="set_max", description="Set your character's maximum HP")
    @app_commands.describe(max_hp="Maximum hit points (must be at least 1)")
    async def hp_set_max(interaction: discord.Interaction, max_hp: int) -> None:
        """Set max HP and reset current HP to the new maximum."""
        logger.debug(f"Command /hp set_max called by {interaction.user.id}")
        if max_hp < 1:
            await interaction.response.send_message(
                Strings.ERROR_INVALID_MAX_HP, ephemeral=True
            )
            return
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return
            char.max_hp = max_hp
            char.current_hp = max_hp
            db.commit()
            logger.info(f"/hp set_max: {char.name} max_hp={max_hp}")
            await interaction.response.send_message(
                Strings.HP_SET_SUCCESS.format(
                    char_name=char.name, current=max_hp, max=max_hp
                ),
                ephemeral=True,
            )
        finally:
            db.close()

    @hp_group.command(name="damage", description="Apply damage to a character")
    @app_commands.describe(
        amount="Damage amount or dice formula (e.g. 10 or 2d6+3)",
        partymember="Party member name to damage (GM only)",
    )
    async def hp_damage(
        interaction: discord.Interaction, amount: str, partymember: str = None
    ) -> None:
        """Apply damage to the active character or a named party member (GM only)."""
        logger.debug(f"Command /hp damage called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if partymember:
                party = get_active_party(db, user, server)
                if not party:
                    await interaction.response.send_message(
                        Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True
                    )
                    return
                if user not in party.gms:
                    await interaction.response.send_message(
                        Strings.ERROR_GM_ONLY_DAMAGE, ephemeral=True
                    )
                    return
                char = next(
                    (c for c in party.characters if c.name == partymember), None
                )
                if not char:
                    await interaction.response.send_message(
                        Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember),
                        ephemeral=True,
                    )
                    return
            else:
                char = get_active_character(db, user, server)
                if not char:
                    await interaction.response.send_message(
                        Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                    )
                    return

            if char.max_hp < 0 or char.current_hp < 0:
                await interaction.response.send_message(
                    Strings.ERROR_HP_NOT_SET, ephemeral=True
                )
                return

            try:
                dmg = parse_amount(amount)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return

            was_dying_before = character_is_dying(char)

            new_hp, new_temp = apply_damage(char.current_hp, char.temp_hp, dmg)
            char.current_hp = new_hp
            char.temp_hp = new_temp

            death_save_msg = ""
            if was_dying_before:
                char.death_save_failures = min(char.death_save_failures + 1, 3)
                if char.death_save_failures >= 3:
                    char.death_save_failures = 0
                    char.death_save_successes = 0
                    death_save_msg = "\n" + Strings.DEATH_SAVE_DAMAGE_SLAIN.format(
                        char_name=char.name
                    )
                else:
                    death_save_msg = "\n" + Strings.DEATH_SAVE_DAMAGE_FAILURE.format(
                        char_name=char.name, failures=char.death_save_failures
                    )

            db.commit()

            msg = Strings.HP_DAMAGE_MSG.format(
                char_name=char.name,
                amount=dmg,
                current=char.current_hp,
                max=char.max_hp,
            )
            if char.temp_hp > 0:
                msg += Strings.HP_VIEW_TEMP.format(temp=char.temp_hp)

            if char.current_hp <= -char.max_hp:
                await interaction.response.send_message(
                    f"{msg}{Strings.HP_DEATH_MSG.format(char_name=char.name)}"
                )
            elif death_save_msg:
                await interaction.response.send_message(f"{msg}{death_save_msg}")
            else:
                await interaction.response.send_message(msg)

            logger.info(
                f"/hp damage: {char.name} took {dmg} damage, HP now {char.current_hp}/{char.max_hp}"
            )
        finally:
            db.close()

    @hp_group.command(name="heal", description="Heal a character")
    @app_commands.describe(
        amount="Healing amount or dice formula (e.g. 10 or 1d8+2)",
        partymember="Party member name to heal (defaults to self)",
    )
    async def hp_heal(
        interaction: discord.Interaction, amount: str, partymember: str = None
    ) -> None:
        """Heal the active character or a named party member."""
        logger.debug(f"Command /hp heal called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)

            if partymember:
                party = get_active_party(db, user, server)
                if not party:
                    await interaction.response.send_message(
                        Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True
                    )
                    return
                char = next(
                    (c for c in party.characters if c.name == partymember), None
                )
                if not char:
                    await interaction.response.send_message(
                        Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember),
                        ephemeral=True,
                    )
                    return
            else:
                char = get_active_character(db, user, server)
                if not char:
                    await interaction.response.send_message(
                        Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                    )
                    return

            if char.max_hp < 0 or char.current_hp < 0:
                await interaction.response.send_message(
                    Strings.ERROR_HP_NOT_SET, ephemeral=True
                )
                return

            try:
                healing = parse_amount(amount)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return

            was_dying = character_is_dying(char)
            char.current_hp = apply_healing(char.current_hp, char.max_hp, healing)

            death_save_reset_msg = ""
            if was_dying:
                char.death_save_successes = 0
                char.death_save_failures = 0
                death_save_reset_msg = "\n" + Strings.DEATH_SAVE_HEAL_RESET.format(
                    char_name=char.name
                )

            db.commit()

            await interaction.response.send_message(
                Strings.HP_HEAL_MSG.format(
                    char_name=char.name,
                    amount=healing,
                    current=char.current_hp,
                    max=char.max_hp,
                )
                + death_save_reset_msg
            )
            logger.info(
                f"/hp heal: {char.name} healed {healing}, HP now {char.current_hp}/{char.max_hp}"
            )
        finally:
            db.close()

    @hp_group.command(
        name="temp", description="Add temporary HP to your active character"
    )
    @app_commands.describe(amount="Temporary HP amount")
    async def hp_temp(interaction: discord.Interaction, amount: int) -> None:
        """Add temp HP to the active character (5e rule: replace if higher, keep if lower)."""
        logger.debug(f"Command /hp temp called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return
            char.temp_hp = apply_temp_hp(char.temp_hp, amount)
            db.commit()
            logger.info(f"/hp temp: {char.name} temp_hp={char.temp_hp}")
            await interaction.response.send_message(
                Strings.HP_TEMP_MSG.format(char_name=char.name, temp=char.temp_hp)
            )
        finally:
            db.close()

    @hp_group.command(
        name="party_temp",
        description="Add temporary HP to all members of your active party",
    )
    @app_commands.describe(amount="Temporary HP amount")
    async def hp_party_temp(interaction: discord.Interaction, amount: int) -> None:
        """Add temp HP to every character in the caller's active party."""
        logger.debug(f"Command /hp party_temp called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            party = get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(
                    Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True
                )
                return
            lines = []
            for char in party.characters:
                char.temp_hp = apply_temp_hp(char.temp_hp, amount)
                lines.append(
                    Strings.HP_TEMP_PARTY_LINE.format(
                        char_name=char.name, temp=char.temp_hp
                    )
                )
            db.commit()
            logger.info(
                f"/hp party_temp: updated {len(lines)} characters in '{party.name}'"
            )
            await interaction.response.send_message(
                Strings.HP_TEMP_PARTY_HEADER + "\n".join(lines)
            )
        finally:
            db.close()

    @hp_group.command(name="status", description="View your character's current HP")
    async def hp_status(interaction: discord.Interaction) -> None:
        """Display the active character's current, max, and temp HP."""
        logger.debug(f"Command /hp status called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user, server = get_or_create_user_server(db, interaction)
            char = get_active_character(db, user, server)
            if not char:
                await interaction.response.send_message(
                    Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True
                )
                return
            msg = Strings.HP_VIEW.format(
                char_name=char.name, current=char.current_hp, max=char.max_hp
            )
            if char.temp_hp:
                msg += Strings.HP_VIEW_TEMP.format(temp=char.temp_hp)
            await interaction.response.send_message(msg, ephemeral=True)
        finally:
            db.close()

    bot.tree.add_command(hp_group)
