"""
Comprehensive edge-case tests covering unusual / adversarial user flows.

Sections
--------
1. Encounter lifecycle — deleting / removing characters mid-encounter
2. Multi-encounter same-server — scoping bug in /encounter next & view
3. Character-state edge cases — null stats, switch, empty party
4. HP / health edge cases — zero HP, overheal, damage during encounter

Tests whose names end in ``_no_guard`` document a *missing* validation that
allows a potentially dangerous state.  These tests currently *pass* (because
the code has no guard), but the passing state is the problematic outcome.

Tests marked ``xfail`` expose a known defect where the current code produces
incorrect results.  They are discussed at the bottom of this module docstring.

Known bugs found during this test run
--------------------------------------
BUG-1  ``/party character_remove`` has no guard for active encounters.
       A character can be removed from a party while their EncounterTurn is
       live.  The turn row survives (character still exists in DB), so the
       encounter keeps running, but the character is no longer a party member.

BUG-2  ``/party delete`` has no guard for open (PENDING or ACTIVE) encounters.
       In SQLite (FK enforcement off by default) the party row is silently
       deleted and the Encounter row is left with a dangling party_id.  On
       PostgreSQL this is a FK violation at commit time.  After deletion,
       any call to /encounter next or /encounter view that dereferences
       encounter.party will raise AttributeError.

BUG-3  ``/encounter next`` and ``/encounter view`` query for active encounters
       at the *server* level without scoping to the user's party.  When two
       parties on the same server both run simultaneous encounters the query
       returns an indeterminate encounter.  A GM of Party B will be blocked
       from advancing their own encounter (they hit the "unauthorized" guard
       on Party A's encounter) and cannot progress combat.
"""

import pytest
import discord
from sqlalchemy import insert

from models import (
    User,
    Server,
    Character,
    Party,
    Encounter,
    Enemy,
    EncounterTurn,
    ClassLevel,
    user_server_association,
)
from enums.encounter_status import EncounterStatus
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def second_user(db_session, sample_server):
    """A second Discord user (ID 444) registered on the same server."""
    u = User(discord_id="444")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def second_character(db_session, second_user, sample_server):
    """A second character owned by second_user, stats set."""
    char = Character(
        name="Zara",
        user=second_user,
        server=sample_server,
        is_active=True,
        dexterity=14,
        strength=10,
        constitution=12,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db_session.add(char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=char.id, class_name="Rogue", level=3))
    db_session.commit()
    db_session.refresh(char)
    return char


@pytest.fixture
def second_active_encounter(db_session, sample_server, second_user, second_character):
    """A fully active encounter belonging to a *second* party on the same server.
    The encounter has one character turn (Zara) and one enemy turn (Spider),
    with Zara going first.  This mirrors sample_active_encounter for Party 2."""
    party2 = Party(name="Team Two", gms=[second_user], server=sample_server)
    db_session.add(party2)
    db_session.flush()
    party2.characters.append(second_character)

    enc = Encounter(
        name="Cave Battle",
        party_id=party2.id,
        server_id=sample_server.id,
        status=EncounterStatus.ACTIVE,
        current_turn_index=0,
        round_number=1,
        message_id="88888",
        channel_id="333",
    )
    db_session.add(enc)
    db_session.flush()

    spider = Enemy(encounter_id=enc.id, name="Spider", initiative_modifier=0, max_hp=5)
    db_session.add(spider)
    db_session.flush()

    char_turn = EncounterTurn(
        encounter_id=enc.id,
        character_id=second_character.id,
        initiative_roll=15,
        order_position=0,
    )
    enemy_turn = EncounterTurn(
        encounter_id=enc.id,
        enemy_id=spider.id,
        initiative_roll=10,
        order_position=1,
    )
    db_session.add_all([char_turn, enemy_turn])
    db_session.commit()
    db_session.refresh(enc)
    return enc


# ===========================================================================
# 1.  Encounter lifecycle — character / party mutations mid-encounter
# ===========================================================================

