import pytest
from sqlalchemy import select
from models import Party, Character, User, Server, user_server_association
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


# ---------------------------------------------------------------------------
# /add_gm
# ---------------------------------------------------------------------------

async def test_add_gm_success(mocker, party_bot, sample_party, sample_server, db_session, interaction, session_factory):
    """A GM can add another Discord user as a GM."""
    # Register a second user in the DB (the target)
    target_user = User(discord_id="555")
    db_session.add(target_user)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "add_gm")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
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

    cb = get_callback(party_bot, "add_gm")
    await cb(non_gm_interaction, party_name="The Fellowship", new_gm=mock_member)

    assert non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_gm_target_not_registered(mocker, party_bot, sample_party, interaction):
    """Adding a user who has never used the bot is rejected."""
    mock_member = mocker.Mock()
    mock_member.id = 9999  # no DB record

    cb = get_callback(party_bot, "add_gm")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_gm_already_gm(mocker, party_bot, sample_party, sample_user, interaction):
    """Adding a user who is already a GM is rejected."""
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)  # user 111 is already the GM

    cb = get_callback(party_bot, "add_gm")
    await cb(interaction, party_name="The Fellowship", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_gm_party_not_found(mocker, party_bot, sample_user, sample_server, interaction):
    """add_gm on a nonexistent party returns an error."""
    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "add_gm")
    await cb(interaction, party_name="Ghost Party", new_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /remove_gm
# ---------------------------------------------------------------------------

async def test_remove_gm_success(mocker, party_bot, sample_party, sample_user, db_session, interaction, session_factory):
    """A GM can remove another GM from the party."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "remove_gm")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(gm.discord_id == "555" for gm in party.gms)
    verify.close()


async def test_remove_gm_self_success(mocker, party_bot, sample_party, sample_user, db_session, interaction, session_factory):
    """A GM can remove themselves when at least one other GM exists."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    # interaction user is 111 (sample_user), removing themselves
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "remove_gm")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True

    verify = session_factory()
    party = verify.query(Party).filter_by(name="The Fellowship").first()
    assert not any(gm.discord_id == sample_user.discord_id for gm in party.gms)
    verify.close()


async def test_remove_gm_last_gm_blocked(mocker, party_bot, sample_party, sample_user, interaction):
    """Removing the last GM is rejected to prevent orphaned parties."""
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "remove_gm")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "last" in msg.lower()


async def test_remove_gm_not_gm(mocker, party_bot, sample_party, sample_user, db_session):
    """A non-GM cannot remove GMs."""
    non_gm_interaction = make_interaction(mocker, user_id=999)
    mock_member = mocker.Mock()
    mock_member.id = int(sample_user.discord_id)

    cb = get_callback(party_bot, "remove_gm")
    await cb(non_gm_interaction, party_name="The Fellowship", target_gm=mock_member)

    assert non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_gm_target_not_a_gm(mocker, party_bot, sample_party, db_session, interaction):
    """Trying to remove someone who isn't a GM returns an error."""
    non_gm_user = User(discord_id="555")
    db_session.add(non_gm_user)
    db_session.commit()

    mock_member = mocker.Mock()
    mock_member.id = 555

    cb = get_callback(party_bot, "remove_gm")
    await cb(interaction, party_name="The Fellowship", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_remove_gm_party_not_found(mocker, party_bot, sample_user, sample_server, interaction):
    """remove_gm on a nonexistent party returns an error."""
    mock_member = mocker.Mock()
    mock_member.id = 111

    cb = get_callback(party_bot, "remove_gm")
    await cb(interaction, party_name="Ghost Party", target_gm=mock_member)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# view_party shows multiple GMs
# ---------------------------------------------------------------------------

async def test_view_party_shows_multiple_gms(mocker, party_bot, sample_party, sample_user, db_session, interaction):
    """view_party embed lists all GMs when there are multiple."""
    second_gm = User(discord_id="555")
    db_session.add(second_gm)
    db_session.flush()
    sample_party.gms.append(second_gm)
    db_session.commit()

    cb = get_callback(party_bot, "view_party")
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

    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="OneMore")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_create_party_over_server_limit(
    mocker, party_bot, sample_user, sample_server, db_session, interaction
):
    """A server that has reached the maximum party count rejects new parties."""
    mocker.patch("commands.party_commands.MAX_PARTIES_PER_SERVER", 2)

    # Need a second user so these don't also hit the GM limit
    other_gm = User(discord_id="888")
    db_session.add(other_gm)
    db_session.flush()
    for i in range(2):
        p = Party(name=f"SrvParty{i}", gms=[other_gm], server=sample_server)
        db_session.add(p)
    db_session.commit()

    cb = get_callback(party_bot, "create_party")
    await cb(interaction, party_name="CantAdd")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_party_add_over_member_limit(
    mocker, party_bot, sample_party, sample_user, sample_server, db_session, interaction
):
    """Adding a character when the party is already at max members is rejected."""
    mocker.patch("commands.party_commands.MAX_CHARACTERS_PER_PARTY", 1)

    # Seed one character already in the party to hit the cap
    existing = Character(
        name="AlreadyIn",
        user=sample_user,
        server=sample_server,
        is_active=False,
        level=1,
    )
    db_session.add(existing)
    db_session.flush()
    sample_party.characters.append(existing)
    db_session.commit()

    # The character being added
    target = Character(
        name="Aldric",
        user=sample_user,
        server=sample_server,
        is_active=True,
        level=5,
    )
    db_session.add(target)
    db_session.commit()

    cb = get_callback(party_bot, "party_add")
    await cb(interaction, party_name="The Fellowship", character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()
