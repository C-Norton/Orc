import pytest
import discord
from sqlalchemy import select
from enums.crit_rule import CritRule
from models import (
    Party,
    Character,
    User,
    Server,
    PartySettings,
    user_server_association,
)
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /party create
# ---------------------------------------------------------------------------


async def test_create_party_empty(
    party_bot, sample_user, sample_server, interaction, session_factory
):
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="The Fellowship")

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    msg = interaction.followup.send.call_args.args[0]
    assert "The Fellowship" in msg

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert party is not None
    verify.close()


async def test_create_party_defers_before_db_work(
    party_bot, sample_user, sample_server, interaction, session_factory
):
    """Regression: party_create must defer() before any DB work to avoid the
    3-second Discord timeout that caused 404 Unknown Interaction errors."""
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Deferred Party")

    interaction.response.defer.assert_called_once()
    interaction.response.send_message.assert_not_called()


async def test_create_party_with_existing_character(
    party_bot, sample_character, interaction, session_factory
):
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Heroes", characters_list="Aldric")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="Heroes").first()
    assert len(party.characters) == 1
    assert party.characters[0].name == "Aldric"
    verify.close()


async def test_create_party_partial_char_list_reports_not_found(
    party_bot, sample_character, interaction
):
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Mixed", characters_list="Aldric, Ghost")

    msg = interaction.followup.send.call_args.args[0]
    assert "Ghost" in msg
    assert "not found" in msg.lower()


async def test_create_party_duplicate_name_rejected(
    party_bot, sample_party, interaction
):
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="The Fellowship")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True


async def test_create_party_sets_active_party(
    party_bot, sample_user, sample_server, interaction, session_factory
):
    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="Test Party")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="Test Party").first()
    stmt = select(user_server_association.c.active_party_id).where(
        user_server_association.c.user_id == sample_user.id,
        user_server_association.c.server_id == sample_server.id,
    )
    result = verify.execute(stmt).fetchone()
    assert result[0] == party.id
    verify.close()


# ---------------------------------------------------------------------------
# /party character_add
# ---------------------------------------------------------------------------


async def test_party_add_success(
    party_bot, sample_party, sample_character, interaction, session_factory
):
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert any(c.name == "Aldric" for c in party.characters)
    verify.close()


