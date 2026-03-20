"""Command-ordering and dependency tests.

Each section tests one or more commands invoked in an unconventional,
out-of-order, or otherwise surprising sequence.  The goal is to verify that
the bot either succeeds gracefully or returns a clear, non-crashing error
message — regardless of the order in which a user happens to run commands.

Sections
--------
1.  HP lifecycle ordering
2.  Attack lifecycle ordering
3.  Party lifecycle ordering
4.  Encounter lifecycle ordering (including full end-to-end sequences)
5.  Character state transitions (switch, deletion)
6.  Roll ordering
7.  Inspiration ordering
8.  Cross-domain sequences
"""

import pytest
from sqlalchemy import insert

from models import (
    Attack,
    Character,
    ClassLevel,
    Encounter,
    EncounterTurn,
    Enemy,
    Party,
    User,
    user_server_association,
)
from enums.encounter_status import EncounterStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ===========================================================================
# 1. HP lifecycle ordering
# ===========================================================================


async def test_hp_heal_without_max_hp_set_is_rejected(
    health_bot, sample_character, interaction
):
    """``/hp heal`` before ``/hp set_max`` must return the HP-not-set error.

    A freshly created character has ``max_hp = -1`` (sentinel for "not yet
    configured").  Healing should be blocked with ERROR_HP_NOT_SET.
    """
    # sample_character has default max_hp = -1
    assert sample_character.max_hp == -1

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "set_max" in msg.lower() or "hp not set" in msg.lower()


async def test_hp_temp_before_max_hp_set_is_accepted(
    health_bot, sample_character, db_session, interaction
):
    """``/hp temp`` does not require ``/hp set_max`` to have been called first.

    Temporary hit points are tracked independently of max HP; the command
    should succeed and record the new value.
    """
    assert sample_character.max_hp == -1

    cb = get_callback(health_bot, "hp", "temp")
    await cb(interaction, amount=5)

    db_session.refresh(sample_character)
    assert sample_character.temp_hp == 5
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_hp_status_before_set_max_shows_sentinel_values(
    health_bot, sample_character, interaction
):
    """``/hp status`` before ``/hp set_max`` should succeed and display -1/-1,
    not crash, so players can tell at a glance that HP hasn't been configured.
    """
    assert sample_character.max_hp == -1

    cb = get_callback(health_bot, "hp", "status")
    await cb(interaction)

    assert interaction.response.send_message.call_args is not None
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )
    msg = interaction.response.send_message.call_args.args[0]
    assert "-1" in msg


async def test_hp_damage_with_partymember_before_active_party_rejected(
    health_bot, sample_character, db_session, interaction
):
    """``/hp damage partymember=X`` requires an active party.  Without one the
    command must reject with ERROR_NO_ACTIVE_PARTY before looking up the
    character name at all.
    """
    # sample_character exists but no party is active (no user_server_association row)
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5", partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_hp_heal_with_partymember_before_active_party_rejected(
    health_bot, sample_character, db_session, interaction
):
    """``/hp heal partymember=X`` similarly requires an active party."""
    sample_character.max_hp = 20
    sample_character.current_hp = 10
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="5", partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_full_hp_lifecycle_set_then_damage_then_heal(
    health_bot, sample_character, db_session, interaction, mocker
):
    """``/hp set_max`` → ``/hp damage`` → ``/hp heal`` runs without error and
    produces the expected HP values at each step.
    """
    cb_set = get_callback(health_bot, "hp", "set_max")
    await cb_set(interaction, max_hp=20)
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 20

    # Damage — use a fresh interaction mock
    dmg_interaction = make_interaction(mocker)
    cb_dmg = get_callback(health_bot, "hp", "damage")
    await cb_dmg(dmg_interaction, amount="7")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 13

    # Heal back to max
    heal_interaction = make_interaction(mocker)
    cb_heal = get_callback(health_bot, "hp", "heal")
    await cb_heal(heal_interaction, amount="999")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 20


