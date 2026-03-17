import pytest
from models import Encounter, Enemy, EncounterTurn
from enums.encounter_status import EncounterStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /create_encounter
# ---------------------------------------------------------------------------

async def test_create_encounter_success(encounter_bot, sample_active_party, interaction, session_factory):
    cb = get_callback(encounter_bot, "create_encounter")
    await cb(interaction, name="Dragon's Lair")

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(name="Dragon's Lair").first()
    assert enc is not None
    assert enc.status == EncounterStatus.PENDING
    assert enc.party_id == sample_active_party.id
    verify.close()


async def test_create_encounter_success_message(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "create_encounter")
    await cb(interaction, name="Dragon's Lair")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Dragon's Lair" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_create_encounter_no_active_party(encounter_bot, sample_user, sample_server, interaction):
    cb = get_callback(encounter_bot, "create_encounter")
    await cb(interaction, name="Dragon's Lair")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_create_encounter_not_gm(mocker, encounter_bot, sample_active_party, session_factory):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "create_encounter")
    await cb(other, name="Dragon's Lair")

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_create_encounter_duplicate_rejected(encounter_bot, sample_pending_encounter, interaction):
    """A party may not have more than one PENDING or ACTIVE encounter at a time."""
    cb = get_callback(encounter_bot, "create_encounter")
    await cb(interaction, name="Another Dungeon")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /add_enemy
# ---------------------------------------------------------------------------

