import pytest
from models import Encounter, Enemy, EncounterTurn, PartySettings
from enums.encounter_status import EncounterStatus
from enums.enemy_initiative_mode import EnemyInitiativeMode
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# /encounter create
# ---------------------------------------------------------------------------

async def test_create_encounter_success(encounter_bot, sample_active_party, interaction, session_factory):
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Dragon's Lair")

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(name="Dragon's Lair").first()
    assert enc is not None
    assert enc.status == EncounterStatus.PENDING
    assert enc.party_id == sample_active_party.id
    verify.close()


async def test_create_encounter_success_message(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Dragon's Lair")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Dragon's Lair" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_create_encounter_no_active_party(encounter_bot, sample_user, sample_server, interaction):
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Dragon's Lair")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_create_encounter_not_gm(mocker, encounter_bot, sample_active_party, session_factory):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(other, name="Dragon's Lair")

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_create_encounter_duplicate_rejected(encounter_bot, sample_pending_encounter, interaction):
    """A party may not have more than one PENDING or ACTIVE encounter at a time."""
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Another Dungeon")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /encounter enemy
# ---------------------------------------------------------------------------

async def test_add_enemy_success(encounter_bot, sample_pending_encounter, interaction, session_factory):
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp="15")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Orc").first()
    assert enemy is not None
    assert enemy.initiative_modifier == 2
    assert enemy.max_hp == 15
    assert enemy.current_hp == 15
    verify.close()


async def test_add_enemy_success_message(encounter_bot, sample_pending_encounter, interaction):
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp="15")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Orc" in msg


async def test_add_enemy_no_pending_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp="15")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_enemy_not_gm(mocker, encounter_bot, sample_pending_encounter):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(other, name="Orc", initiative_modifier=2, max_hp="15")

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_add_enemy_cannot_add_to_active_encounter(
    encounter_bot, sample_active_encounter, interaction
):
    """Enemies cannot be added once the encounter has started."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="LateOrc", initiative_modifier=0, max_hp="10")

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

    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="OneMore", initiative_modifier=0, max_hp="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "limit" in msg.lower()


# ---------------------------------------------------------------------------
# /encounter enemy — Phase 1 enhancements
# ---------------------------------------------------------------------------


async def test_add_enemy_sets_type_name_equal_to_name(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """Single enemy created with count=1 sets type_name equal to the provided name."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Orc", initiative_modifier=2, max_hp="10")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Orc").first()
    assert enemy.type_name == "Orc"
    verify.close()


async def test_add_enemy_sets_current_hp_on_creation(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """current_hp is set to the parsed HP value when the enemy is created."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Troll", initiative_modifier=0, max_hp="15")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Troll").first()
    assert enemy.current_hp == 15
    assert enemy.max_hp == 15
    verify.close()


async def test_add_enemy_stores_ac(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """AC value is stored on the enemy when provided."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Knight", initiative_modifier=1, max_hp="20", ac=14)

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Knight").first()
    assert enemy.ac == 14
    verify.close()


async def test_add_enemy_ac_defaults_to_none(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """AC defaults to None when not provided."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Slime", initiative_modifier=0, max_hp="5")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Slime").first()
    assert enemy.ac is None
    verify.close()


async def test_add_enemy_flat_hp_string(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """A flat integer string for max_hp is stored as the HP value."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Rat", initiative_modifier=-1, max_hp="20")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Rat").first()
    assert enemy.max_hp == 20
    assert enemy.current_hp == 20
    verify.close()