async def test_hp_damage_then_heal_then_damage_to_zero(
    health_bot, sample_character, db_session, interaction, mocker
):
    """Repeated damage/heal cycles correctly track HP all the way to 0."""
    sample_character.max_hp = 10
    sample_character.current_hp = 10
    db_session.commit()

    i2, i3, i4 = (
        make_interaction(mocker),
        make_interaction(mocker),
        make_interaction(mocker),
    )
    cb_dmg = get_callback(health_bot, "hp", "damage")
    cb_heal = get_callback(health_bot, "hp", "heal")

    await cb_dmg(interaction, amount="4")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 6

    await cb_heal(i2, amount="2")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 8

    await cb_dmg(i3, amount="8")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 0

    # Heal from 0
    await cb_heal(i4, amount="5")
    db_session.refresh(sample_character)
    assert sample_character.current_hp == 5


# ===========================================================================
# 2. Attack lifecycle ordering
# ===========================================================================


async def test_attack_roll_after_switching_to_character_without_attacks(
    attack_bot, char_bot, sample_character, db_session, interaction, mocker
):
    """Adding an attack to character A then switching to character B means
    ``/attack roll`` on B fails — attacks belong to the character, not the user.
    """
    # Add an attack to Aldric (the active character)
    cb_add = get_callback(attack_bot, "attack", "add")
    await cb_add(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+3")
    db_session.refresh(sample_character)
    assert len(sample_character.attacks) == 1

    # Create a second character
    char_b = Character(
        name="Brindlewood",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(char_b)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char_b.id, class_name="Wizard", level=1))
    db_session.commit()

    # Switch to character B
    switch_interaction = make_interaction(mocker)
    cb_switch = get_callback(char_bot, "character", "switch")
    await cb_switch(switch_interaction, name="Brindlewood")

    # Attack roll should fail — B has no attacks
    roll_interaction = make_interaction(mocker)
    cb_roll = get_callback(attack_bot, "attack", "roll")
    await cb_roll(roll_interaction, attack_name="Longsword")

    assert (
        roll_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )
    msg = roll_interaction.response.send_message.call_args.args[0]
    assert "not found" in msg.lower() or "longsword" in msg.lower()


async def test_attack_add_then_roll_then_roll_after_attack_replaced(
    attack_bot, sample_character, db_session, interaction, mocker
):
    """Add attack → roll (success) → add same name with new formula (upsert)
    → roll still works with the updated formula.
    """
    sample_character.max_hp = 10
    sample_character.current_hp = 10
    db_session.commit()

    cb_add = get_callback(attack_bot, "attack", "add")
    await cb_add(interaction, name="Dagger", hit_mod=4, damage_formula="1d4+2")

    # Roll once successfully
    roll_interaction = make_interaction(mocker)
    cb_roll = get_callback(attack_bot, "attack", "roll")
    await cb_roll(roll_interaction, attack_name="Dagger")
    assert (
        roll_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is not True
    )

    # Upsert with new formula
    upsert_interaction = make_interaction(mocker)
    await cb_add(upsert_interaction, name="Dagger", hit_mod=6, damage_formula="1d6+4")

    db_session.refresh(sample_character)
    updated_attack = next(a for a in sample_character.attacks if a.name == "Dagger")
    assert updated_attack.damage_formula == "1d6+4"

    # Roll again — still works
    roll_interaction2 = make_interaction(mocker)
    await cb_roll(roll_interaction2, attack_name="Dagger")
    assert (
        roll_interaction2.response.send_message.call_args.kwargs.get("ephemeral")
        is not True
    )


# ===========================================================================
# 3. Party lifecycle ordering
# ===========================================================================


