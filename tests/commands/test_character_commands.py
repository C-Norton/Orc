import pytest
from models import Character, CharacterSkill
from enums.skill_proficiency_status import SkillProficiencyStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /create_character
# ---------------------------------------------------------------------------

async def test_create_character_success(char_bot, sample_user, sample_server, interaction, session_factory):
    cb = get_callback(char_bot, "create_character")
    await cb(interaction, name="Aldric")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "Aldric" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char is not None
    assert char.is_active is True
    verify.close()


async def test_create_character_name_too_long(char_bot, interaction):
    cb = get_callback(char_bot, "create_character")
    await cb(interaction, name="A" * 101)

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_create_character_duplicate_name(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "create_character")
    await cb(interaction, name="Aldric")  # sample_character is already named Aldric

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    assert "already have" in interaction.response.send_message.call_args.args[0]


async def test_create_character_new_char_becomes_active(char_bot, sample_character, interaction, session_factory):
    """Creating a second character should deactivate the first."""
    cb = get_callback(char_bot, "create_character")
    await cb(interaction, name="Beren")

    verify = session_factory()
    old = verify.query(Character).filter_by(name="Aldric").first()
    new = verify.query(Character).filter_by(name="Beren").first()
    assert old.is_active is False
    assert new.is_active is True
    verify.close()


async def test_create_character_auto_creates_user_record(char_bot, sample_server, session_factory):
    """A brand-new Discord user should have a User record created automatically."""
    new_user_interaction = make_interaction(user_id=999)
    cb = get_callback(char_bot, "create_character")
    await cb(new_user_interaction, name="Ghost")

    verify = session_factory()
    from models import User
    user = verify.query(User).filter_by(discord_id="999").first()
    assert user is not None
    verify.close()


# ---------------------------------------------------------------------------
# /set_stats
# ---------------------------------------------------------------------------

async def test_set_stats_first_time_requires_all_stats(char_bot, sample_character_no_stats, interaction):
    cb = get_callback(char_bot, "set_stats")
    await cb(interaction, strength=10)  # missing five stats

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    assert "first time" in interaction.response.send_message.call_args.args[0]


async def test_set_stats_first_time_success(char_bot, sample_character_no_stats, interaction, session_factory):
    cb = get_callback(char_bot, "set_stats")
    await cb(interaction, strength=16, dexterity=14, constitution=15,
             intelligence=10, wisdom=12, charisma=8)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Unnamed").first()
    assert char.strength == 16
    assert char.charisma == 8
    verify.close()


async def test_set_stats_partial_update_after_first_time(char_bot, sample_character, interaction, session_factory):
    """After stats are set, only providing one stat should update just that stat."""
    cb = get_callback(char_bot, "set_stats")
    await cb(interaction, strength=20)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.strength == 20
    assert char.dexterity == 14  # unchanged
    verify.close()


async def test_set_stats_out_of_range_rejected(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "set_stats")
    await cb(interaction, strength=31)

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_set_stats_no_character(char_bot, sample_user, sample_server, interaction):
    cb = get_callback(char_bot, "set_stats")
    await cb(interaction, strength=10, dexterity=10, constitution=10,
             intelligence=10, wisdom=10, charisma=10)

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /set_saving_throws
# ---------------------------------------------------------------------------

async def test_set_saving_throws_success(char_bot, sample_character, interaction, session_factory):
    cb = get_callback(char_bot, "set_saving_throws")
    await cb(interaction, strength=True, dexterity=True)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.st_prof_strength is True
    assert char.st_prof_dexterity is True
    assert char.st_prof_wisdom is False
    verify.close()


async def test_set_saving_throws_no_character(char_bot, sample_user, sample_server, interaction):
    cb = get_callback(char_bot, "set_saving_throws")
    await cb(interaction, strength=True)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /view_character
# ---------------------------------------------------------------------------

async def test_view_character_sends_embed(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "view_character")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title


async def test_view_character_no_character(char_bot, sample_user, sample_server, interaction):
    cb = get_callback(char_bot, "view_character")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /switch_character
# ---------------------------------------------------------------------------

async def test_switch_character_success(char_bot, sample_character, interaction, session_factory, db_session):
    # Create a second inactive character to switch to
    from models import User, Server
    user = db_session.query(User).filter_by(discord_id="111").first()
    server = db_session.query(Server).filter_by(discord_id="222").first()
    second = Character(name="Beren", user=user, server=server, is_active=False, level=1)
    db_session.add(second)
    db_session.commit()

    cb = get_callback(char_bot, "switch_character")
    await cb(interaction, name="Beren")

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Beren").first().is_active is True
    assert verify.query(Character).filter_by(name="Aldric").first().is_active is False
    verify.close()


async def test_switch_character_not_found(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "switch_character")
    await cb(interaction, name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /set_level
# ---------------------------------------------------------------------------

async def test_set_level_success(char_bot, sample_character, interaction, session_factory):
    cb = get_callback(char_bot, "set_level")
    await cb(interaction, level=10)

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Aldric").first().level == 10
    verify.close()


async def test_set_level_too_low(char_bot, interaction):
    cb = get_callback(char_bot, "set_level")
    await cb(interaction, level=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_level_too_high(char_bot, interaction):
    cb = get_callback(char_bot, "set_level")
    await cb(interaction, level=21)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /set_skill
# ---------------------------------------------------------------------------

async def test_set_skill_creates_new_entry(char_bot, sample_character, interaction, session_factory):
    cb = get_callback(char_bot, "set_skill")
    await cb(interaction, skill="Perception", status="proficient")

    verify = session_factory()
    skill = verify.query(CharacterSkill).filter_by(skill_name="Perception").first()
    assert skill.proficiency == SkillProficiencyStatus.PROFICIENT
    verify.close()


async def test_set_skill_updates_existing_entry(char_bot, sample_character, interaction, db_session, session_factory):
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Stealth",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()

    cb = get_callback(char_bot, "set_skill")
    await cb(interaction, skill="Stealth", status="expertise")

    verify = session_factory()
    updated = verify.query(CharacterSkill).filter_by(skill_name="Stealth").first()
    assert updated.proficiency == SkillProficiencyStatus.EXPERTISE
    verify.close()


async def test_set_skill_unknown_skill_sends_warning(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "set_skill")
    await cb(interaction, skill="FlyingKick", status="proficient")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /characters
# ---------------------------------------------------------------------------

async def test_characters_lists_all(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "characters")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None


async def test_characters_no_characters(char_bot, sample_user, sample_server, interaction):
    cb = get_callback(char_bot, "characters")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /delete_character
# ---------------------------------------------------------------------------

async def test_delete_character_success(char_bot, sample_character, interaction, session_factory):
    cb = get_callback(char_bot, "delete_character")
    await cb(interaction, name="Aldric")

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Aldric").first() is None
    verify.close()


async def test_delete_character_not_found(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "delete_character")
    await cb(interaction, name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