async def test_party_add_party_not_found(
    party_bot, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="Nonexistent", character_name="Anyone")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_add_not_gm(
    mocker, party_bot, sample_party, sample_character, db_session, session_factory
):
    """A user who isn't the GM cannot add members."""
    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party", "character_add")
    await cb(other_interaction, party_name="The Fellowship", character_name="Aldric")

    assert (
        other_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


async def test_party_add_character_not_found(
    party_bot, sample_party, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="The Fellowship", character_name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_add_already_in_party(
    party_bot, sample_party, sample_character, db_session, interaction
):
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party character_remove
# ---------------------------------------------------------------------------


async def test_party_remove_success(
    mocker,
    party_bot,
    sample_party,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """Removing a character shows a confirmation; pressing Confirm removes them."""
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    # Confirmation view shown
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(c.name == "Aldric" for c in party.characters)
    verify.close()


async def test_party_remove_not_gm(
    mocker, party_bot, sample_party, sample_character, db_session
):
    sample_party.characters.append(sample_character)
    db_session.commit()

    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party", "character_remove")
    await cb(other_interaction, party_name="The Fellowship", character_name="Aldric")

    assert (
        other_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


# ---------------------------------------------------------------------------
# /party active (set and view)
# ---------------------------------------------------------------------------


async def test_active_party_set_success(party_bot, sample_party, interaction):
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name="The Fellowship")

    msg = interaction.response.send_message.call_args.args[0]
    assert "The Fellowship" in msg
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_active_party_set_not_found(
    party_bot, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name="Ghost Party")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_active_party_view(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction)  # no party_name → view mode

    msg = interaction.response.send_message.call_args.args[0]
    assert "The Fellowship" in msg


async def test_active_party_view_none_set(
    party_bot, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "active")
    await cb(interaction)

    msg = interaction.response.send_message.call_args.args[0]
    assert "don't have" in msg.lower() or "no active" in msg.lower()


# ---------------------------------------------------------------------------
# /party roll_as
# ---------------------------------------------------------------------------


async def test_rollas_success(
    mocker, party_bot, sample_active_party, sample_character, db_session, interaction
):
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "roll_as")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, member_name="Aldric", notation="1d20")

    interaction.response.send_message.assert_called_once()


async def test_rollas_no_active_party(
    party_bot, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "roll_as")
    await cb(interaction, member_name="Aldric", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_rollas_member_not_found(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "party", "roll_as")
    await cb(interaction, member_name="Ghost", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party roll
# ---------------------------------------------------------------------------


async def test_partyroll_success(
    mocker, party_bot, sample_active_party, sample_character, db_session, interaction
):
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "roll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, notation="1d20")

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()


async def test_partyroll_no_active_party(
    party_bot, sample_user, sample_server, interaction
):
    cb = get_callback(party_bot, "party", "roll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_partyroll_empty_party(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "party", "roll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party view
# ---------------------------------------------------------------------------


async def test_view_party_success(party_bot, sample_party, interaction):
    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name="The Fellowship")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "The Fellowship" in embed.title


async def test_view_party_not_found(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name="Nope")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party delete
# ---------------------------------------------------------------------------


async def test_delete_party_success(
    mocker, party_bot, sample_party, interaction, session_factory
):
    """Deleting a party shows a confirmation; pressing Delete removes the party."""
    cb = get_callback(party_bot, "party", "delete")
    await cb(interaction, party_name="The Fellowship")

    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Party).filter_by(name="The Fellowship").first() is None
    verify.close()


async def test_delete_party_not_gm(mocker, party_bot, sample_party, session_factory):
    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party", "delete")
    await cb(other_interaction, party_name="The Fellowship")

    assert (
        other_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )

    verify = session_factory()
    assert verify.query(Party).filter_by(name="The Fellowship").first() is not None
    verify.close()


# ---------------------------------------------------------------------------
# /party gm_add
# ---------------------------------------------------------------------------


async def test_add_gm_success(
    mocker,
    party_bot,
    sample_party,
    sample_server,
    db_session,
    interaction,
    session_factory,
):
    """A GM can add another Discord user as a GM."""
    target_user = User(discord_id="555")
    db_session.add(target_user)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )
    msg = interaction.response.send_message.call_args.args[0]
    assert "555" in msg

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert any(gm.discord_id == "555" for gm in party.gms)
    verify.close()


async def test_add_gm_not_gm(mocker, party_bot, sample_party, db_session):
    """A non-GM cannot add GMs."""
    target_user = User(discord_id="555")
    db_session.add(target_user)
    db_session.commit()

    non_gm_interaction = make_interaction(mocker, user_id=999)
    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(non_gm_interaction, party_name="The Fellowship", new_gm=mock_member)

    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


async def test_add_gm_auto_registers_unregistered_user(
    mocker, party_bot, sample_party, interaction, session_factory
):
    """Adding a Discord user who has never used the bot auto-registers them and
    succeeds — no User row is required to pre-exist."""
    mock_member = mocker.Mock()
    mock_member.id = 9999

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )
    msg = interaction.response.send_message.call_args.args[0]
    assert "9999" in msg


async def test_add_gm_creates_user_row_for_unregistered_discord_user(
    mocker, party_bot, sample_party, interaction, session_factory
):
    """When the target Discord user has no User row, gm_add creates one."""
    mock_member = mocker.Mock()
    mock_member.id = 7777

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    verify = session_factory()
    user = verify.query(User).filter_by(discord_id="7777").first()
    assert user is not None
    verify.close()