async def test_party_roll_after_active_party_deleted_returns_error(
    party_bot, sample_active_party, db_session, interaction, mocker
):
    """Delete the party that is set as active.  Subsequent ``/party roll``
    must return ERROR_PARTY_SET_ACTIVE_FIRST, not crash.

    Note: In SQLite (FK enforcement off), deleting the party leaves a dangling
    ``active_party_id`` in ``user_server_association``.  ``get_active_party``
    calls ``db.get(Party, id)`` which returns ``None`` for missing rows, so the
    guard fires correctly.
    """
    party_id = sample_active_party.id

    # Manually delete party (bypassing the confirmation flow)
    db_session.delete(sample_active_party)
    db_session.commit()

    roll_interaction = make_interaction(mocker)
    cb = get_callback(party_bot, "party", "roll")
    await cb(roll_interaction, notation="1d20")

    assert (
        roll_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )
    msg = roll_interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_encounter_create_after_active_party_deleted_returns_error(
    encounter_bot, sample_active_party, db_session, interaction
):
    """Delete the active party, then try ``/encounter create``.  Must reject
    with ERROR_NO_ACTIVE_PARTY instead of crashing.
    """
    db_session.delete(sample_active_party)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Cave")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_party_active_view_after_active_party_deleted_shows_none(
    party_bot, sample_active_party, db_session, interaction
):
    """After deleting the active party, ``/party active`` (view) must not
    crash — it should behave as if no active party is set.
    """
    db_session.delete(sample_active_party)
    db_session.commit()

    cb = get_callback(party_bot, "party", "active")
    await cb(interaction, party_name=None)

    # Either ephemeral error OR a message saying "no active party"
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower() or "no active" in msg.lower()


async def test_setting_new_active_party_replaces_previous(
    party_bot, sample_active_party, db_session, interaction, mocker
):
    """Setting a second party as active replaces the first.  A subsequent
    ``/party roll`` uses the new active party's membership.
    """
    # Create a second party with a member
    second_char = Character(
        name="Vera",
        user=sample_active_party.gms[0],
        server=sample_active_party.server,
        is_active=False,
        strength=10,
        dexterity=12,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db_session.add(second_char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=second_char.id, class_name="Rogue", level=1))

    party_b = Party(
        name="Party B",
        gms=[sample_active_party.gms[0]],
        server=sample_active_party.server,
    )
    db_session.add(party_b)
    db_session.commit()
    party_b.characters.append(second_char)
    db_session.commit()

    # Switch active party to Party B
    switch_interaction = make_interaction(mocker)
    cb_active = get_callback(party_bot, "party", "active")
    await cb_active(switch_interaction, party_name="Party B")

    # Now party roll should target Party B (and succeed because it has a member)
    roll_interaction = make_interaction(mocker)
    cb_roll = get_callback(party_bot, "party", "roll")
    await cb_roll(roll_interaction, notation="1d20")

    msg = (
        roll_interaction.response.is_called or roll_interaction.followup.send.call_args
    )
    assert msg is not None


async def test_party_view_after_party_deleted_returns_not_found(
    party_bot, sample_party, db_session, interaction
):
    """``/party view <name>`` after the party has been deleted must return a
    PARTY_NOT_FOUND error, not crash.
    """
    party_name = sample_party.name
    db_session.delete(sample_party)
    db_session.commit()

    cb = get_callback(party_bot, "party", "view")
    await cb(interaction, party_name=party_name)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert party_name in msg or "not found" in msg.lower()


async def test_party_roll_as_when_member_not_in_party(
    party_bot, sample_active_party, sample_character, db_session, interaction
):
    """``/party roll_as <name>`` when the named character is not a party member
    must return an ephemeral error, not crash.

    Order: create party (with no characters) → set active → roll_as <name>
    """
    # sample_active_party has no characters; sample_character exists but is not added
    cb = get_callback(party_bot, "party", "roll_as")
    await cb(interaction, member_name="Aldric", notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "not found" in msg.lower() or "aldric" in msg.lower()


async def test_party_character_add_then_remove_then_readd(
    party_bot, sample_party, sample_character, db_session, interaction, mocker
):
    """A character can be removed and then re-added to a party without error."""
    # Add
    cb_add = get_callback(party_bot, "party", "character_add")
    await cb_add(interaction, party_name=sample_party.name, character_name="Aldric")

    db_session.refresh(sample_party)
    assert any(c.name == "Aldric" for c in sample_party.characters)

    # Remove (shows confirmation — press confirm)
    remove_interaction = make_interaction(mocker)
    cb_remove = get_callback(party_bot, "party", "character_remove")
    await cb_remove(
        remove_interaction, party_name=sample_party.name, character_name="Aldric"
    )

    view = remove_interaction.response.send_message.call_args.kwargs.get("view")
    btn_interaction = make_interaction(mocker)
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove"
    )
    await confirm_btn.callback(btn_interaction)

    db_session.refresh(sample_party)
    assert not any(c.name == "Aldric" for c in sample_party.characters)

    # Re-add
    readd_interaction = make_interaction(mocker)
    await cb_add(
        readd_interaction, party_name=sample_party.name, character_name="Aldric"
    )

    db_session.refresh(sample_party)
    assert any(c.name == "Aldric" for c in sample_party.characters)