# ---------------------------------------------------------------------------
# 1a. /character delete while encounter is PENDING (no turns yet)
# ---------------------------------------------------------------------------


async def test_delete_character_allowed_when_encounter_pending(
    mocker,
    char_bot,
    sample_character,
    sample_pending_encounter,
    db_session,
    interaction,
    session_factory,
):
    """Character can be deleted while there is only a PENDING encounter.

    The guard in /character delete checks for an EncounterTurn whose encounter
    is ACTIVE.  Since turns are created only at /encounter start, a PENDING
    encounter has no turns, so the plain (non-encounter) confirmation is shown
    and deletion proceeds after confirmation.
    """
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    # Shows confirmation (ephemeral), but NOT the encounter-specific warning
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "initiative" not in msg.lower()

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
    verify.close()


async def test_start_encounter_after_only_character_deleted(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_enemy,
    sample_character,
    db_session,
    interaction,
):
    """If the only party character is deleted before /encounter start, the start
    command should reject with an ephemeral 'party has no members' error."""
    sample_pending_encounter.party.characters.append(sample_character)
    db_session.commit()

    # Delete character (allowed — encounter is only PENDING)
    sample_pending_encounter.party.characters.remove(sample_character)
    db_session.delete(sample_character)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "start")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# 1b. /character delete while encounter is ACTIVE (should be blocked)
# ---------------------------------------------------------------------------


async def test_delete_character_blocked_during_active_encounter(
    char_bot, sample_active_encounter, sample_character, interaction
):
    """The guard in /character delete must reject deletion when the character
    has a live EncounterTurn in an ACTIVE encounter."""
    cb = get_callback(char_bot, "character", "delete")
    await cb(interaction, name="Aldric")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# FIX-1: /party character_remove shows confirmation when in active encounter
# ---------------------------------------------------------------------------


async def test_character_remove_during_active_encounter_sends_confirmation(
    party_bot, sample_active_encounter, interaction
):
    """When the target character is in an active encounter, the command sends
    an ephemeral confirmation message with ✅/❌ buttons instead of removing
    immediately."""
    party = sample_active_encounter.party
    char = next(t.character for t in sample_active_encounter.turns if t.character_id)

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name=party.name, character_name=char.name)

    msg = interaction.response.send_message.call_args.args[0]
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    assert char.name in msg
    assert "encounter" in msg.lower()

    # Confirmation view attached
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None


async def test_character_remove_shows_confirmation_when_no_active_encounter(
    mocker,
    party_bot,
    sample_party,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """Without an active encounter the command shows a plain confirmation prompt.
    After confirming, the character is removed from the party."""
    sample_party.characters.append(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(
        interaction, party_name=sample_party.name, character_name=sample_character.name
    )

    # Confirmation is always shown (ephemeral)
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    assert view is not None
    # Plain confirmation — no encounter warning
    msg = interaction.response.send_message.call_args.args[0]
    assert "encounter" not in msg.lower()

    # Press confirm
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    party = verify.query(Party).filter_by(id=sample_party.id).first()
    assert not any(c.name == sample_character.name for c in party.characters)
    verify.close()


async def test_character_remove_confirmation_confirmed_deletes_turn_and_removes(
    mocker, party_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """Pressing ✅ on the confirmation deletes the EncounterTurn and removes
    the character from the party."""
    party = sample_active_encounter.party
    char = next(t.character for t in sample_active_encounter.turns if t.character_id)

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name=party.name, character_name=char.name)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    button_interaction = make_interaction(mocker, user_id=111)
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove"
    )
    await confirm_btn.callback(button_interaction)

    verify = session_factory()
    # Character removed from party
    refreshed_party = verify.query(Party).filter_by(id=party.id).first()
    assert char not in refreshed_party.characters
    # EncounterTurn cascade-deleted
    surviving_turns = verify.query(EncounterTurn).filter_by(character_id=char.id).all()
    assert len(surviving_turns) == 0
    verify.close()


async def test_character_remove_confirmation_cancelled_no_changes(
    mocker, party_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """Pressing ❌ cancels the removal — party membership and encounter turn
    are both left untouched."""
    party = sample_active_encounter.party
    char = next(t.character for t in sample_active_encounter.turns if t.character_id)

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name=party.name, character_name=char.name)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    button_interaction = make_interaction(mocker, user_id=111)
    cancel_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Cancel"
    )
    await cancel_btn.callback(button_interaction)

    verify = session_factory()
    refreshed_party = verify.query(Party).filter_by(id=party.id).first()
    assert any(c.id == char.id for c in refreshed_party.characters)
    surviving_turns = verify.query(EncounterTurn).filter_by(character_id=char.id).all()
    assert len(surviving_turns) == 1
    verify.close()