async def test_add_enemy_dice_formula_hp(
    mocker, encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """A dice formula for max_hp is rolled and the result stored as HP."""
    mocker.patch("dice_roller.random.randint", return_value=5)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    # 2d8+4 with each die returning 5 → 5+5+4 = 14
    await cb(interaction, name="Ogre", initiative_modifier=1, max_hp="2d8+4")

    verify = session_factory()
    enemy = verify.query(Enemy).filter_by(name="Ogre").first()
    assert enemy.max_hp == 14
    assert enemy.current_hp == 14
    verify.close()


async def test_add_enemy_invalid_hp_formula(
    encounter_bot, sample_pending_encounter, interaction
):
    """An unrecognised HP string sends an ephemeral error and creates no enemy."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Ghost", initiative_modifier=0, max_hp="notaformula")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "notaformula" in msg


async def test_add_enemy_bulk_creates_multiple(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """count=2 creates two enemies named 'Kobold 1' and 'Kobold 2'."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Kobold", initiative_modifier=1, max_hp="5", count=2)

    verify = session_factory()
    enemies = verify.query(Enemy).filter(
        Enemy.encounter_id == sample_pending_encounter.id
    ).all()
    names = {e.name for e in enemies}
    assert "Kobold 1" in names
    assert "Kobold 2" in names
    assert len(enemies) == 2
    verify.close()


async def test_add_enemy_bulk_type_name_is_base_name(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """All bulk-added enemies share the base name as their type_name."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Kobold", initiative_modifier=1, max_hp="5", count=3)

    verify = session_factory()
    enemies = verify.query(Enemy).filter(
        Enemy.encounter_id == sample_pending_encounter.id
    ).all()
    assert all(e.type_name == "Kobold" for e in enemies)
    verify.close()


async def test_add_enemy_bulk_hp_rolled_per_enemy(
    mocker, encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """Each enemy in a bulk add rolls HP independently using dice formula."""
    mocker.patch("dice_roller.random.randint", side_effect=[3, 6])
    cb = get_callback(encounter_bot, "encounter", "enemy")
    # 1d6 with rolls 3 then 6 → HP 3 and HP 6
    await cb(interaction, name="Rat", initiative_modifier=0, max_hp="1d6", count=2)

    verify = session_factory()
    enemies = (
        verify.query(Enemy)
        .filter(Enemy.encounter_id == sample_pending_encounter.id)
        .order_by(Enemy.name)
        .all()
    )
    hp_values = {e.max_hp for e in enemies}
    assert hp_values == {3, 6}
    verify.close()


async def test_add_enemy_bulk_over_limit_rejected(
    mocker, encounter_bot, sample_pending_encounter, db_session, interaction
):
    """Bulk add that would exceed the cap is rejected entirely."""
    mocker.patch("commands.encounter_commands.MAX_ENEMIES_PER_ENCOUNTER", 3)

    for i in range(2):
        db_session.add(Enemy(
            encounter_id=sample_pending_encounter.id,
            name=f"Existing{i}",
            initiative_modifier=0,
            max_hp=5,
        ))
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=0, max_hp="5", count=2)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "limit" in msg.lower()


async def test_add_enemy_bulk_partial_over_limit_rejected(
    mocker, encounter_bot, sample_pending_encounter, db_session, interaction
):
    """Partial overage (8 existing + count=4 against cap=10) is also rejected."""
    mocker.patch("commands.encounter_commands.MAX_ENEMIES_PER_ENCOUNTER", 10)

    for i in range(8):
        db_session.add(Enemy(
            encounter_id=sample_pending_encounter.id,
            name=f"Filler{i}",
            initiative_modifier=0,
            max_hp=5,
        ))
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Goblin", initiative_modifier=0, max_hp="5", count=4)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "limit" in msg.lower()


async def test_add_enemy_count_default_is_one(
    encounter_bot, sample_pending_encounter, interaction, session_factory
):
    """Calling encounter enemy without count defaults to creating a single enemy."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Bandit", initiative_modifier=0, max_hp="8")

    verify = session_factory()
    enemies = verify.query(Enemy).filter(
        Enemy.encounter_id == sample_pending_encounter.id
    ).all()
    assert len(enemies) == 1
    assert enemies[0].name == "Bandit"
    verify.close()


