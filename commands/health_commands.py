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


async def _execute_damage(
    interaction: discord.Interaction,
    char: Character,
    db,
    dmg: int,
    *,
    respond_by_editing: bool = False,
) -> None:
    """Apply damage to a character and send the result message.

    Args:
        interaction: The Discord interaction to respond to.
        char: The character receiving damage (already loaded in ``db``).
        db: An open SQLAlchemy session.
        dmg: The positive damage amount to apply.
        respond_by_editing: If ``True``, use ``edit_message`` instead of
            ``send_message`` — used when responding from a button callback.
    """
    was_dying_before = character_is_dying(char)
    new_hp, new_temp = apply_damage(char.current_hp, char.temp_hp, dmg)
    char.current_hp = new_hp
    char.temp_hp = new_temp

    suffix = ""
    just_downed = not was_dying_before and new_hp == 0
    if just_downed:
        if dmg >= char.max_hp:
            suffix = Strings.HP_DEATH_MSG.format(char_name=char.name)
        else:
            suffix = Strings.HP_DOWNED_MSG.format(char_name=char.name)
    elif was_dying_before:
        char.death_save_failures = min(char.death_save_failures + 1, 3)
        if char.death_save_failures >= 3:
            char.death_save_failures = 0
            char.death_save_successes = 0
            suffix = "\n" + Strings.DEATH_SAVE_DAMAGE_SLAIN.format(char_name=char.name)
        else:
            suffix = "\n" + Strings.DEATH_SAVE_DAMAGE_FAILURE.format(
                char_name=char.name, failures=char.death_save_failures
            )

    db.commit()
    logger.info(
        f"/hp damage: {char.name} took {dmg} damage, HP now {char.current_hp}/{char.max_hp}"
    )

    msg = Strings.HP_DAMAGE_MSG.format(
        char_name=char.name,
        amount=dmg,
        current=char.current_hp,
        max=char.max_hp,
    )
    if char.temp_hp > 0:
        msg += Strings.HP_VIEW_TEMP.format(temp=char.temp_hp)
    full_msg = f"{msg}{suffix}"

    if respond_by_editing:
        await interaction.response.edit_message(content=full_msg, view=None)
    else:
        await interaction.response.send_message(full_msg)


async def _execute_healing(
    interaction: discord.Interaction,
    char: Character,
    db,
    healing: int,
    *,
    respond_by_editing: bool = False,
) -> None:
    """Apply healing to a character and send the result message.

    Args:
        interaction: The Discord interaction to respond to.
        char: The character receiving healing (already loaded in ``db``).
        db: An open SQLAlchemy session.
        healing: The positive healing amount to apply.
        respond_by_editing: If ``True``, use ``edit_message`` instead of
            ``send_message`` — used when responding from a button callback.
    """
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
    logger.info(
        f"/hp heal: {char.name} healed {healing}, HP now {char.current_hp}/{char.max_hp}"
    )

    full_msg = (
        Strings.HP_HEAL_MSG.format(
            char_name=char.name,
            amount=healing,
            current=char.current_hp,
            max=char.max_hp,
        )
        + death_save_reset_msg
    )

    if respond_by_editing:
        await interaction.response.edit_message(content=full_msg, view=None)
    else:
        await interaction.response.send_message(full_msg)


class _NegativeAmountConfirmView(discord.ui.View):
    """Ephemeral confirmation shown when /hp damage or /hp heal receives a negative amount.

    Presents the absolute value and asks whether to apply it (✓ Apply) or
    discard the command (✗ Discard).

    ✓ Apply   — applies ``abs_amount`` as the intended operation.
    ✗ Discard — aborts with no changes.
    """

    def __init__(
        self, char_id: int, char_name: str, abs_amount: int, apply_as: str
    ) -> None:
        super().__init__(timeout=30)
        self.char_id = char_id
        self.char_name = char_name
        self.abs_amount = abs_amount
        self.apply_as = apply_as  # "damage" or "heal"

    @discord.ui.button(label=Strings.BUTTON_APPLY, emoji="✅", style=discord.ButtonStyle.primary)
    async def apply_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Apply the absolute amount as the intended operation."""
        db = SessionLocal()
        try:
            char = db.get(Character, self.char_id)
            if not char:
                await interaction.response.edit_message(
                    content=Strings.ERROR_CHAR_NO_LONGER_EXISTS, view=None
                )
                return
            if self.apply_as == "damage":
                await _execute_damage(
                    interaction, char, db, self.abs_amount, respond_by_editing=True
                )
            else:
                await _execute_healing(
                    interaction, char, db, self.abs_amount, respond_by_editing=True
                )
        finally:
            db.close()
        self.stop()

    @discord.ui.button(label=Strings.BUTTON_DISCARD, emoji="❌", style=discord.ButtonStyle.secondary)
    async def discard_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.HP_NEGATIVE_CANCELLED, view=None
        )
        self.stop()


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

            if dmg < 0:
                abs_amount = abs(dmg)
                view = _NegativeAmountConfirmView(
                    char_id=char.id,
                    char_name=char.name,
                    abs_amount=abs_amount,
                    apply_as="damage",
                )
                await interaction.response.send_message(
                    Strings.HP_NEGATIVE_DAMAGE_CONFIRM.format(
                        abs_amount=abs_amount, char_name=char.name
                    ),
                    view=view,
                    ephemeral=True,
                )
                return

            await _execute_damage(interaction, char, db, dmg)
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

            if healing < 0:
                abs_amount = abs(healing)
                view = _NegativeAmountConfirmView(
                    char_id=char.id,
                    char_name=char.name,
                    abs_amount=abs_amount,
                    apply_as="heal",
                )
                await interaction.response.send_message(
                    Strings.HP_NEGATIVE_HEAL_CONFIRM.format(
                        abs_amount=abs_amount, char_name=char.name
                    ),
                    view=view,
                    ephemeral=True,
                )
                return

            await _execute_healing(interaction, char, db, healing)
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
            await interaction.response.send_message(msg)
        finally:
            db.close()

    bot.tree.add_command(hp_group)