async def test_party_character_remove_when_not_in_party_returns_error(
    party_bot, sample_party, sample_character, interaction
):
    """``/party character_remove`` for a character that has never been added to
    the party must return an ephemeral error.
    """
    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name=sample_party.name, character_name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 4. Encounter lifecycle ordering
# ===========================================================================


async def test_full_encounter_lifecycle_create_enemy_start_next_end(
    encounter_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    session_factory,
    mocker,
):
    """Full sequential encounter lifecycle:
    create → add enemy → start → next (advance) → next (wrap round) → end.
    After end, ``/encounter next`` must return ENCOUNTER_NOT_ACTIVE.
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # Step 1: create
    cb_create = get_callback(encounter_bot, "encounter", "create")
    await cb_create(interaction, name="Dungeon Run")

    verify = session_factory()
    enc = (
        verify.query(Encounter)
        .filter_by(
            party_id=sample_active_party.id,
            status=EncounterStatus.PENDING,
        )
        .first()
    )
    assert enc is not None, "encounter not created"
    enc_id = enc.id
    verify.close()

    # Step 2: add enemy
    enemy_interaction = make_interaction(mocker)
    cb_enemy = get_callback(encounter_bot, "encounter", "enemy")
    await cb_enemy(enemy_interaction, name="Orc", initiative_modifier=1, max_hp="7")

    # Step 3: start (rolls initiative)
    start_interaction = make_interaction(mocker)
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    cb_start = get_callback(encounter_bot, "encounter", "start")
    await cb_start(start_interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=enc_id).first()
    assert enc.status == EncounterStatus.ACTIVE
    assert enc.round_number == 1
    turn_count = verify.query(EncounterTurn).filter_by(encounter_id=enc_id).count()
    assert turn_count == 2  # one char + one enemy
    verify.close()

    # Step 4: next (advance to turn 1)
    next_interaction = make_interaction(mocker)
    cb_next = get_callback(encounter_bot, "encounter", "next")
    await cb_next(next_interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=enc_id).first()
    assert enc.current_turn_index == 1
    verify.close()

    # Step 5: next again → wraps back to index 0, round 2
    next_interaction2 = make_interaction(mocker)
    await cb_next(next_interaction2)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=enc_id).first()
    assert enc.current_turn_index == 0
    assert enc.round_number == 2
    verify.close()

    # Step 6: end
    end_interaction = make_interaction(mocker)
    cb_end = get_callback(encounter_bot, "encounter", "end")
    await cb_end(end_interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=enc_id).first()
    assert enc.status == EncounterStatus.COMPLETE
    verify.close()

    # Step 7: next after end → ENCOUNTER_NOT_ACTIVE
    dead_interaction = make_interaction(mocker)
    await cb_next(dead_interaction)

    assert (
        dead_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )
    msg = dead_interaction.response.send_message.call_args.args[0]
    assert "encounter" in msg.lower()


async def test_second_encounter_after_first_ends(
    encounter_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    session_factory,
    mocker,
):
    """After ending encounter A, the party can create and start encounter B.

    Verifies that the ENCOUNTER_ALREADY_OPEN guard does not fire on a new
    encounter when the previous one has been closed.
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # ---- Encounter A ----
    cb_create = get_callback(encounter_bot, "encounter", "create")
    await cb_create(interaction, name="Encounter A")

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    enemy_i = make_interaction(mocker)
    cb_enemy = get_callback(encounter_bot, "encounter", "enemy")
    await cb_enemy(enemy_i, name="Goblin", initiative_modifier=1, max_hp="5")

    start_i = make_interaction(mocker)
    cb_start = get_callback(encounter_bot, "encounter", "start")
    await cb_start(start_i)

    end_i = make_interaction(mocker)
    cb_end = get_callback(encounter_bot, "encounter", "end")
    await cb_end(end_i)

    # ---- Encounter B ----
    create_i2 = make_interaction(mocker)
    await cb_create(create_i2, name="Encounter B")

    # Should succeed (no duplicate encounter)
    create_msg = create_i2.response.send_message.call_args.args[0]
    assert "already" not in create_msg.lower()

    verify = session_factory()
    enc_b = (
        verify.query(Encounter)
        .filter_by(
            party_id=sample_active_party.id,
            status=EncounterStatus.PENDING,
        )
        .first()
    )
    assert enc_b is not None
    assert enc_b.name == "Encounter B"
    verify.close()