async def test_character_remove_confirmed_adjusts_turn_index_when_earlier_removed(
    mocker, party_bot, sample_active_encounter, db_session, interaction, session_factory
):
    """When the removed character's turn comes before the current turn index,
    current_turn_index must be decremented so the same participant keeps the
    spotlight after the removal."""
    # Advance to turn 1 (Goblin) so Aldric (position 0) is "behind" the cursor
    sample_active_encounter.current_turn_index = 1
    db_session.commit()

    party = sample_active_encounter.party
    char = next(t.character for t in sample_active_encounter.turns if t.character_id)

    cb = get_callback(party_bot, "party", "character_remove")
    await cb(interaction, party_name=party.name, character_name=char.name)

    view = interaction.response.send_message.call_args.kwargs.get("view")
    button_interaction = make_interaction(mocker, user_id=111)
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Remove"
    )
    await confirm_btn.callback(button_interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    # Only 1 turn left (the enemy); index must shift from 1 → 0
    assert enc.current_turn_index == 0
    verify.close()


# ---------------------------------------------------------------------------
# BUG-2: /party delete has no guard for open encounters
# ---------------------------------------------------------------------------


async def test_party_delete_with_pending_encounter_auto_completes(
    mocker, party_bot, sample_pending_encounter, interaction, session_factory
):
    """FIX-2a: Deleting a party with a PENDING encounter shows a confirmation that
    mentions the encounter.  After confirming, the encounter is cascade-deleted
    with the party."""
    party = sample_pending_encounter.party
    enc_id = sample_pending_encounter.id

    cb = get_callback(party_bot, "party", "delete")
    await cb(interaction, party_name=party.name)

    # Confirmation mentions the open encounter
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "Test Dungeon" in msg or "encounter" in msg.lower()

    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Party).filter_by(name=party.name).first() is None
    # Encounter is cascade-deleted with the party
    assert verify.query(Encounter).filter_by(id=enc_id).first() is None
    verify.close()


async def test_party_delete_with_active_encounter_auto_completes(
    mocker, party_bot, sample_active_encounter, interaction, session_factory
):
    """FIX-2b: Same behaviour for an ACTIVE encounter — cascade-deleted after
    confirmation, no IntegrityError."""
    party = sample_active_encounter.party
    enc_id = sample_active_encounter.id

    cb = get_callback(party_bot, "party", "delete")
    await cb(interaction, party_name=party.name)

    # Confirmation shows encounter warning
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Party).filter_by(name=party.name).first() is None
    assert verify.query(Encounter).filter_by(id=enc_id).first() is None
    verify.close()


async def test_party_delete_without_encounter_still_works(
    mocker, party_bot, sample_party, interaction, session_factory
):
    """Deleting a party that has no encounters shows a plain confirmation then deletes."""
    cb = get_callback(party_bot, "party", "delete")
    await cb(interaction, party_name=sample_party.name)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    view = interaction.response.send_message.call_args.kwargs.get("view")
    confirm_btn = next(
        item for item in view.children if getattr(item, "label", "") == "Delete"
    )
    btn_interaction = mocker.AsyncMock(spec=discord.Interaction)
    btn_interaction.response = mocker.AsyncMock()
    await confirm_btn.callback(btn_interaction)

    verify = session_factory()
    assert verify.query(Party).filter_by(name=sample_party.name).first() is None
    verify.close()