async def test_add_enemy_single_message_shows_name_and_hp(
    encounter_bot, sample_pending_encounter, interaction
):
    """Response for a single add includes the enemy name and HP value."""
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Wolf", initiative_modifier=1, max_hp="11")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Wolf" in msg
    assert "11" in msg


async def test_add_enemy_bulk_message_shows_all_enemies(
    mocker, encounter_bot, sample_pending_encounter, interaction
):
    """Response for a bulk add lists all enemy names."""
    mocker.patch("dice_roller.random.randint", return_value=4)
    cb = get_callback(encounter_bot, "encounter", "enemy")
    await cb(interaction, name="Skeleton", initiative_modifier=0, max_hp="1d6+1", count=2)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Skeleton 1" in msg
    assert "Skeleton 2" in msg


# ---------------------------------------------------------------------------
# /encounter start
# ---------------------------------------------------------------------------

async def test_start_encounter_success(
    mocker, encounter_bot, sample_pending_encounter, sample_enemy, sample_character, db_session,
    interaction, session_factory
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "start")
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

    cb = get_callback(encounter_bot, "encounter", "start")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    interaction.response.defer.assert_called_once()
    assert interaction.followup.send.call_count >= 2
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

    cb = get_callback(encounter_bot, "encounter", "start")
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

    cb = get_callback(encounter_bot, "encounter", "start")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

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

    cb = get_callback(encounter_bot, "encounter", "start")
    # Character rolls 18 (via dnd_logic); enemy rolls 5+1=6 (via encounter_commands).
    mocker.patch("utils.dnd_logic.random.randint", return_value=18)
    mocker.patch("commands.encounter_commands.random.randint", return_value=5)
    await cb(interaction)

    verify = session_factory()
    turns = (
        verify.query(EncounterTurn)
        .filter_by(encounter_id=sample_pending_encounter.id)
        .order_by(EncounterTurn.order_position)
        .all()
    )
    assert turns[0].character_id is not None
    assert turns[1].enemy_id is not None
    verify.close()


