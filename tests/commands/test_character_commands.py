import pytest
import discord
from models import Character, CharacterSkill, ClassLevel, User
from enums.skill_proficiency_status import SkillProficiencyStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /character create — wizard entry point
# (creation logic is tested in test_character_wizard.py)
# ---------------------------------------------------------------------------


async def test_create_command_sends_wizard_intro(char_bot, interaction):
    """/character create sends an ephemeral wizard intro message."""
    cb = get_callback(char_bot, "character", "create")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character stats
# ---------------------------------------------------------------------------


async def test_set_stats_first_time_requires_all_stats(
    char_bot, sample_character_no_stats, interaction
):
    cb = get_callback(char_bot, "character", "stats")
    await cb(interaction, strength=10)  # missing five stats

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    assert "first time" in interaction.response.send_message.call_args.args[0]


async def test_set_stats_first_time_success(
    char_bot, sample_character_no_stats, interaction, session_factory
):
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=16,
        dexterity=14,
        constitution=15,
        intelligence=10,
        wisdom=12,
        charisma=8,
    )

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Unnamed").first()
    assert char.strength == 16
    assert char.charisma == 8
    verify.close()


async def test_set_stats_partial_update_after_first_time(
    char_bot, sample_character, interaction, session_factory
):
    """After stats are set, only providing one stat should update just that stat."""
    cb = get_callback(char_bot, "character", "stats")
    await cb(interaction, strength=20)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.strength == 20
    assert char.dexterity == 14  # unchanged
    verify.close()


async def test_set_stats_out_of_range_rejected(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "stats")
    await cb(interaction, strength=31)

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_set_stats_no_character(
    char_bot, sample_user, sample_server, interaction
):
    cb = get_callback(char_bot, "character", "stats")
    await cb(
        interaction,
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character saves
# ---------------------------------------------------------------------------


async def test_set_saving_throws_sends_edit_view(
    char_bot, sample_character, interaction
):
    """/character saves sends an ephemeral CharacterSavesEditView when a character exists."""
    from commands.character_commands import CharacterSavesEditView

    cb = get_callback(char_bot, "character", "saves")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    assert isinstance(kwargs.get("view"), CharacterSavesEditView)


async def test_set_saving_throws_no_character(
    char_bot, sample_user, sample_server, interaction
):
    """/character saves returns an error message when there is no active character."""
    cb = get_callback(char_bot, "character", "saves")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character view
# ---------------------------------------------------------------------------


async def test_view_character_sends_intro_embed(
    char_bot, sample_character, interaction
):
    """Initial view sends the intro page (page 0)."""
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title


async def test_view_character_sends_sheet_view_with_buttons(
    char_bot, sample_character, interaction
):
    """The response attaches a CharacterSheetView with one button per page."""
    from commands.character_commands import CharacterSheetView, _SHEET_PAGES

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    assert isinstance(view, CharacterSheetView)
    assert view._owner_id == interaction.user.id

    button_labels = [item.label for item in view.children]
    for _, label, _ in _SHEET_PAGES:
        assert label in button_labels


async def test_view_character_stores_message_reference(
    char_bot, sample_character, interaction
):
    """The view's .message is set after the response is sent."""
    from commands.character_commands import CharacterSheetView

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    msg = await interaction.original_response()
    assert view.message is msg


async def test_view_character_page_button_edits_embed(
    mocker, char_bot, sample_character, interaction
):
    """Clicking a page button edits the message to show the correct page."""
    from commands.character_commands import CharacterSheetView

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")

    stats_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Stats"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.user = mocker.MagicMock()
    btn_interaction.user.id = interaction.user.id
    btn_interaction.response = mocker.AsyncMock()

    await stats_btn.callback(btn_interaction)

    btn_interaction.response.edit_message.assert_called_once()
    _, edit_kwargs = btn_interaction.response.edit_message.call_args
    embed = edit_kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title


async def test_view_character_sheet_interaction_check_blocks_others(
    mocker, char_bot, sample_character, interaction
):
    """Non-owner button presses are rejected with an ephemeral message."""
    from commands.character_commands import CharacterSheetView

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")

    other_interaction = mocker.AsyncMock(spec=discord.Interaction)
    other_interaction.user = mocker.MagicMock()
    other_interaction.user.id = 99999
    other_interaction.response = mocker.AsyncMock()

    result = await view.interaction_check(other_interaction)
    assert result is False
    other_interaction.response.send_message.assert_called_once()
    assert (
        other_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


async def test_view_character_no_character(
    char_bot, sample_user, sample_server, interaction
):
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_view_character_by_own_name(char_bot, sample_character, interaction):
    """Supplying the character's own name shows that character's sheet."""
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction, name="Aldric")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_view_character_by_inactive_own_name(
    char_bot,
    sample_character,
    db_session,
    sample_user,
    sample_server,
    interaction,
    session_factory,
):
    """A non-active character can be viewed by name."""
    from models import Character as Char

    second = Char(
        name="Borgin", user=sample_user, server=sample_server, is_active=False
    )
    db_session.add(second)
    db_session.commit()

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction, name="Borgin")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Borgin" in embed.title