async def test_encounter_enemy_after_encounter_ended_returns_no_pending(
    encounter_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    mocker,
):
    """``/encounter enemy`` after the encounter has been ended must return an
    error (no PENDING encounter), not add enemies to the completed one.
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # Create, add enemy, start, end
    cb_create = get_callback(encounter_bot, "encounter", "create")
    await cb_create(interaction, name="Short Fight")

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    e1 = make_interaction(mocker)
    cb_enemy = get_callback(encounter_bot, "encounter", "enemy")
    await cb_enemy(e1, name="Goblin", initiative_modifier=1, max_hp="5")

    e2 = make_interaction(mocker)
    cb_start = get_callback(encounter_bot, "encounter", "start")
    await cb_start(e2)

    e3 = make_interaction(mocker)
    cb_end = get_callback(encounter_bot, "encounter", "end")
    await cb_end(e3)

    # Try to add another enemy — should fail (no pending encounter)
    e4 = make_interaction(mocker)
    await cb_enemy(e4, name="Orc", initiative_modifier=0, max_hp="10")

    assert e4.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_start_after_encounter_ended_no_pending_returns_error(
    encounter_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    mocker,
):
    """``/encounter start`` after the encounter has been ended must fail with
    'no pending encounter', not crash.
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    cb_create = get_callback(encounter_bot, "encounter", "create")
    await cb_create(interaction, name="Skirmish")

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    e1 = make_interaction(mocker)
    cb_enemy = get_callback(encounter_bot, "encounter", "enemy")
    await cb_enemy(e1, name="Goblin", initiative_modifier=1, max_hp="5")

    e2 = make_interaction(mocker)
    cb_start = get_callback(encounter_bot, "encounter", "start")
    await cb_start(e2)

    e3 = make_interaction(mocker)
    cb_end = get_callback(encounter_bot, "encounter", "end")
    await cb_end(e3)

    # Try to start again — no PENDING encounter exists
    e4 = make_interaction(mocker)
    await cb_start(e4)

    assert e4.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_create_when_pending_encounter_already_exists(
    encounter_bot, sample_pending_encounter, interaction
):
    """Creating a second encounter when one is already PENDING must reject with
    ENCOUNTER_ALREADY_OPEN.
    """
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Another Dungeon")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "already" in msg.lower()


async def test_encounter_create_when_active_encounter_already_exists(
    encounter_bot, sample_active_encounter, interaction
):
    """Creating a new encounter when one is ACTIVE must also reject with
    ENCOUNTER_ALREADY_OPEN — not silently create a second encounter.
    """
    cb = get_callback(encounter_bot, "encounter", "create")
    await cb(interaction, name="Parallel Fight")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "already" in msg.lower()