async def test_start_encounter_no_pending_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_no_enemies(
    encounter_bot, sample_pending_encounter, sample_character, db_session, interaction
):
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_empty_party(encounter_bot, sample_pending_encounter, sample_enemy, interaction):
    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_start_encounter_already_active(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /encounter next
# ---------------------------------------------------------------------------

async def test_next_turn_advances_index(
    encounter_bot, sample_active_encounter, interaction, session_factory
):
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.current_turn_index == 1
    verify.close()


async def test_next_turn_edits_original_message(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    interaction.channel.fetch_message.assert_called_once_with(int(sample_active_encounter.message_id))
    interaction.channel.fetch_message.return_value.edit.assert_called_once()


async def test_next_turn_message_shows_new_current(encounter_bot, sample_active_encounter, interaction):
    """After advancing, the edit content should highlight position 1 (Goblin)."""
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    edited_content = interaction.channel.fetch_message.return_value.edit.call_args.kwargs.get("content")
    assert edited_content is not None
    assert "Goblin" in edited_content


async def test_next_turn_wraps_round(
    encounter_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """Advancing past the last turn should increment round and wrap to index 0."""
    sample_active_encounter.current_turn_index = 1
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "next")
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

    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    edited_content = interaction.channel.fetch_message.return_value.edit.call_args.kwargs.get("content")
    assert "Round 2" in edited_content


async def test_next_turn_pings_next_participant(encounter_bot, sample_active_encounter, interaction):
    """After advancing to turn 1 (enemy), the GM should be pinged."""
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    interaction.followup.send.assert_called_once()
    msg = interaction.followup.send.call_args.args[0]
    assert "next_turn" in msg.lower() or "your turn" in msg.lower()


async def test_next_turn_by_gm_on_enemy_turn(
    encounter_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """The GM can always call /encounter next (including on enemy turns)."""
    sample_active_encounter.current_turn_index = 1
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.current_turn_index == 0
    verify.close()


async def test_next_turn_by_character_owner_on_their_turn(
    mocker, encounter_bot, sample_active_encounter, session_factory
):
    """The character's owning player can call /encounter next on their own turn."""
    their_interaction = make_interaction(mocker, user_id=111)
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(their_interaction)

    their_interaction.channel.fetch_message.assert_called_once()


async def test_next_turn_unauthorized_user_blocked(mocker, encounter_bot, sample_active_encounter):
    """A user who is not the GM and not the current turn's character owner is blocked."""
    stranger = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(stranger)

    assert stranger.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_next_turn_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_next_turn_response_before_followup(encounter_bot, sample_active_encounter, interaction):
    """interaction.response must be used before followup to avoid 404 Unknown Webhook.

    Regression test: previously followup.send(ping) was called before
    response.send_message, which caused 'Unknown Webhook' errors in production.
    """
    response_order = []
    original_response = interaction.response.send_message
    original_followup = interaction.followup.send

    async def record_response(*args, **kwargs):
        response_order.append("response")
        return await original_response(*args, **kwargs)

    async def record_followup(*args, **kwargs):
        response_order.append("followup")
        return await original_followup(*args, **kwargs)

    interaction.response.send_message = record_response
    interaction.followup.send = record_followup

    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(interaction)

    assert response_order[0] == "response", (
        "response.send_message must be called before followup.send"
    )


# ---------------------------------------------------------------------------
# /encounter end
# ---------------------------------------------------------------------------

async def test_end_encounter_success(
    encounter_bot, sample_active_encounter, interaction, session_factory
):
    cb = get_callback(encounter_bot, "encounter", "end")
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.status == EncounterStatus.COMPLETE
    verify.close()


async def test_end_encounter_not_gm(mocker, encounter_bot, sample_active_encounter):
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "encounter", "end")
    await cb(other)

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_end_encounter_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "end")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /encounter view
# ---------------------------------------------------------------------------

async def test_view_encounter_sends_embed(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Test Dungeon" in embed.title


async def test_view_encounter_shows_round(encounter_bot, sample_active_encounter, interaction):
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    combined = embed.title + " ".join(f.value for f in embed.fields)
    assert "1" in combined


async def test_view_encounter_no_active_encounter(encounter_bot, sample_active_party, interaction):
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /encounter start — Phase 2: initiative grouping modes
# ---------------------------------------------------------------------------


async def test_start_encounter_by_type_groups_same_type_enemies(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """Enemies with the same type_name share the same initiative roll (BY_TYPE mode)."""
    sample_pending_encounter.party.characters.append(sample_character)

    goblin_one = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Goblin 1",
        type_name="Goblin",
        initiative_modifier=2,
        max_hp=7,
        current_hp=7,
    )
    goblin_two = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Goblin 2",
        type_name="Goblin",
        initiative_modifier=2,
        max_hp=7,
        current_hp=7,
    )
    orc = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Orc",
        type_name="Orc",
        initiative_modifier=0,
        max_hp=15,
        current_hp=15,
    )
    db_session.add_all([goblin_one, goblin_two, orc])
    db_session.commit()

    # Set BY_TYPE mode explicitly (this is also the default, but be explicit)
    settings = PartySettings(
        party_id=sample_pending_encounter.party_id,
        initiative_mode=EnemyInitiativeMode.BY_TYPE,
    )
    db_session.add(settings)
    db_session.commit()

    # character roll = 10, goblin type roll = 8, orc roll = 14
    mocker.patch(
        "commands.encounter_commands.roll_initiative_for_character",
        return_value=(10, 0),
    )
    mocker.patch(
        "commands.encounter_commands.random.randint", side_effect=[8, 14]
    )

    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    verify = session_factory()
    turns = verify.query(EncounterTurn).filter_by(
        encounter_id=sample_pending_encounter.id
    ).all()

    goblin_one_turn = next(t for t in turns if t.enemy_id == goblin_one.id)
    goblin_two_turn = next(t for t in turns if t.enemy_id == goblin_two.id)
    orc_turn = next(t for t in turns if t.enemy_id == orc.id)

    assert goblin_one_turn.initiative_roll == goblin_two_turn.initiative_roll
    assert orc_turn.initiative_roll != goblin_one_turn.initiative_roll
    verify.close()