# ===========================================================================
# 2.  Multi-encounter / same-server scoping bug  (BUG-3)
# ===========================================================================

# ---------------------------------------------------------------------------
# FIX-3: /encounter next and /encounter view scoped to the user's active party
# ---------------------------------------------------------------------------


async def test_next_turn_scoped_to_users_party_when_multiple_active(
    mocker,
    encounter_bot,
    sample_active_encounter,
    second_active_encounter,
    db_session,
    session_factory,
):
    """FIX-3a: The GM of Party 2 can advance their own encounter even when
    Party 1 also has an active encounter on the same server.

    The query is now scoped to the user's active party, so Party 1's encounter
    is never touched.
    """
    # Set user 444 as the active-party owner for "Team Two" so the query can
    # resolve their active party.
    from sqlalchemy import insert as sa_insert

    second_party = second_active_encounter.party
    second_user = second_party.gms[0]
    server = second_active_encounter.server
    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=second_user.id,
            server_id=server.id,
            active_party_id=second_party.id,
        )
    )
    db_session.commit()

    user2_interaction = make_interaction(mocker, user_id=444)
    cb = get_callback(encounter_bot, "encounter", "next")
    await cb(user2_interaction)

    verify = session_factory()
    enc1 = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    enc2 = verify.query(Encounter).filter_by(id=second_active_encounter.id).first()
    assert enc1.current_turn_index == 0, "Party 1 encounter must NOT be advanced"
    assert enc2.current_turn_index == 1, "Party 2 encounter must advance"
    verify.close()


async def test_view_encounter_scoped_to_users_party_when_multiple_active(
    mocker, encounter_bot, sample_active_encounter, second_active_encounter, db_session
):
    """FIX-3b: /encounter view returns the correct encounter for each party's GM."""
    from sqlalchemy import insert as sa_insert

    second_party = second_active_encounter.party
    second_user = second_party.gms[0]
    server = second_active_encounter.server
    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=second_user.id,
            server_id=server.id,
            active_party_id=second_party.id,
        )
    )
    db_session.commit()

    user2_interaction = make_interaction(mocker, user_id=444)
    cb = get_callback(encounter_bot, "encounter", "view")
    await cb(user2_interaction)

    embed = user2_interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Cave Battle" in embed.title


# ===========================================================================
# 3.  Character-state edge cases
# ===========================================================================


async def test_start_encounter_with_null_stats_character(
    mocker,
    encounter_bot,
    sample_pending_encounter,
    sample_enemy,
    sample_character_no_stats,
    db_session,
    interaction,
    session_factory,
):
    """A character whose stats are all NULL (never set up) can still participate
    in combat.  roll_initiative_for_character handles None dexterity safely by
    returning a modifier of 0.  The encounter starts normally."""
    sample_pending_encounter.party.characters.append(sample_character_no_stats)
    db_session.commit()

    cb = get_callback(encounter_bot, "encounter", "start")
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    await cb(interaction)

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_pending_encounter.id).first()
    assert enc.status == EncounterStatus.ACTIVE
    turns = verify.query(EncounterTurn).filter_by(encounter_id=enc.id).all()
    assert len(turns) == 2
    verify.close()