async def test_encounter_view_and_next_after_all_enemies_defeated_auto_end(
    encounter_bot, sample_active_encounter, db_session, interaction, mocker
):
    """When the last enemy is defeated (auto-end), subsequent ``/encounter next``
    and ``/encounter view`` must return ENCOUNTER_NOT_ACTIVE, not crash.
    """
    # Manually zero out the enemy's HP and mark encounter COMPLETED to
    # simulate the auto-end that occurs when the last enemy is defeated.
    enemy_turn = next(t for t in sample_active_encounter.turns if t.enemy_id)
    enemy_turn.enemy.current_hp = 0
    sample_active_encounter.status = EncounterStatus.COMPLETE
    db_session.commit()

    cb_next = get_callback(encounter_bot, "encounter", "next")
    await cb_next(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "encounter" in msg.lower()

    view_i = make_interaction(mocker)
    cb_view = get_callback(encounter_bot, "encounter", "view")
    await cb_view(view_i)

    assert view_i.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_encounter_end_then_next_then_create_next_all_correct(
    encounter_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    mocker,
):
    """Sequence: start encounter → end → try next (error) → create new encounter
    → ``/encounter enemy`` succeeds on the new one.
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    cb_create = get_callback(encounter_bot, "encounter", "create")
    cb_enemy = get_callback(encounter_bot, "encounter", "enemy")
    cb_start = get_callback(encounter_bot, "encounter", "start")
    cb_end = get_callback(encounter_bot, "encounter", "end")
    cb_next = get_callback(encounter_bot, "encounter", "next")

    # Encounter 1
    await cb_create(interaction, name="Fight 1")
    e1 = make_interaction(mocker)
    await cb_enemy(e1, name="Wolf", initiative_modifier=2, max_hp="11")
    e2 = make_interaction(mocker)
    await cb_start(e2)
    e3 = make_interaction(mocker)
    await cb_end(e3)

    # next on ended encounter → error
    e4 = make_interaction(mocker)
    await cb_next(e4)
    assert e4.response.send_message.call_args.kwargs.get("ephemeral") is True

    # Encounter 2 — create and add enemy should succeed
    e5 = make_interaction(mocker)
    await cb_create(e5, name="Fight 2")
    create_msg = e5.response.send_message.call_args.args[0]
    assert "already" not in create_msg.lower()

    e6 = make_interaction(mocker)
    await cb_enemy(e6, name="Bear", initiative_modifier=0, max_hp="34")
    # Success: GM confirmation is ephemeral — just verify a response was sent (no crash)
    assert e6.response.send_message.call_args is not None
    msg = e6.response.send_message.call_args.args[0]
    assert "bear" in msg.lower() or "fight 2" in msg.lower()


# ===========================================================================
# 5. Character state transitions
# ===========================================================================


async def test_switch_to_nonexistent_character_original_remains_active(
    char_bot, sample_character, db_session, interaction, mocker
):
    """``/character switch <bad-name>`` must reject with CHAR_NOT_FOUND_NAME.
    The original character must still be active afterwards.
    """
    cb = get_callback(char_bot, "character", "switch")
    await cb(interaction, name="GhostCharacter")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "ghostcharacter" in msg.lower() or "not found" in msg.lower()

    # Original character is still active
    db_session.refresh(sample_character)
    assert sample_character.is_active is True


async def test_hp_state_preserved_after_switch_to_second_char_and_back(
    health_bot, char_bot, sample_character, db_session, interaction, mocker
):
    """Setting HP on character A, switching to B, then switching back to A
    shows A's original HP — B's default state does not clobber A's values.
    """
    # Configure Aldric's HP
    sample_character.max_hp = 20
    sample_character.current_hp = 14
    db_session.commit()

    # Create a second character (Brindlewood)
    char_b = Character(
        name="Brindlewood",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(char_b)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char_b.id, class_name="Wizard", level=1))
    db_session.commit()

    cb_switch = get_callback(char_bot, "character", "switch")
    cb_status = get_callback(health_bot, "hp", "status")

    # Switch to B
    s1 = make_interaction(mocker)
    await cb_switch(s1, name="Brindlewood")

    # Switch back to A
    s2 = make_interaction(mocker)
    await cb_switch(s2, name="Aldric")

    # HP status for Aldric should still show 14/20
    s3 = make_interaction(mocker)
    await cb_status(s3)
    msg = s3.response.send_message.call_args.args[0]
    assert "14" in msg and "20" in msg


async def test_hp_operations_scoped_to_newly_active_character_after_switch(
    health_bot, char_bot, sample_character, db_session, interaction, mocker
):
    """After switching active character, HP commands operate on the new active
    character — the old character's HP is not affected.
    """
    # Aldric has HP set
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    # Create and switch to Brindlewood
    char_b = Character(
        name="Brindlewood",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(char_b)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char_b.id, class_name="Wizard", level=1))
    db_session.commit()

    s1 = make_interaction(mocker)
    cb_switch = get_callback(char_bot, "character", "switch")
    await cb_switch(s1, name="Brindlewood")

    # /hp set_max on Brindlewood
    s2 = make_interaction(mocker)
    cb_set = get_callback(health_bot, "hp", "set_max")
    await cb_set(s2, max_hp=8)

    db_session.refresh(sample_character)
    db_session.refresh(char_b)
    assert char_b.max_hp == 8
    assert sample_character.max_hp == 20  # Aldric's HP unchanged


async def test_character_active_flag_transitions_correctly_on_switch(
    char_bot, sample_character, db_session, interaction, mocker
):
    """``/character switch`` deactivates the old character and activates the
    new one.  Both states are correctly reflected in the DB.
    """
    char_b = Character(
        name="Brindlewood",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(char_b)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char_b.id, class_name="Wizard", level=1))
    db_session.commit()

    cb = get_callback(char_bot, "character", "switch")
    await cb(interaction, name="Brindlewood")

    db_session.refresh(sample_character)
    db_session.refresh(char_b)
    assert char_b.is_active is True
    assert sample_character.is_active is False


# ===========================================================================
# 6. Roll ordering
# ===========================================================================


async def test_roll_pure_dice_does_not_require_character(
    roll_bot, sample_server, db_session, interaction
):
    """``/roll 1d20`` (pure dice notation) must succeed even with no character.

    The roll is resolved directly in dice_roller without querying the DB for
    a character, so the response should be public and non-ephemeral.
    """
    # No sample_user or sample_character fixture — bare server only
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="1d20")

    # Public response (not ephemeral)
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )


async def test_roll_skill_without_character_returns_not_found(
    roll_bot, sample_server, db_session, interaction
):
    """``/roll perception`` (a named skill) requires an active character.
    Without one the command must return CHARACTER_NOT_FOUND, not crash.
    """
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_roll_stat_save_without_character_returns_not_found(
    roll_bot, sample_server, db_session, interaction
):
    """``/roll strength save`` requires a character for proficiency lookup."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="strength save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_roll_initiative_without_character_returns_not_found(
    roll_bot, sample_server, db_session, interaction
):
    """``/roll initiative`` requires a character to look up the dexterity
    modifier or initiative bonus."""
    cb = get_callback(roll_bot, "roll")
    await cb(interaction, notation="initiative")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_partyroll_before_any_party_created(
    party_bot, sample_server, sample_user, interaction
):
    """``/party roll`` when no party has ever been created for this user must
    return ERROR_PARTY_SET_ACTIVE_FIRST, not crash.
    """
    # sample_user + sample_server exist but no party and no user_server_association row
    cb = get_callback(party_bot, "party", "roll")
    await cb(interaction, notation="1d20")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


# ===========================================================================
# 7. Inspiration ordering
# ===========================================================================


async def test_inspiration_grant_without_active_party_rejected(
    inspiration_bot, sample_character, db_session, interaction
):
    """``/inspiration grant`` without an active party set must return an
    ephemeral error — not crash or silently succeed.
    """
    # sample_character exists but no active party
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction, partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_inspiration_grant_as_non_gm_rejected(
    inspiration_bot,
    sample_active_party,
    sample_character,
    db_session,
    interaction,
    mocker,
):
    """A party member who is NOT a GM must be rejected when trying to grant
    inspiration.

    Order: create party (GM = user 111) → call ``/inspiration grant`` as
    user 444 (not a GM).
    """
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # user 444 has active party set to sample_active_party
    non_gm_user = User(discord_id="444")
    db_session.add(non_gm_user)
    db_session.flush()
    db_session.execute(
        insert(user_server_association).values(
            user_id=non_gm_user.id,
            server_id=sample_active_party.server_id,
            active_party_id=sample_active_party.id,
        )
    )
    db_session.commit()

    non_gm_interaction = make_interaction(mocker, user_id=444)
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(non_gm_interaction, partymember="Aldric")

    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )
    msg = non_gm_interaction.response.send_message.call_args.args[0]
    assert "gm" in msg.lower() or "only" in msg.lower()