async def test_start_encounter_individual_mode_each_enemy_rolls_separately(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """In INDIVIDUAL mode every enemy gets a distinct initiative roll."""
    sample_pending_encounter.party.characters.append(sample_character)

    enemy_one = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Orc 1",
        type_name="Orc",
        initiative_modifier=0,
        max_hp=15,
        current_hp=15,
    )
    enemy_two = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Orc 2",
        type_name="Orc",
        initiative_modifier=0,
        max_hp=15,
        current_hp=15,
    )
    db_session.add_all([enemy_one, enemy_two])

    settings = PartySettings(
        party_id=sample_pending_encounter.party_id,
        initiative_mode=EnemyInitiativeMode.INDIVIDUAL,
    )
    db_session.add(settings)
    db_session.commit()

    mocker.patch(
        "commands.encounter_commands.roll_initiative_for_character",
        return_value=(10, 0),
    )
    mocker.patch(
        "commands.encounter_commands.random.randint", side_effect=[8, 6]
    )

    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    verify = session_factory()
    turns = verify.query(EncounterTurn).filter_by(
        encounter_id=sample_pending_encounter.id
    ).all()
    enemy_rolls = sorted(
        t.initiative_roll for t in turns if t.enemy_id is not None
    )
    assert enemy_rolls == [6, 8]
    verify.close()


async def test_start_encounter_shared_mode_all_enemies_same_roll(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """In SHARED mode all enemies share one initiative roll."""
    sample_pending_encounter.party.characters.append(sample_character)

    enemy_one = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Wolf 1",
        type_name="Wolf",
        initiative_modifier=2,
        max_hp=11,
        current_hp=11,
    )
    enemy_two = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Troll",
        type_name="Troll",
        initiative_modifier=0,
        max_hp=84,
        current_hp=84,
    )
    db_session.add_all([enemy_one, enemy_two])

    settings = PartySettings(
        party_id=sample_pending_encounter.party_id,
        initiative_mode=EnemyInitiativeMode.SHARED,
    )
    db_session.add(settings)
    db_session.commit()

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    mocker.patch("commands.encounter_commands.random.randint", return_value=9)

    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    verify = session_factory()
    turns = verify.query(EncounterTurn).filter_by(
        encounter_id=sample_pending_encounter.id
    ).all()
    enemy_rolls = {t.initiative_roll for t in turns if t.enemy_id is not None}
    assert len(enemy_rolls) == 1
    verify.close()


async def test_start_encounter_default_mode_is_by_type(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """When no PartySettings exist, enemies with the same type_name share a roll."""
    sample_pending_encounter.party.characters.append(sample_character)

    goblin_a = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Goblin A",
        type_name="Goblin",
        initiative_modifier=1,
        max_hp=7,
        current_hp=7,
    )
    goblin_b = Enemy(
        encounter_id=sample_pending_encounter.id,
        name="Goblin B",
        type_name="Goblin",
        initiative_modifier=1,
        max_hp=7,
        current_hp=7,
    )
    db_session.add_all([goblin_a, goblin_b])
    db_session.commit()

    # No PartySettings row created — should default to BY_TYPE behaviour.

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    mocker.patch("commands.encounter_commands.random.randint", return_value=7)

    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    verify = session_factory()
    turns = verify.query(EncounterTurn).filter_by(
        encounter_id=sample_pending_encounter.id
    ).all()
    goblin_a_turn = next(t for t in turns if t.enemy_id == goblin_a.id)
    goblin_b_turn = next(t for t in turns if t.enemy_id == goblin_b.id)
    assert goblin_a_turn.initiative_roll == goblin_b_turn.initiative_roll
    verify.close()


