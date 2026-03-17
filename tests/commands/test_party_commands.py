import pytest
from sqlalchemy import select
from models import Party, Character, user_server_association
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /create_party
# ---------------------------------------------------------------------------

async def test_create_party_empty(party_bot, sample_user, sample_server, interaction, session_factory):
    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="The Fellowship")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "The Fellowship" in msg

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert party is not None
    verify.close()


async def test_create_party_with_existing_character(party_bot, sample_character, interaction, session_factory):
    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="Heroes", characters_list="Aldric")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="Heroes").first()
    assert len(party.characters) == 1
    assert party.characters[0].name == "Aldric"
    verify.close()


async def test_create_party_partial_char_list_reports_not_found(party_bot, sample_character, interaction):
    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="Mixed", characters_list="Aldric, Ghost")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Ghost" in msg
    assert "not found" in msg.lower()


async def test_create_party_duplicate_name_rejected(party_bot, sample_party, interaction):
    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="The Fellowship")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_create_party_sets_active_party(party_bot, sample_user, sample_server, interaction, session_factory):
    cb = get_callback(party_bot, "create_party")
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
# /party_add
# ---------------------------------------------------------------------------

async def test_party_add_success(party_bot, sample_party, sample_character, interaction, session_factory):
    cb = get_callback(party_bot, "party_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert any(c.name == "Aldric" for c in party.characters)
    verify.close()


async def test_party_add_party_not_found(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "party_add")
    await cb(interaction, party_name="Nonexistent", character_name="Anyone")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_add_not_gm(mocker, party_bot, sample_party, sample_character, db_session, session_factory):
    """A user who isn't the GM cannot add members."""
    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party_add")
    await cb(other_interaction, party_name="The Fellowship", character_name="Aldric")

    assert other_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_add_character_not_found(party_bot, sample_party, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "party_add")
    await cb(interaction, party_name="The Fellowship", character_name="Nobody")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_party_add_already_in_party(party_bot, sample_party, sample_character, db_session, interaction):
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party_remove
# ---------------------------------------------------------------------------

async def test_party_remove_success(party_bot, sample_party, sample_character, db_session, interaction, session_factory):
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party_remove")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(c.name == "Aldric" for c in party.characters)
    verify.close()


async def test_party_remove_not_gm(mocker, party_bot, sample_party, sample_character, db_session):
    sample_party.characters.append(sample_character)
    db_session.commit()

    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party_remove")
    await cb(other_interaction, party_name="The Fellowship", character_name="Aldric")

    assert other_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /active_party (set and view)
# ---------------------------------------------------------------------------

async def test_active_party_set_success(party_bot, sample_party, interaction):
    cb = get_callback(party_bot, "active_party")
    await cb(interaction, party_name="The Fellowship")

    msg = interaction.response.send_message.call_args.args[0]
    assert "The Fellowship" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_active_party_set_not_found(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "active_party")
    await cb(interaction, party_name="Ghost Party")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_active_party_view(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "active_party")
    await cb(interaction)  # no party_name → view mode

    msg = interaction.response.send_message.call_args.args[0]
    assert "The Fellowship" in msg


async def test_active_party_view_none_set(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "active_party")
    await cb(interaction)

    msg = interaction.response.send_message.call_args.args[0]
    assert "don't have" in msg.lower() or "no active" in msg.lower()


# ---------------------------------------------------------------------------
# /rollas
# ---------------------------------------------------------------------------

async def test_rollas_success(mocker, party_bot, sample_active_party, sample_character, db_session, interaction):
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "rollas")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, member_name="Aldric", notation="1d20")

    interaction.response.send_message.assert_called_once()


async def test_rollas_no_active_party(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "rollas")
    await cb(interaction, member_name="Aldric", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_rollas_member_not_found(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "rollas")
    await cb(interaction, member_name="Ghost", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /partyroll
# ---------------------------------------------------------------------------

async def test_partyroll_success(mocker, party_bot, sample_active_party, sample_character, db_session, interaction):
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "partyroll")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction, notation="1d20")

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()


async def test_partyroll_no_active_party(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "partyroll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_partyroll_empty_party(party_bot, sample_active_party, interaction):
    cb = get_callback(party_bot, "partyroll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /view_party
# ---------------------------------------------------------------------------

async def test_view_party_success(party_bot, sample_party, interaction):
    cb = get_callback(party_bot, "view_party")
    await cb(interaction, party_name="The Fellowship")

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "The Fellowship" in embed.title


async def test_view_party_not_found(party_bot, sample_user, sample_server, interaction):
    cb = get_callback(party_bot, "view_party")
    await cb(interaction, party_name="Nope")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /delete_party
# ---------------------------------------------------------------------------

async def test_delete_party_success(party_bot, sample_party, interaction, session_factory):
    cb = get_callback(party_bot, "delete_party")
    await cb(interaction, party_name="The Fellowship")

    verify = session_factory()
    assert verify.query(Party).filter_by(name="The Fellowship").first() is None
    verify.close()


async def test_delete_party_not_gm(mocker, party_bot, sample_party, session_factory):
    other_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "delete_party")
    await cb(other_interaction, party_name="The Fellowship")

    assert other_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    verify = session_factory()
    assert verify.query(Party).filter_by(name="The Fellowship").first() is not None
    verify.close()