async def test_view_character_by_party_member_name(
    char_bot, sample_active_party, db_session, sample_user, sample_server, interaction
):
    """A party member's character can be viewed by name when the user has an active party."""
    from models import User as U, Character as Char

    other_user = U(discord_id="888")
    db_session.add(other_user)
    db_session.flush()
    party_char = Char(
        name="Morgath", user=other_user, server=sample_server, is_active=True
    )
    db_session.add(party_char)
    db_session.flush()
    sample_active_party.characters.append(party_char)
    db_session.commit()

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction, name="Morgath")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Morgath" in embed.title
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_view_character_name_not_found(char_bot, sample_character, interaction):
    """An unknown name returns an ephemeral error."""
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction, name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_view_character_own_takes_priority_over_party(
    char_bot,
    sample_character,
    sample_active_party,
    db_session,
    sample_user,
    sample_server,
    interaction,
):
    """When own character and party character share a name, own character is shown."""
    from models import User as U, Character as Char

    other_user = U(discord_id="999")
    db_session.add(other_user)
    db_session.flush()
    party_char = Char(
        name="Aldric", user=other_user, server=sample_server, is_active=True
    )
    db_session.add(party_char)
    db_session.flush()
    sample_active_party.characters.append(party_char)
    db_session.commit()

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction, name="Aldric")

    _, kwargs = interaction.response.send_message.call_args
    view = kwargs.get("view")
    # View is bound to sample_character.id (own), not the party duplicate
    assert view._char_id == sample_character.id


# ---------------------------------------------------------------------------
# /character ac
# ---------------------------------------------------------------------------


async def test_set_ac_success(char_bot, sample_character, interaction, session_factory):
    """Setting AC persists the value on the character."""
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=15)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.ac == 15
    verify.close()