# ---------------------------------------------------------------------------
# /encounter damage — Phase 3
# ---------------------------------------------------------------------------


async def test_encounter_damage_reduces_enemy_hp(
    encounter_bot, sample_active_encounter, sample_enemy, interaction, session_factory
):
    """Dealing damage reduces the enemy's current_hp by the damage amount."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=3)

    verify = session_factory()
    refreshed = verify.get(Enemy, sample_enemy.id)
    assert refreshed.current_hp == 4  # 7 - 3
    verify.close()


async def test_encounter_damage_hp_floored_at_zero(
    encounter_bot, sample_active_encounter, sample_enemy, interaction, session_factory
):
    """Damage exceeding current HP floors at 0 rather than going negative."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=100)

    verify = session_factory()
    refreshed = verify.get(Enemy, sample_enemy.id)
    assert refreshed.current_hp == 0
    verify.close()


async def test_encounter_damage_sends_ephemeral_hp_update(
    encounter_bot, sample_active_encounter, sample_enemy, interaction
):
    """The HP-update response is sent as an ephemeral message to the GM."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=3)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_damage_hp_update_message_contains_enemy_name(
    encounter_bot, sample_active_encounter, sample_enemy, interaction
):
    """The GM's HP-update message contains the enemy name and current HP."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=3)

    msg = interaction.response.send_message.call_args.args[0]
    assert "Goblin" in msg
    assert "4" in msg  # current_hp after 7 - 3


async def test_encounter_damage_enemy_at_zero_removed_from_turns(
    encounter_bot, sample_active_encounter, sample_enemy, interaction, session_factory
):
    """An enemy reduced to 0 HP has its EncounterTurn removed from the DB."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=7)

    verify = session_factory()
    remaining_turns = (
        verify.query(EncounterTurn)
        .filter_by(encounter_id=sample_active_encounter.id)
        .all()
    )
    enemy_turn_ids = [t.enemy_id for t in remaining_turns if t.enemy_id is not None]
    assert sample_enemy.id not in enemy_turn_ids
    verify.close()


async def test_encounter_damage_enemy_death_sends_public_announcement(
    encounter_bot, sample_active_encounter, sample_enemy, interaction
):
    """A public (non-ephemeral) defeat announcement is posted when enemy HP hits 0."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=7)

    followup_call = interaction.followup.send.call_args
    assert followup_call is not None
    public_msg = followup_call.args[0] if followup_call.args else followup_call.kwargs.get("content", "")
    assert "Goblin" in public_msg
    assert followup_call.kwargs.get("ephemeral") is not True


async def test_encounter_damage_invalid_position_shows_error(
    encounter_bot, sample_active_encounter, interaction
):
    """An out-of-range position produces an ephemeral error."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=99, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "99" in msg


async def test_encounter_damage_non_gm_denied(
    encounter_bot, sample_active_encounter, interaction, mocker, db_session, sample_user, sample_active_party
):
    """A non-GM user receives an ephemeral error."""
    non_gm_interaction = make_interaction(mocker, user_id=999)
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(non_gm_interaction, position=2, damage=3)

    assert non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_damage_player_position_rejected(
    encounter_bot, sample_active_encounter, interaction
):
    """Targeting a player's position (position=1) returns an ephemeral error."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=1, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "player" in msg.lower()