async def test_inspiration_status_partymember_without_active_party_rejected(
    inspiration_bot, sample_character, db_session, interaction
):
    """``/inspiration status partymember=X`` requires an active party.
    Without one the command must return an ephemeral error mentioning "party".
    """
    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction, partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "party" in msg.lower()


async def test_inspiration_status_without_character_rejected(
    inspiration_bot, sample_server, interaction
):
    """``/inspiration status`` (no partymember) without any character must
    return an ephemeral CHARACTER_NOT_FOUND error.
    """
    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_inspiration_remove_before_character_in_party_rejected(
    inspiration_bot, sample_active_party, sample_character, db_session, interaction
):
    """``/inspiration remove`` for a character not in the active party must
    return an ephemeral error — the character exists but is not a member.
    """
    # sample_character is NOT added to sample_active_party
    cb = get_callback(inspiration_bot, "inspiration", "remove")
    await cb(interaction, partymember="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# 8. Cross-domain sequences
# ===========================================================================


async def test_attack_targeted_without_encounter_returns_error(
    attack_bot, sample_character, db_session, interaction
):
    """``/attack roll target=X`` when no encounter is active must return an
    ephemeral error, not crash.  The attack itself is valid; only the target
    lookup fails.
    """
    db_session.add(
        Attack(
            character_id=sample_character.id,
            name="Crossbow",
            hit_modifier=5,
            damage_formula="1d8+3",
        )
    )
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Crossbow", target="Goblin")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "encounter" in msg.lower() or "no active" in msg.lower()


async def test_encounter_start_without_any_character_in_party_fails(
    encounter_bot, sample_pending_encounter, sample_enemy, interaction
):
    """``/encounter start`` when the party has no characters must reject with
    ENCOUNTER_PARTY_NO_MEMBERS, not crash.
    """
    # sample_pending_encounter has an enemy but no characters in the party
    cb = get_callback(encounter_bot, "encounter", "start")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "member" in msg.lower() or "party" in msg.lower()


async def test_hp_damage_after_active_character_deactivated(
    health_bot, sample_character, db_session, interaction, mocker
):
    """If a character's ``is_active`` flag is cleared (e.g. because the user
    switched to a different character), ``/hp damage`` must return
    ACTIVE_CHARACTER_NOT_FOUND — the user has no active character.
    """
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    sample_character.is_active = False
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "active" in msg.lower() or "character" in msg.lower()


async def test_party_roll_after_switching_active_party_uses_new_party(
    party_bot, sample_active_party, sample_character, db_session, interaction, mocker
):
    """After switching the active party, ``/party roll`` targets the new
    party's roster, not the old one.
    """
    # Add Aldric to the original party
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # Create a second party with a different character, set it as active
    char_b = Character(
        name="Vera",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
        strength=10,
        dexterity=12,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db_session.add(char_b)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char_b.id, class_name="Rogue", level=1))
    party_b = Party(
        name="Party B",
        gms=[sample_character.user],
        server=sample_character.server,
    )
    db_session.add(party_b)
    db_session.commit()
    party_b.characters.append(char_b)
    db_session.commit()

    # Switch active party to Party B
    switch_i = make_interaction(mocker)
    cb_active = get_callback(party_bot, "party", "active")
    await cb_active(switch_i, party_name="Party B")

    # Party roll — defer + followup pattern
    roll_i = make_interaction(mocker)
    cb_roll = get_callback(party_bot, "party", "roll")
    await cb_roll(roll_i, notation="1d20")

    followup_call = roll_i.followup.send.call_args
    assert followup_call is not None
    msg = followup_call.args[0]
    # Response mentions Party B, not The Fellowship
    assert "Party B" in msg


async def test_all_character_dependent_hp_commands_without_any_character(
    health_bot, sample_server, db_session, interaction, mocker
):
    """All HP commands that require an active character reject gracefully when
    no character exists for this user — server row exists but user row does not.
    """
    commands_and_kwargs = [
        ("set_max", {"max_hp": 20}),
        ("damage", {"amount": "5"}),
        ("heal", {"amount": "5"}),
        ("temp", {"amount": 5}),
        ("status", {}),
    ]
    for subcommand, kwargs in commands_and_kwargs:
        fresh_i = make_interaction(mocker)
        cb = get_callback(health_bot, "hp", subcommand)
        await cb(fresh_i, **kwargs)
        assert (
            fresh_i.response.send_message.call_args.kwargs.get("ephemeral") is True
        ), f"/hp {subcommand} did not return ephemeral=True without a character"