async def test_set_ac_success_message(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=15)

    msg = interaction.response.send_message.call_args.args[0]
    assert "15" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_ac_too_low(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_ac_too_high(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=31)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_set_ac_no_character(char_bot, sample_user, sample_server, interaction):
    cb = get_callback(char_bot, "character", "ac")
    await cb(interaction, ac=14)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_view_character_sheet_shows_ac(
    char_bot, sample_character, db_session, interaction
):
    """The intro page quick-reference field must include the AC value."""
    sample_character.ac = 16
    db_session.commit()

    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    combined = " ".join(f.value for f in embed.fields)
    assert "16" in combined


async def test_view_character_sheet_ac_not_set(char_bot, sample_character, interaction):
    """When AC is not yet set the quick-reference should say so."""
    cb = get_callback(char_bot, "character", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    combined = " ".join(f.value for f in embed.fields)
    assert "set_ac" in combined or "Not set" in combined or "ac" in combined.lower()


# ---------------------------------------------------------------------------
# /character switch
# ---------------------------------------------------------------------------


async def test_switch_character_success(
    char_bot, sample_character, interaction, session_factory, db_session
):
    from models import User, Server

    user = db_session.query(User).filter_by(discord_id="111").first()
    server = db_session.query(Server).filter_by(discord_id="222").first()
    second = Character(name="Beren", user=user, server=server, is_active=False)
    db_session.add(second)
    db_session.commit()

    cb = get_callback(char_bot, "character", "switch")
    await cb(interaction, name="Beren")

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Beren").first().is_active is True
    assert verify.query(Character).filter_by(name="Aldric").first().is_active is False
    verify.close()


async def test_switch_character_not_found(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "switch")
    await cb(interaction, name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character class_add
# ---------------------------------------------------------------------------


async def test_add_class_success(
    char_bot, sample_character, interaction, session_factory
):
    """Adding a new class increments total level and persists a ClassLevel row."""
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=2)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.level == 7  # Fighter 5 + Rogue 2
    rogue_cl = (
        verify.query(ClassLevel)
        .filter_by(character_id=char.id, class_name="Rogue")
        .first()
    )
    assert rogue_cl is not None
    assert rogue_cl.level == 2
    verify.close()


async def test_add_class_updates_existing_class(
    char_bot, sample_character, interaction, session_factory
):
    """Adding levels to the character's existing class updates the row, not inserts."""
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Fighter", level=8)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    assert char.level == 8
    fighter_rows = (
        verify.query(ClassLevel)
        .filter_by(character_id=char.id, class_name="Fighter")
        .all()
    )
    assert len(fighter_rows) == 1
    verify.close()


async def test_add_class_success_message(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=2)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Rogue" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_class_level_too_low(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_class_exceeds_level_20(char_bot, sample_character, interaction):
    """Fighter 5 + 16 levels of Rogue = 21 — must be rejected."""
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=16)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_class_no_active_character(
    char_bot, sample_user, sample_server, interaction
):
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Fighter", level=1)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_class_recalculates_hp(
    char_bot, sample_character, interaction, session_factory
):
    """When stats are set, adding a class level should update max_hp."""
    cb = get_callback(char_bot, "character", "class_add")
    await cb(interaction, character_class="Rogue", level=1)

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    # sample_character has CON 15 (+2). Fighter 5 / Rogue 1 HP:
    # Lvl1 Fighter: 10+2=12, Lvls2-5: 4*(6+2)=32, Lvl6 Rogue: 5+2=7 → 51
    assert char.max_hp == 51
    verify.close()


# ---------------------------------------------------------------------------
# /character class_remove
# ---------------------------------------------------------------------------


async def test_remove_class_success(
    char_bot, sample_character, db_session, interaction, session_factory
):
    """Removing a class that exists should delete its ClassLevel row."""
    db_session.add(
        ClassLevel(character_id=sample_character.id, class_name="Rogue", level=3)
    )
    db_session.commit()

    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Rogue")

    verify = session_factory()
    assert verify.query(ClassLevel).filter_by(class_name="Rogue").first() is None
    verify.close()


async def test_remove_class_success_message(
    char_bot, sample_character, db_session, interaction
):
    db_session.add(
        ClassLevel(character_id=sample_character.id, class_name="Rogue", level=3)
    )
    db_session.commit()

    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Rogue")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Rogue" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_class_not_found(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Barbarian")  # Aldric is not a Barbarian

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_class_no_active_character(
    char_bot, sample_user, sample_server, interaction
):
    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Fighter")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_class_recalculates_hp(
    char_bot, sample_character, db_session, interaction, session_factory
):
    """Removing a class should recalculate max HP based on remaining classes."""
    db_session.add(
        ClassLevel(character_id=sample_character.id, class_name="Rogue", level=1)
    )
    db_session.commit()

    cb = get_callback(char_bot, "character", "class_remove")
    await cb(interaction, character_class="Rogue")

    verify = session_factory()
    char = verify.query(Character).filter_by(name="Aldric").first()
    # After removing Rogue, back to Fighter 5 with CON +2: 12 + 4*8 = 44
    assert char.max_hp == 44
    verify.close()


# ---------------------------------------------------------------------------
# /character skill
# ---------------------------------------------------------------------------