async def test_encounter_damage_non_positive_damage_rejected(
    encounter_bot, sample_active_encounter, interaction
):
    """Damage of 0 or less is rejected with an ephemeral error."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=2, damage=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_damage_no_active_encounter(
    encounter_bot, sample_active_party, interaction
):
    """When there is no active encounter, an ephemeral error is returned."""
    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=1, damage=5)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_damage_adjusts_current_turn_index_when_earlier_enemy_removed(
    encounter_bot, db_session, sample_active_party, sample_character, interaction, session_factory
):
    """When an enemy before the current turn index is removed, the index is decremented."""
    # Build an encounter: enemy at position 0 (init 20), char at position 1 (init 15),
    # enemy2 at position 2 (init 10). Set current_turn_index to 1 (char's turn).
    encounter = Encounter(
        name="Index Test",
        party_id=sample_active_party.id,
        server_id=sample_active_party.server_id,
        status=EncounterStatus.ACTIVE,
        current_turn_index=1,
        round_number=1,
        message_id="99999",
        channel_id="333",
    )
    sample_active_party.characters.append(sample_character)
    db_session.add(encounter)
    db_session.flush()

    enemy_front = Enemy(
        encounter_id=encounter.id, name="Front Enemy", type_name="Orc",
        initiative_modifier=0, max_hp=10, current_hp=10,
    )
    enemy_back = Enemy(
        encounter_id=encounter.id, name="Back Enemy", type_name="Orc",
        initiative_modifier=0, max_hp=10, current_hp=10,
    )
    db_session.add_all([enemy_front, enemy_back])
    db_session.flush()

    turn_enemy_front = EncounterTurn(
        encounter_id=encounter.id, enemy_id=enemy_front.id,
        initiative_roll=20, order_position=0,
    )
    turn_char = EncounterTurn(
        encounter_id=encounter.id, character_id=sample_character.id,
        initiative_roll=15, order_position=1,
    )
    turn_enemy_back = EncounterTurn(
        encounter_id=encounter.id, enemy_id=enemy_back.id,
        initiative_roll=10, order_position=2,
    )
    db_session.add_all([turn_enemy_front, turn_char, turn_enemy_back])
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "damage")
    await cb(interaction, position=1, damage=10)  # kill front enemy at position 1

    verify = session_factory()
    refreshed_encounter = verify.get(Encounter, encounter.id)
    # current_turn_index should now be 0 (was 1, one earlier turn removed)
    assert refreshed_encounter.current_turn_index == 0
    verify.close()


# ---------------------------------------------------------------------------
# /encounter view — Phase 3: HP display + GM dual message
# ---------------------------------------------------------------------------


async def test_view_encounter_shows_enemy_hp(
    encounter_bot, sample_active_encounter, sample_enemy, interaction
):
    """The public embed shows current and max HP for enemies."""
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    field_values = " ".join(f.value for f in embed.fields)
    assert "7/7" in field_values  # sample_enemy has current_hp=7, max_hp=7


async def test_view_encounter_gm_gets_ephemeral_details(
    encounter_bot, sample_active_encounter, interaction
):
    """A GM receives an additional ephemeral embed with full enemy details."""
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    # The GM followup must have been sent as ephemeral
    assert interaction.followup.send.called
    followup_kwargs = interaction.followup.send.call_args.kwargs
    assert followup_kwargs.get("ephemeral") is True
    gm_embed = followup_kwargs.get("embed")
    assert gm_embed is not None
    assert "GM" in gm_embed.title


async def test_view_encounter_enemy_ac_hidden_by_default(
    encounter_bot, db_session, sample_active_encounter, sample_enemy, interaction
):
    """Enemy AC is not shown in the public embed when enemy_ac_public is False."""
    sample_enemy.ac = 14
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    field_values = " ".join(f.value for f in embed.fields)
    assert "AC: 14" not in field_values


async def test_view_encounter_enemy_ac_shown_when_setting_on(
    encounter_bot, db_session, sample_active_encounter, sample_enemy, interaction
):
    """Enemy AC appears in the public embed when enemy_ac_public is True."""
    sample_enemy.ac = 14
    from models import PartySettings
    settings = PartySettings(
        party_id=sample_active_encounter.party_id,
        enemy_ac_public=True,
    )
    db_session.add(settings)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    field_values = " ".join(f.value for f in embed.fields)
    assert "AC: 14" in field_values