async def test_add_enemy_success(encounter_bot, sample_pending_encounter, interaction, session_factory):
    cb = get_callback(encounter_bot, "add_enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp=15)

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Orc").first()
    assert enemy is not None
    assert enemy.initiative_modifier == 2
    assert enemy.max_hp == 15
    assert enemy.current_hp is None  # HP tracking placeholder — not set on creation
    verify.close()


async def test_add_enemy_success_message(encounter_bot, sample_pending_encounter, interaction):
    cb = get_callback(encounter_bot, "add_enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp=15)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Orc" in msg


async def test_add_enemy_no_pending_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "add_enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp=15)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_enemy_not_gm(mocker, encounter_bot, sample_pending_encounter):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "add_enemy")
    await cb(other, name="Orc", initiative_modifier=2, max_hp=15)

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_enemy_cannot_add_to_active_encounter(
    encounter_bot, sample_active_encounter, interaction
):
    """Enemies cannot be added once the encounter has started."""
    cb = get_callback(encounter_bot, "add_enemy")
    await cb(interaction, name="LateOrc", initiative_modifier=0, max_hp=10)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_enemy_over_limit_rejected(
    mocker, encounter_bot, sample_pending_encounter, db_session, interaction
):
    """Adding an enemy beyond the per-encounter cap is rejected."""
    mocker.patch("commands.encounter_commands.MAX_ENEMIES_PER_ENCOUNTER", 2)

    for i in range(2):
        db_session.add(Enemy(
            encounter_id=sample_pending_encounter.id,
            name=f"Enemy{i}",
            initiative_modifier=0,
            max_hp=10,
        ))
    db_session.commit()

    cb = get_callback(encounter_bot, "add_enemy")
    await cb(interaction, name="OneMore", initiative_modifier=0, max_hp=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


# ---------------------------------------------------------------------------
# /start_encounter
# ---------------------------------------------------------------------------

async def test_start_encounter_success(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session,
    interaction, session_factory
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "start_encounter")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_pending_encounter.id).first()
    assert enc.status == EncounterStatus.ACTIVE
    assert enc.round_number == 1
    assert enc.current_turn_index == 0
    turns = verify.query(EncounterTurn).filter_by(encounter_id=enc.id).all()
    assert len(turns) == 2
    verify.close()


async def test_start_encounter_posts_message(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session, interaction
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "start_encounter")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    interaction.response.defer.assert_called_once()
    assert interaction.followup.send.call_count >= 2  # order message + ping
    content = interaction.followup.send.call_args_list[0].args[0]
    assert "Test Dungeon" in content
    assert "Round 1" in content
    assert "Aldric" in content
    assert "Goblin" in content


async def test_start_encounter_stores_message_id(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session,
    interaction, session_factory
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "start_encounter")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_pending_encounter.id).first()
    assert enc.message_id == str(interaction.followup.send.return_value.id)
    assert enc.channel_id == str(interaction.channel_id)
    verify.close()


async def test_start_encounter_pings_first_participant(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session, interaction
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "start_encounter")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    # The turn notification is sent as a separate followup after the order message
    assert interaction.followup.send.call_count >= 2
    all_calls = [str(c) for c in interaction.followup.send.call_args_list]
    combined = " ".join(all_calls)
    assert "next_turn" in combined.lower() or "your turn" in combined.lower()


async def test_start_encounter_initiative_order_sorted(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session,
    interaction, session_factory
):
    """Higher initiative roll should get lower order_position."""
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    call_count = 0
    def alternating_roll(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return 18 if call_count == 1 else 5  # char rolls 18, enemy rolls 5

    cb = get_callback(encounter_bot, "start_encounter")
    mocker.patch("utils.dnd_logic.random.randint", side_effect=alternating_roll)
    await cb(interaction)

    verify = session_factory()
    turns = (
        verify.query(EncounterTurn)
        .filter_by(encounter_id=sample_pending_encounter.id)
        .order_by(EncounterTurn.order_position)
        .all()
    )
    assert turns[0].character_id is not None  # char goes first (higher roll)
    assert turns[1].enemy_id is not None
    verify.close()


async def test_start_encounter_no_pending_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "start_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_no_enemies(
    encounter_bot, sample_pending_encounter, sample_character, db_session, interaction
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "start_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_empty_party(encounter_bot, sample_pending_encounter, sample_enemy, interaction):
    cb = get_callback(encounter_bot, "start_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_already_active(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "start_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /next_turn
# ---------------------------------------------------------------------------

async def test_next_turn_advances_index(
    encounter_bot, sample_active_encounter, interaction, session_factory
):
    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.current_turn_index == 1
    verify.close()


async def test_next_turn_edits_original_message(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    interaction.channel.fetch_message.assert_called_once_with(int(sample_active_encounter.message_id))
    interaction.channel.fetch_message.return_value.edit.assert_called_once()


async def test_next_turn_message_shows_new_current(encounter_bot, sample_active_encounter, interaction):
    """After advancing, the edit content should highlight position 1 (Goblin)."""
    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    edited_content = interaction.channel.fetch_message.return_value.edit.call_args.kwargs.get("content")
    assert edited_content is not None
    assert "Goblin" in edited_content


async def test_next_turn_wraps_round(
    encounter_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """Advancing past the last turn should increment round and wrap to index 0."""
    sample_active_encounter.current_turn_index = 1  # already on last turn
    db_session.commit()

    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.current_turn_index == 0
    assert enc.round_number == 2
    verify.close()


async def test_next_turn_round_message_updates(
    encounter_bot, sample_active_encounter, db_session, interaction
):
    sample_active_encounter.current_turn_index = 1
    db_session.commit()

    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    edited_content = interaction.channel.fetch_message.return_value.edit.call_args.kwargs.get("content")
    assert "Round 2" in edited_content


async def test_next_turn_pings_next_participant(encounter_bot, sample_active_encounter, interaction):
    """After advancing to turn 1 (enemy), the GM should be pinged."""
    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    # A new message should be sent announcing the next turn
    interaction.followup.send.assert_called_once()
    msg = interaction.followup.send.call_args.args[0]
    assert "next_turn" in msg.lower() or "your turn" in msg.lower()


async def test_next_turn_by_gm_on_enemy_turn(
    encounter_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """The GM can always call /next_turn (including on enemy turns)."""
    sample_active_encounter.current_turn_index = 1  # enemy's turn
    db_session.commit()

    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)  # interaction user is the GM (user_id=111)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.current_turn_index == 0
    verify.close()


async def test_next_turn_by_character_owner_on_their_turn(
    mocker, encounter_bot, sample_active_encounter, session_factory
):
    """The character's owning player can call /next_turn on their own turn."""
    # Turn 0 belongs to Aldric, owned by user 111
    their_interaction = make_interaction(mocker, user_id=111)
    cb = get_callback(encounter_bot, "next_turn")
    await cb(their_interaction)

    their_interaction.channel.fetch_message.assert_called_once()


async def test_next_turn_unauthorized_user_blocked(mocker, encounter_bot, sample_active_encounter):
    """A user who is not the GM and not the current turn's character owner is blocked."""
    stranger = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "next_turn")
    await cb(stranger)

    assert stranger.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_next_turn_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "next_turn")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /end_encounter
# ---------------------------------------------------------------------------

async def test_end_encounter_success(
    encounter_bot, sample_active_encounter, interaction, session_factory
):
    cb = get_callback(encounter_bot, "end_encounter")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.status == EncounterStatus.COMPLETE
    verify.close()


async def test_end_encounter_not_gm(mocker, encounter_bot, sample_active_encounter):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "end_encounter")
    await cb(other)

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_end_encounter_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "end_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /view_encounter
# ---------------------------------------------------------------------------

async def test_view_encounter_sends_embed(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "view_encounter")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Test Dungeon" in embed.title


async def test_view_encounter_shows_round(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "view_encounter")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    combined = embed.title + " ".join(f.value for f in embed.fields)
    assert "1" in combined  # round 1


async def test_view_encounter_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "view_encounter")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