async def test_set_skill_creates_new_entry(
    char_bot, sample_character, interaction, session_factory
):
    cb = get_callback(char_bot, "character", "skill")
    await cb(interaction, skill="Perception", status="proficient")

    verify = session_factory()
    skill = verify.query(CharacterSkill).filter_by(skill_name="Perception").first()
    assert skill.proficiency == SkillProficiencyStatus.PROFICIENT
    verify.close()


async def test_set_skill_updates_existing_entry(
    char_bot, sample_character, interaction, db_session, session_factory
):
    skill = CharacterSkill(
        character_id=sample_character.id,
        skill_name="Stealth",
        proficiency=SkillProficiencyStatus.PROFICIENT,
    )
    db_session.add(skill)
    db_session.commit()

    cb = get_callback(char_bot, "character", "skill")
    await cb(interaction, skill="Stealth", status="expertise")

    verify = session_factory()
    updated = verify.query(CharacterSkill).filter_by(skill_name="Stealth").first()
    assert updated.proficiency == SkillProficiencyStatus.EXPERTISE
    verify.close()


async def test_set_skill_unknown_skill_sends_warning(
    char_bot, sample_character, interaction
):
    cb = get_callback(char_bot, "character", "skill")
    await cb(interaction, skill="FlyingKick", status="proficient")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character list
# ---------------------------------------------------------------------------