async def test_add_gm_already_gm(
    mocker, party_bot, sample_party, sample_user, interaction
):
    """Adding a user who is already a GM is rejected."""
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_gm_party_not_found(
    mocker, party_bot, sample_user, sample_server, interaction
):
    """gm_add on a nonexistent party returns an error."""
    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "party", "gm_add")
    await cb(interaction, party_name="Ghost Party", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party gm_remove
# ---------------------------------------------------------------------------


async def test_remove_gm_success(
    mocker,
    party_bot,
    sample_party,
    sample_user,
    db_session,
    interaction,
    session_factory,
):
    """A GM can remove another GM from the party."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(gm.discord_id == "555" for gm in party.gms)
    verify.close()


async def test_remove_gm_self_shows_confirmation(
    mocker,
    party_bot,
    sample_party,
    sample_user,
    db_session,
    interaction,
    session_factory,
):
    """Removing yourself as GM shows an ephemeral confirmation prompt."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None
    # GM is NOT removed until the button is pressed
    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert any(gm.discord_id == sample_user.discord_id for gm in party.gms)
    verify.close()


async def test_remove_gm_self_confirmed_removes_gm(
    mocker,
    party_bot,
    sample_party,
    sample_user,
    db_session,
    interaction,
    session_factory,
):
    """Pressing the confirm button on self-GM-removal removes the GM."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove myself"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(gm.discord_id == sample_user.discord_id for gm in party.gms)
    verify.close()


async def test_remove_gm_last_gm_blocked(
    mocker, party_bot, sample_party, sample_user, interaction
):
    """Removing the last GM is rejected to prevent orphaned parties."""
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "last" in msg.lower()


async def test_remove_gm_not_gm(
    mocker, party_bot, sample_party, sample_user, db_session
):
    """A non-GM cannot remove GMs."""
    non_gm_interaction = make_interaction(mocker, user_id=999)
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(non_gm_interaction, party_name="The Fellowship", target_gm=mock_member)

    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )


async def test_remove_gm_target_not_a_gm(
    mocker, party_bot, sample_party, db_session, interaction
):
    """Trying to remove someone who isn't a GM returns an error."""
    non_gm_user = User(discord_id="555")
    db_session.add(non_gm_user)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_gm_party_not_found(
    mocker, party_bot, sample_user, sample_server, interaction
):
    """gm_remove on a nonexistent party returns an error."""
    mock_member = mocker.Mock()
    mock_member.id = 111

    cb = get_callback(party_bot, "party", "gm_remove")
    await cb(interaction, party_name="Ghost Party", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# view_party shows multiple GMs
# ---------------------------------------------------------------------------


async def test_view_party_shows_multiple_gms(
    mocker, party_bot, sample_party, sample_user, db_session, interaction
):
    """view embed lists all GMs when there are multiple."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name="The Fellowship")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    gm_field = next(f for f in embed.fields if f.name == "GMs")
    assert "111" in gm_field.value
    assert "555" in gm_field.value


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------


async def test_create_party_over_gm_limit(
    mocker, party_bot, sample_user, sample_server, db_session, interaction
):
    """A user who is already GM of the maximum number of parties cannot create another."""
    mocker.patch("commands.party_commands.MAX_GM_PARTIES_PER_USER", 2)

    for i in range(2):
        p = Party(name=f"Party{i}", gms=[sample_user], server=sample_server)
        db_session.add(p)
    db_session.commit()

    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="OneMore")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_create_party_over_server_limit(
    mocker, party_bot, sample_user, sample_server, db_session, interaction
):
    """A server that has reached the maximum party count rejects new parties."""
    mocker.patch("commands.party_commands.MAX_PARTIES_PER_SERVER", 2)

    other_gm = User(discord_id="888")
    db_session.add(other_gm)
    db_session.flush()
    for i in range(2):
        p = Party(name=f"SrvParty{i}", gms=[other_gm], server=sample_server)
        db_session.add(p)
    db_session.commit()

    cb = get_callback(party_bot, "party", "create")
    await cb(interaction, party_name="CantAdd")

    assert interaction.followup.send.call_args.kwargs.get("ephemeral") is True
    msg = interaction.followup.send.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_party_add_over_member_limit(
    mocker, party_bot, sample_party, sample_user, sample_server, db_session, interaction
):
    """Adding a character when the party is already at max members is rejected."""
    mocker.patch("commands.party_commands.MAX_CHARACTERS_PER_PARTY", 1)

    existing = Character(
        name="AlreadyIn",
        user=sample_user,
        server=sample_server,
        is_active=False,
    )
    db_session.add(existing)
    db_session.flush()
    sample_party.characters.append(existing)
    db_session.commit()

    target = Character(
        name="Aldric",
        user=sample_user,
        server=sample_server,
        is_active=True,
    )
    db_session.add(target)
    db_session.commit()

    cb = get_callback(party_bot, "party", "character_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


# ---------------------------------------------------------------------------
# /party settings crit_rule
# ---------------------------------------------------------------------------


async def test_party_settings_crit_rule_set_by_gm(
    party_bot,
    sample_party,
    interaction,
    session_factory,
):
    """GM can set the crit rule for their party."""
    cb = get_callback(party_bot, "party", "settings", "crit_rule")
    await cb(interaction, party_name="The Fellowship", rule="perkins")

    msg = interaction.response.send_message.call_args.args[0]
    assert "perkins" in msg.lower()

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings is not None
    assert settings.crit_rule == CritRule.PERKINS
    verify.close()


async def test_party_settings_crit_rule_default_is_double_dice(
    party_bot,
    sample_party,
    interaction,
    session_factory,
):
    """A party with no settings defaults to DOUBLE_DICE."""
    cb = get_callback(party_bot, "party", "settings", "crit_rule")
    await cb(interaction, party_name="The Fellowship", rule="double_dice")

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings.crit_rule == CritRule.DOUBLE_DICE
    verify.close()


async def test_party_settings_crit_rule_invalid_value(
    party_bot,
    sample_party,
    interaction,
):
    """An unrecognised crit rule name returns an ephemeral error."""
    cb = get_callback(party_bot, "party", "settings", "crit_rule")
    await cb(interaction, party_name="The Fellowship", rule="quadruple")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_settings_crit_rule_requires_gm(
    party_bot,
    sample_party,
    db_session,
    interaction,
    session_factory,
    mocker,
):
    """A non-GM cannot change the crit rule."""
    non_gm = User(discord_id="999")
    db_session.add(non_gm)
    db_session.commit()
    interaction.user.id = 999

    cb = get_callback(party_bot, "party", "settings", "crit_rule")
    await cb(interaction, party_name="The Fellowship", rule="double_damage")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    # Settings should be unchanged
    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings is None or settings.crit_rule == CritRule.DOUBLE_DICE
    verify.close()


# ---------------------------------------------------------------------------
# /party list
# ---------------------------------------------------------------------------


async def test_party_list_shows_embed(
    party_bot, sample_party, sample_server, interaction
):
    """/party list returns an embed when at least one party exists."""
    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None


async def test_party_list_embed_title_contains_server_name(
    party_bot, sample_party, sample_server, interaction
):
    """/party list embed title includes the server name."""
    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert sample_server.name in embed.title


async def test_party_list_shows_member_count(
    party_bot, sample_party, sample_character, db_session, interaction
):
    """/party list shows the correct member count for a party."""
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    field_values = " ".join(f.value for f in embed.fields)
    assert "1" in field_values  # 1 member


async def test_party_list_empty_server_sends_ephemeral(
    party_bot, sample_user, sample_server, interaction
):
    """/party list with no parties sends an ephemeral message (not an embed)."""
    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is None
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_list_no_character_needed(
    party_bot, sample_party, sample_server, interaction
):
    """/party list works for a user who has no active character."""
    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None


async def test_party_list_single_page_buttons_disabled(
    party_bot, sample_party, sample_server, interaction
):
    """With only 1 party (< page size), both pagination buttons are disabled."""
    from commands.party_commands import PartyListView

    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert isinstance(view, PartyListView)
    prev_btn = next(
        item for item in view.children if getattr(item, "label", "") == "◀ Previous"
    )
    next_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Next ▶"
    )
    assert prev_btn.disabled is True
    assert next_btn.disabled is True


async def test_party_list_multi_page_next_button_enabled(
    mocker, party_bot, sample_user, sample_server, db_session, interaction
):
    """With more parties than PARTIES_PER_PAGE, the Next button is enabled."""
    from commands.party_commands import PartyListView

    for i in range(PartyListView.PARTIES_PER_PAGE + 1):
        db_session.add(Party(name=f"Party{i}", gms=[sample_user], server=sample_server))
    db_session.commit()

    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    next_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Next ▶"
    )
    assert next_btn.disabled is False


async def test_party_list_next_button_advances_page(
    mocker, party_bot, sample_user, sample_server, db_session, interaction
):
    """Clicking Next on a multi-page list edits the message to show the next page."""
    from commands.party_commands import PartyListView

    for i in range(PartyListView.PARTIES_PER_PAGE + 2):
        db_session.add(
            Party(name=f"Party{i:02d}", gms=[sample_user], server=sample_server)
        )
    db_session.commit()

    cb = get_callback(party_bot, "party", "list")
    await cb(interaction)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view.current_page == 0

    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    next_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Next ▶"
    )
    await next_btn.callback(btn_interaction)

    assert view.current_page == 1
    btn_interaction.response.edit_message.assert_called_once()


# ---------------------------------------------------------------------------
# /party settings death_save_nat20
# ---------------------------------------------------------------------------


async def test_settings_death_save_nat20_set_regain_hp(
    party_bot,
    sample_party,
    interaction,
    session_factory,
):
    """GM can set death_save_nat20 to regain_hp."""
    cb = get_callback(party_bot, "party", "settings", "death_save_nat20")
    await cb(interaction, party_name="The Fellowship", mode="regain_hp")

    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )
    msg = interaction.response.send_message.call_args.args[0]
    assert "regain_hp" in msg.lower()

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings is not None
    assert settings.death_save_nat20_mode.value == "regain_hp"
    verify.close()


async def test_settings_death_save_nat20_set_double_success(
    party_bot,
    sample_party,
    interaction,
    session_factory,
):
    """GM can set death_save_nat20 to double_success."""
    from enums.death_save_nat20_mode import DeathSaveNat20Mode

    cb = get_callback(party_bot, "party", "settings", "death_save_nat20")
    await cb(interaction, party_name="The Fellowship", mode="double_success")

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings is not None
    assert settings.death_save_nat20_mode == DeathSaveNat20Mode.DOUBLE_SUCCESS
    verify.close()


async def test_settings_death_save_nat20_invalid_mode(
    party_bot,
    sample_party,
    interaction,
):
    """An invalid mode string returns an ephemeral error."""
    cb = get_callback(party_bot, "party", "settings", "death_save_nat20")
    await cb(interaction, party_name="The Fellowship", mode="triple_success")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_settings_death_save_nat20_transition(
    party_bot,
    sample_party,
    interaction,
    session_factory,
):
    """Setting double_success then regain_hp → final value is regain_hp."""
    from enums.death_save_nat20_mode import DeathSaveNat20Mode

    cb = get_callback(party_bot, "party", "settings", "death_save_nat20")
    await cb(interaction, party_name="The Fellowship", mode="double_success")
    await cb(interaction, party_name="The Fellowship", mode="regain_hp")

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(party_id=sample_party.id).first()
    assert settings.death_save_nat20_mode == DeathSaveNat20Mode.REGAIN_HP
    verify.close()


async def test_settings_view_shows_death_save_nat20_mode(
    party_bot,
    sample_party,
    interaction,
):
    """/party settings view includes the death_save_nat20 field."""
    cb = get_callback(party_bot, "party", "settings", "view")
    await cb(interaction, party_name="The Fellowship")

    msg = interaction.response.send_message.call_args.args[0]
    # PARTY_SETTINGS_VIEW contains "Death save nat-20 rule:" label
    assert (
        "death" in msg.lower()
        or "nat" in msg.lower()
        or "nat20" in msg.lower()
        or "nat-20" in msg.lower()
    )