async def test_switch_active_character_does_not_change_encounter_turn(
    char_bot,
    encounter_bot,
    sample_active_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """Switching a player's active character mid-encounter does not change
    whose turn it is in the initiative order.  EncounterTurn rows reference
    a specific character_id and are unaffected by the is_active flag."""
    # Create a second character for user 111 to switch to
    alt_char = Character(
        name="Backup",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
        dexterity=10,
        strength=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    db_session.add(alt_char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=alt_char.id, class_name="Wizard", level=1))
    db_session.commit()

    cb_switch = get_callback(char_bot, "character", "switch")
    await cb_switch(interaction, name="Backup")

    # The switch itself should succeed
    assert (
        interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
    )

    # Aldric still owns turn index 0 in the encounter
    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    first_turn = min(enc.turns, key=lambda t: t.order_position)
    assert first_turn.character.name == "Aldric"
    verify.close()


async def test_party_roll_after_member_removed(
    party_bot, sample_active_party, sample_character, db_session, interaction
):
    """Party roll only includes characters currently in the party.
    After removing a character, they are excluded from subsequent rolls."""
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    # Remove the character from the party
    sample_active_party.characters.remove(sample_character)
    db_session.commit()

    cb = get_callback(party_bot, "party", "roll")
    await cb(interaction, notation="perception")

    msg = interaction.response.send_message.call_args.args[0]
    # Party is now empty → should report empty party
    assert (
        "empty" in msg.lower()
        or interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# ===========================================================================
# 4.  HP / health edge cases
# ===========================================================================


async def test_damage_during_active_encounter_does_not_end_encounter(
    health_bot,
    sample_active_encounter,
    sample_character,
    db_session,
    interaction,
    session_factory,
):
    """Applying lethal damage during an encounter brings HP to 0 and shows
    the death message, but does NOT automatically end the encounter.
    The GM must call /encounter end explicitly."""
    sample_character.max_hp = 10
    sample_character.current_hp = 3
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="3")

    msg = interaction.response.send_message.call_args.args[0]
    assert "0/10" in msg

    verify = session_factory()
    enc = verify.query(Encounter).filter_by(id=sample_active_encounter.id).first()
    assert enc.status == EncounterStatus.ACTIVE
    verify.close()


async def test_overheal_is_capped_at_max_hp(
    health_bot, sample_character, db_session, interaction
):
    """Healing cannot push current_hp above max_hp."""
    sample_character.max_hp = 10
    sample_character.current_hp = 7
    db_session.commit()

    cb = get_callback(health_bot, "hp", "heal")
    await cb(interaction, amount="999")

    msg = interaction.response.send_message.call_args.args[0]
    assert "10/10" in msg


async def test_damage_to_zero_hp_shows_downed_not_death(
    health_bot, sample_character, db_session, interaction
):
    """Dropping to exactly 0 HP shows the HP message without the death string.

    Per 5e2024 rules:
    - 0 HP → incapacitated / making death saves (no instant death message)
    - HP ≤ -max_hp → massive damage / instant death (death message fires)

    Only the second case triggers HP_DEATH_MSG; reaching 0 is just HP: 0/max.
    """
    sample_character.max_hp = 8
    sample_character.current_hp = 8
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="8")

    msg = interaction.response.send_message.call_args.args[0]
    assert "0/8" in msg
    # No death message at exactly 0 HP — that requires current_hp <= -max_hp
    assert "died" not in msg.lower()


async def test_massive_damage_triggers_instant_death_message(
    health_bot, sample_character, db_session, interaction
):
    """Damage that drives HP to ≤ -max_hp triggers the instant-death message
    (5e2024 massive damage rule)."""
    sample_character.max_hp = 8
    sample_character.current_hp = 8
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    # 17 damage: 8 (max_hp) + 1 pushes current_hp to -9, which is ≤ -8
    await cb(interaction, amount="17")

    msg = interaction.response.send_message.call_args.args[0]
    assert "died" in msg.lower() or "massive" in msg.lower()


async def test_damage_without_hp_set_is_rejected(
    health_bot, sample_character, db_session, interaction
):
    """Applying damage before max HP is set (current_hp == -1) should be
    rejected with an ephemeral error."""
    # sample_character has default max_hp=-1 / current_hp=-1
    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_gm_can_damage_party_member_by_name(
    health_bot, sample_active_party, sample_character, db_session, interaction
):
    """The GM can apply damage to another party member by specifying their name."""
    sample_active_party.characters.append(sample_character)
    sample_character.max_hp = 20
    sample_character.current_hp = 20
    db_session.commit()

    cb = get_callback(health_bot, "hp", "damage")
    await cb(interaction, amount="5", partymember="Aldric")

    msg = interaction.response.send_message.call_args.args[0]
    assert "15/20" in msg