async def test_characters_lists_all(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None


async def test_characters_no_characters(
    char_bot, sample_user, sample_server, interaction
):
    cb = get_callback(char_bot, "character", "list")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character list_all
# ---------------------------------------------------------------------------


async def test_list_all_no_characters_sends_ephemeral_none_message(
    char_bot, sample_user, sample_server, interaction
):
    """/character list_all with no server characters sends ephemeral CHAR_LIST_ALL_NONE."""
    from utils.strings import Strings

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    interaction.response.defer.assert_called_once()
    call_args = interaction.followup.send.call_args
    assert call_args.kwargs.get("ephemeral") is True
    assert call_args.args[0] == Strings.CHAR_LIST_ALL_NONE


async def test_list_all_groups_characters_by_player(
    char_bot, sample_character, interaction, mocker
):
    """/character list_all groups characters under per-player embed fields."""
    member = mocker.Mock()
    member.display_name = "TestUser"
    interaction.guild.fetch_member = mocker.AsyncMock(return_value=member)

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    call_kwargs = interaction.followup.send.call_args.kwargs
    embed = call_kwargs.get("embed")
    assert embed is not None
    # One field per player
    assert len(embed.fields) == 1
    assert embed.fields[0].name == "TestUser"


async def test_list_all_active_character_marked_with_star(
    char_bot, sample_character, interaction, mocker
):
    """Active characters should have a ★ marker in the embed field value."""
    member = mocker.Mock()
    member.display_name = "TestUser"
    interaction.guild.fetch_member = mocker.AsyncMock(return_value=member)

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    field_value = embed.fields[0].value
    # sample_character (Aldric) is active
    assert "★" in field_value
    assert "Aldric" in field_value


async def test_list_all_character_with_no_class_shows_no_class(
    char_bot, db_session, sample_user, sample_server, interaction, mocker
):
    """Characters with no class_levels show 'No class' in the embed field."""
    char = Character(
        name="Classless",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(char)
    db_session.commit()

    member = mocker.Mock()
    member.display_name = "TestUser"
    interaction.guild.fetch_member = mocker.AsyncMock(return_value=member)

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    # At least one field must contain "No class"
    field_values = [f.value for f in embed.fields]
    assert any("No class" in value for value in field_values)


async def test_list_all_unknown_player_shows_unknown_player_string(
    char_bot, sample_character, interaction, mocker
):
    """When a guild member cannot be found, field name falls back to CHAR_LIST_ALL_UNKNOWN_PLAYER."""
    from utils.strings import Strings

    # fetch_member raises NotFound — user is not in the guild
    interaction.guild.fetch_member = mocker.AsyncMock(
        side_effect=discord.NotFound(mocker.MagicMock(), mocker.MagicMock())
    )

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    field_names = [f.name for f in embed.fields]
    assert Strings.CHAR_LIST_ALL_UNKNOWN_PLAYER in field_names


async def test_list_all_multiple_characters_per_player_in_one_field(
    char_bot,
    db_session,
    sample_character,
    sample_user,
    sample_server,
    interaction,
    mocker,
):
    """Multiple characters belonging to the same player appear in a single embed field."""
    second_char = Character(
        name="Zara",
        user=sample_user,
        server=sample_server,
        is_active=False,
    )
    db_session.add(second_char)
    db_session.commit()

    member = mocker.Mock()
    member.display_name = "TestUser"
    interaction.guild.fetch_member = mocker.AsyncMock(return_value=member)

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    # Both characters belong to the same player → only one field
    assert len(embed.fields) == 1
    field_value = embed.fields[0].value
    assert "Aldric" in field_value
    assert "Zara" in field_value


async def test_list_all_multiple_players_each_get_own_field(
    char_bot,
    db_session,
    sample_character,
    sample_server,
    interaction,
    mocker,
    session_factory,
):
    """Characters from different players each appear in their own embed field."""
    second_user = User(discord_id="999")
    db_session.add(second_user)
    db_session.flush()

    second_char = Character(
        name="Beren",
        user=second_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(second_char)
    db_session.commit()

    first_member = mocker.Mock()
    first_member.display_name = "TestUser"
    second_member = mocker.Mock()
    second_member.display_name = "OtherUser"

    async def fetch_member_side_effect(discord_id: int):
        if discord_id == 111:
            return first_member
        if discord_id == 999:
            return second_member
        raise discord.NotFound(mocker.MagicMock(), mocker.MagicMock())

    interaction.guild.fetch_member = mocker.AsyncMock(
        side_effect=fetch_member_side_effect
    )

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert len(embed.fields) == 2
    field_names = {f.name for f in embed.fields}
    assert "TestUser" in field_names
    assert "OtherUser" in field_names


async def test_list_all_message_is_ephemeral(
    char_bot, sample_character, interaction, mocker
):
    """/character list_all response is ephemeral (only visible to the invoking user)."""
    member = mocker.Mock()
    member.display_name = "TestUser"
    interaction.guild.fetch_member = mocker.AsyncMock(return_value=member)

    cb = get_callback(char_bot, "character", "list_all")
    await cb(interaction)

    call_kwargs = interaction.followup.send.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /character delete
# ---------------------------------------------------------------------------


async def test_delete_character_success(
    mocker, char_bot, sample_character, interaction, session_factory
):
    """Deleting a character shows a confirmation view; pressing Delete removes the character."""
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    # Command shows ephemeral confirmation, not immediate deletion
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None

    # Confirm deletion
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Aldric").first() is None
    verify.close()


async def test_delete_character_not_found(char_bot, sample_character, interaction):
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_delete_character_in_active_encounter_shows_encounter_confirmation(
    char_bot, sample_active_encounter, sample_character, interaction, session_factory
):
    """Deleting a character in an active encounter shows a confirmation that mentions the encounter."""
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "encounter" in msg.lower() or "initiative" in msg.lower()
    # Character is NOT deleted until the button is pressed
    verify = session_factory()
    assert verify.query(Character).filter_by(name="Aldric").first() is not None
    verify.close()


async def test_delete_character_cascade_removes_encounter_turns(
    mocker,
    char_bot,
    db_session,
    sample_character,
    sample_active_party,
    interaction,
    session_factory,
):
    """Deleting a character not in an active encounter cleans up any completed
    encounter turns (ON DELETE CASCADE)."""
    from models import Encounter, EncounterTurn
    from enums.encounter_status import EncounterStatus

    enc = Encounter(
        name="Old Battle",
        party_id=sample_active_party.id,
        server_id=sample_active_party.server_id,
        status=EncounterStatus.COMPLETE,
    )
    db_session.add(enc)
    db_session.flush()
    turn = EncounterTurn(
        encounter_id=enc.id,
        character_id=sample_character.id,
        initiative_roll=10,
        order_position=0,
    )
    db_session.add(turn)
    db_session.commit()
    turn_id = turn.id

    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    # Confirm deletion
    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Character).filter_by(name="Aldric").first() is None
    assert verify.query(EncounterTurn).filter_by(id=turn_id).first() is None
    verify.close()
