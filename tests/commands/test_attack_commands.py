import pytest
from models import Attack
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /add_attack
# ---------------------------------------------------------------------------

async def test_add_attack_creates_new(attack_bot, sample_character, interaction, session_factory):
    cb = get_callback(attack_bot, "add_attack")
    await cb(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+3")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "Added" in msg
    assert "Longsword" in msg

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.hit_modifier == 5
    assert attack.damage_formula == "1d8+3"
    verify.close()


async def test_add_attack_updates_existing(attack_bot, sample_character, interaction, db_session, session_factory):
    existing = Attack(character_id=sample_character.id, name="Dagger", hit_modifier=3, damage_formula="1d4+1")
    db_session.add(existing)
    db_session.commit()

    cb = get_callback(attack_bot, "add_attack")
    await cb(interaction, name="Dagger", hit_mod=7, damage_formula="1d4+5")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Updated" in msg

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Dagger").first()
    assert attack.hit_modifier == 7
    verify.close()


async def test_add_attack_invalid_formula_rejected(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "add_attack")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="notadice")

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_add_attack_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "add_attack")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="1d8")

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /attack
# ---------------------------------------------------------------------------

async def test_attack_success(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Longsword", hit_modifier=5, damage_formula="1d8+3"))
    db_session.commit()

    cb = get_callback(attack_bot, "attack")
    await cb(interaction, attack_name="Longsword")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "Aldric" in msg
    assert "Longsword" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_case_insensitive_lookup(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Longsword", hit_modifier=5, damage_formula="1d8"))
    db_session.commit()

    cb = get_callback(attack_bot, "attack")
    await cb(interaction, attack_name="longsword")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_not_found(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "attack")
    await cb(interaction, attack_name="Vorpal Blade")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_attack_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "attack")
    await cb(interaction, attack_name="Sword")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /attacks (list)
# ---------------------------------------------------------------------------

async def test_attacks_list_sends_embed(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Bow", hit_modifier=4, damage_formula="1d6+2"))
    db_session.commit()

    cb = get_callback(attack_bot, "attacks")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title


async def test_attacks_list_empty(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "attacks")
    await cb(interaction)

    msg = interaction.response.send_message.call_args.args[0]
    assert "no attacks" in msg.lower()


async def test_attacks_list_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "attacks")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

