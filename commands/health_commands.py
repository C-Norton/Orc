import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database import SessionLocal
from models import Character, User, Server, Party
from models.base import user_server_association
from utils.hp_logic import apply_damage, apply_healing, apply_temp_hp, parse_amount
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


def _get_active_party(db, user, server):
    stmt = select(user_server_association.c.active_party_id).where(
        user_server_association.c.user_id == user.id,
        user_server_association.c.server_id == server.id,
    )
    result = db.execute(stmt).fetchone()
    if result and result[0]:
        return db.get(Party, result[0])
    return None


def register_health_commands(bot: commands.Bot) -> None:

    @bot.tree.command(name="set_max_hp", description="Set your character's maximum HP")
    @app_commands.describe(max_hp="Maximum hit points (must be at least 1)")
    async def set_max_hp(interaction: discord.Interaction, max_hp: int) -> None:
        logger.debug(f"Command /set_max_hp called by {interaction.user.id}")
        if max_hp < 1:
            await interaction.response.send_message(Strings.ERROR_INVALID_MAX_HP, ephemeral=True)
            return
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return
            char.max_hp = max_hp
            char.current_hp = max_hp
            db.commit()
            logger.info(f"/set_max_hp: {char.name} max_hp={max_hp}")
            await interaction.response.send_message(Strings.HP_SET_SUCCESS.format(char_name=char.name, current=max_hp, max=max_hp))
        finally:
            db.close()

    @bot.tree.command(name="damage", description="Apply damage to a character")
    @app_commands.describe(
        amount="Damage amount or dice formula (e.g. 10 or 2d6+3)",
        partymember="Party member name to damage (GM only)",
    )
    async def damage(interaction: discord.Interaction, amount: str, partymember: str = None) -> None:
        logger.debug(f"Command /damage called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if partymember:
                party = _get_active_party(db, user, server)
                if not party:
                    await interaction.response.send_message(Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True)
                    return
                if user not in party.gms:
                    await interaction.response.send_message(
                        Strings.ERROR_GM_ONLY_DAMAGE, ephemeral=True
                    )
                    return
                char = next((c for c in party.characters if c.name == partymember), None)
                if not char:
                    await interaction.response.send_message(
                        Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember), ephemeral=True
                    )
                    return
            else:
                char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
                if not char:
                    await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                    return

            if char.max_hp < 0 or char.current_hp < 0:
                await interaction.response.send_message(Strings.ERROR_HP_NOT_SET, ephemeral=True)
                return

            try:
                dmg = parse_amount(amount)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return

            new_hp, new_temp = apply_damage(char.current_hp, char.temp_hp, dmg)
            char.current_hp = new_hp
            char.temp_hp = new_temp
            db.commit()

            msg = Strings.HP_DAMAGE_MSG.format(char_name=char.name, amount=dmg, current=char.current_hp, max=char.max_hp)
            if char.temp_hp > 0:
                msg += Strings.HP_VIEW_TEMP.format(temp=char.temp_hp)

            if char.current_hp <= -char.max_hp:
                await interaction.response.send_message(
                    f"{msg}{Strings.HP_DEATH_MSG.format(char_name=char.name)}"
                )
            else:
                await interaction.response.send_message(msg)

            logger.info(f"/damage: {char.name} took {dmg} damage, HP now {char.current_hp}/{char.max_hp}")
        finally:
            db.close()

    @bot.tree.command(name="heal", description="Heal a character")
    @app_commands.describe(
        amount="Healing amount or dice formula (e.g. 10 or 2d6+3)",
        partymember="Party member name to heal (defaults to self)",
    )
    async def heal(interaction: discord.Interaction, amount: str, partymember: str = None) -> None:
        logger.debug(f"Command /heal called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()

            if partymember:
                party = _get_active_party(db, user, server)
                if not party:
                    await interaction.response.send_message(Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True)
                    return
                char = next((c for c in party.characters if c.name == partymember), None)
                if not char:
                    await interaction.response.send_message(
                        Strings.ERROR_PARTY_MEMBER_NOT_FOUND.format(name=partymember), ephemeral=True
                    )
                    return
            else:
                char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
                if not char:
                    await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                    return

            if char.max_hp < 0 or char.current_hp < 0:
                await interaction.response.send_message(Strings.ERROR_HP_NOT_SET, ephemeral=True)
                return

            try:
                healing = parse_amount(amount)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return

            char.current_hp = apply_healing(char.current_hp, char.max_hp, healing)
            db.commit()

            await interaction.response.send_message(
                Strings.HP_HEAL_MSG.format(char_name=char.name, amount=healing, current=char.current_hp, max=char.max_hp)
            )
            logger.info(f"/heal: {char.name} healed {healing}, HP now {char.current_hp}/{char.max_hp}")
        finally:
            db.close()

    @bot.tree.command(name="add_temp_hp", description="Add temporary HP to your character")
    @app_commands.describe(amount="Temporary HP amount")
    async def add_temp_hp(interaction: discord.Interaction, amount: int) -> None:
        logger.debug(f"Command /add_temp_hp called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return
            char.temp_hp = apply_temp_hp(char.temp_hp, amount)
            db.commit()
            logger.info(f"/add_temp_hp: {char.name} temp_hp={char.temp_hp}")
            await interaction.response.send_message(Strings.HP_TEMP_MSG.format(char_name=char.name, temp=char.temp_hp))
        finally:
            db.close()

    @bot.tree.command(name="add_temp_hp_party", description="Add temporary HP to all members of your active party")
    @app_commands.describe(amount="Temporary HP amount")
    async def add_temp_hp_party(interaction: discord.Interaction, amount: int) -> None:
        logger.debug(f"Command /add_temp_hp_party called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            party = _get_active_party(db, user, server)
            if not party:
                await interaction.response.send_message(Strings.ERROR_NO_ACTIVE_PARTY, ephemeral=True)
                return
            lines = []
            for char in party.characters:
                char.temp_hp = apply_temp_hp(char.temp_hp, amount)
                lines.append(Strings.HP_TEMP_PARTY_LINE.format(char_name=char.name, temp=char.temp_hp))
            db.commit()
            logger.info(f"/add_temp_hp_party: updated {len(lines)} characters in '{party.name}'")
            await interaction.response.send_message(Strings.HP_TEMP_PARTY_HEADER + "\n".join(lines))
        finally:
            db.close()

    @bot.tree.command(name="hp", description="View your character's current HP")
    async def hp(interaction: discord.Interaction) -> None:
        logger.debug(f"Command /hp called by {interaction.user.id}")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(discord_id=str(interaction.user.id)).first()
            server = db.query(Server).filter_by(discord_id=str(interaction.guild_id)).first()
            char = db.query(Character).filter_by(user=user, server=server, is_active=True).first()
            if not char:
                await interaction.response.send_message(Strings.ACTIVE_CHARACTER_NOT_FOUND, ephemeral=True)
                return
            msg = Strings.HP_VIEW.format(char_name=char.name, current=char.current_hp, max=char.max_hp)
            if char.temp_hp:
                msg += Strings.HP_VIEW_TEMP.format(temp=char.temp_hp)
            await interaction.response.send_message(msg)
        finally:
            db.close()
