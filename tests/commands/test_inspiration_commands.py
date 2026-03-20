"""Integration tests for /inspiration commands and Perkins crit auto-grant."""

import pytest
from sqlalchemy import insert

from models import Party, PartySettings, user_server_association
from enums.crit_rule import CritRule
from tests.commands.conftest import get_callback, make_bot
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def inspiration_bot(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.inspiration_commands.SessionLocal", new=session_factory)
    from commands.inspiration_commands import register_inspiration_commands

    register_inspiration_commands(bot)
    yield bot


@pytest.fixture
def attack_bot_patched(session_factory, mocker):
    bot = make_bot()
    mocker.patch("commands.attack_commands.SessionLocal", new=session_factory)
    from commands.attack_commands import register_attack_commands

    register_attack_commands(bot)
    yield bot


def _sent_message(interaction):
    return interaction.response.send_message.call_args.args[0]


# ---------------------------------------------------------------------------
# /inspiration grant — self
# ---------------------------------------------------------------------------


async def test_grant_sets_inspiration_true(
    inspiration_bot, sample_character, db_session, interaction
):
    """Granting inspiration to own character sets inspiration=True."""
    assert sample_character.inspiration is False

    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction)

    db_session.refresh(sample_character)
    assert sample_character.inspiration is True
    msg = _sent_message(interaction)
    assert "Inspiration" in msg


async def test_grant_when_already_has_inspiration_returns_error(
    inspiration_bot, sample_character, db_session, interaction
):
    """Granting inspiration when already held returns an ephemeral error."""
    sample_character.inspiration = True
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_grant_no_character_returns_error(
    inspiration_bot, sample_user, sample_server, interaction
):
    """Granting with no active character returns an error."""
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /inspiration remove — self
# ---------------------------------------------------------------------------


async def test_remove_clears_inspiration(
    inspiration_bot, sample_character, db_session, interaction
):
    """Removing inspiration from own character sets inspiration=False."""
    sample_character.inspiration = True
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "remove")
    await cb(interaction)

    db_session.refresh(sample_character)
    assert sample_character.inspiration is False
    msg = _sent_message(interaction)
    assert "no longer" in msg.lower()


async def test_remove_when_not_held_returns_error(
    inspiration_bot, sample_character, db_session, interaction
):
    """Removing inspiration when not held returns an ephemeral error."""
    cb = get_callback(inspiration_bot, "inspiration", "remove")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /inspiration status
# ---------------------------------------------------------------------------


async def test_status_reports_has_inspiration(
    inspiration_bot, sample_character, db_session, interaction
):
    """Status for a character with inspiration says they have it."""
    sample_character.inspiration = True
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction)

    msg = _sent_message(interaction)
    assert "has Inspiration" in msg


async def test_status_reports_no_inspiration(
    inspiration_bot, sample_character, db_session, interaction
):
    """Status for a character without inspiration says they don't."""
    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction)

    msg = _sent_message(interaction)
    assert "does not have Inspiration" in msg


# ---------------------------------------------------------------------------
# /inspiration grant — GM targeting another party member
# ---------------------------------------------------------------------------


async def test_gm_can_grant_to_party_member(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A GM can grant inspiration to another party member by name."""
    from models import Character, ClassLevel

    target = Character(
        name="Gandalf",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(ClassLevel(character_id=target.id, class_name="Wizard", level=1))
    sample_active_party.characters.append(target)
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(interaction, partymember="Gandalf")

    db_session.refresh(target)
    assert target.inspiration is True


async def test_non_gm_cannot_grant_to_party_member(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A non-GM gets an error when trying to target another party member."""
    from models import Character, ClassLevel, User

    other_user = User(discord_id="999")
    db_session.add(other_user)
    db_session.flush()
    other_char = Character(
        name="Legolas",
        user=other_user,
        server=sample_character.server,
        is_active=False,
    )
    db_session.add(other_char)
    db_session.flush()
    db_session.add(ClassLevel(character_id=other_char.id, class_name="Ranger", level=1))
    sample_active_party.characters.append(other_char)
    db_session.commit()

    # interaction user (id=111) is a GM of sample_active_party, so set up a
    # different interaction user who is NOT a GM
    non_gm_interaction = make_interaction(mocker, user_id=9999, guild_id=222)
    non_gm_user = User(discord_id="9999")
    db_session.add(non_gm_user)
    db_session.flush()
    from sqlalchemy import insert as sa_insert

    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=non_gm_user.id,
            server_id=sample_character.server_id,
            active_party_id=sample_active_party.id,
        )
    )
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(non_gm_interaction, partymember="Legolas")

    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )
    msg = non_gm_interaction.response.send_message.call_args.args[0]
    assert "GM" in msg


# ---------------------------------------------------------------------------
# Perkins crit auto-grants inspiration
# ---------------------------------------------------------------------------


async def test_perkins_crit_sets_inspiration_on_character(
    mocker,
    attack_bot_patched,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A nat-20 with Perkins rule active persists inspiration=True on character."""
    from models import Attack

    attack = Attack(
        character_id=sample_character.id,
        name="Shortsword",
        hit_modifier=5,
        damage_formula="1d6+3",
    )
    db_session.add(attack)

    party_settings = PartySettings(
        party_id=sample_active_party.id,
        crit_rule=CritRule.PERKINS,
    )
    db_session.add(party_settings)
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    mocker.patch("commands.attack_commands.random.randint", return_value=20)
    mocker.patch(
        "commands.attack_commands.roll_dice",
        return_value=([4], 3, 7),
    )

    cb = get_callback(attack_bot_patched, "attack", "roll")
    await cb(interaction, attack_name="Shortsword")

    db_session.refresh(sample_character)
    assert sample_character.inspiration is True

    msg = interaction.response.send_message.call_args.args[0]
    assert "Inspiration" in msg


async def test_non_perkins_crit_does_not_grant_inspiration(
    mocker,
    attack_bot_patched,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A nat-20 with DOUBLE_DICE rule does NOT set inspiration."""
    from models import Attack

    attack = Attack(
        character_id=sample_character.id,
        name="Longsword",
        hit_modifier=5,
        damage_formula="1d8+3",
    )
    db_session.add(attack)
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    mocker.patch("commands.attack_commands.random.randint", return_value=20)
    mocker.patch(
        "commands.attack_commands.roll_dice",
        return_value=([6, 6], 3, 15),
    )

    cb = get_callback(attack_bot_patched, "attack", "roll")
    await cb(interaction, attack_name="Longsword")

    db_session.refresh(sample_character)
    assert sample_character.inspiration is False


# ---------------------------------------------------------------------------
# Inspiration lifecycle: grant → remove → grant again
# ---------------------------------------------------------------------------


async def test_grant_then_spend_then_grant_again(
    inspiration_bot, sample_character, db_session, interaction
):
    """Grant → remove → grant again leaves inspiration=True (no stuck state)."""
    cb_grant = get_callback(inspiration_bot, "inspiration", "grant")
    cb_remove = get_callback(inspiration_bot, "inspiration", "remove")

    await cb_grant(interaction)
    db_session.refresh(sample_character)
    assert sample_character.inspiration is True

    await cb_remove(interaction)
    db_session.refresh(sample_character)
    assert sample_character.inspiration is False

    await cb_grant(interaction)
    db_session.refresh(sample_character)
    assert sample_character.inspiration is True


# ---------------------------------------------------------------------------
# Perkins crit — already inspired
# ---------------------------------------------------------------------------


async def test_perkins_crit_already_inspired_no_error(
    mocker,
    attack_bot_patched,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """Perkins crit fires when character already has inspiration — succeeds, stays True."""
    from models import Attack

    attack = Attack(
        character_id=sample_character.id,
        name="Dagger",
        hit_modifier=4,
        damage_formula="1d4+2",
    )
    db_session.add(attack)
    sample_character.inspiration = True
    party_settings = PartySettings(
        party_id=sample_active_party.id,
        crit_rule=CritRule.PERKINS,
    )
    db_session.add(party_settings)
    sample_active_party.characters.append(sample_character)
    db_session.commit()

    mocker.patch("commands.attack_commands.random.randint", return_value=20)
    mocker.patch(
        "commands.attack_commands.apply_crit_damage",
        return_value=mocker.Mock(
            rolls=[3], modifier=2, total=5, grants_inspiration=True
        ),
    )

    cb = get_callback(attack_bot_patched, "attack", "roll")
    await cb(interaction, attack_name="Dagger")

    db_session.refresh(sample_character)
    assert sample_character.inspiration is True  # stays True, no error


# ---------------------------------------------------------------------------
# GM can remove another party member's inspiration
# ---------------------------------------------------------------------------


async def test_gm_can_remove_from_party_member(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A GM can call /inspiration remove partymember=<name> to clear a target's inspiration."""
    from models import Character, ClassLevel

    target = Character(
        name="Merlin",
        user=sample_character.user,
        server=sample_character.server,
        is_active=False,
        inspiration=True,
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(ClassLevel(character_id=target.id, class_name="Wizard", level=1))
    sample_active_party.characters.append(target)
    db_session.commit()

    cb = get_callback(inspiration_bot, "inspiration", "remove")
    await cb(interaction, partymember="Merlin")

    db_session.refresh(target)
    assert target.inspiration is False


# ---------------------------------------------------------------------------
# Status check — no GM required
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Non-GM can manage inspiration for their own inactive character
# ---------------------------------------------------------------------------


async def test_non_gm_cannot_grant_inspiration_to_other_players_character(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A non-GM party member cannot grant inspiration to a character owned by another player."""
    from models import Character, ClassLevel, User
    from sqlalchemy import insert as sa_insert

    # Player A (non-GM): owns PlayerA_Char in the party
    player_a_user = User(discord_id="4441")
    db_session.add(player_a_user)
    db_session.flush()
    player_a_char = Character(
        name="Kairos",
        user=player_a_user,
        server=sample_character.server,
        is_active=True,
    )
    db_session.add(player_a_char)
    db_session.flush()
    db_session.add(
        ClassLevel(character_id=player_a_char.id, class_name="Bard", level=1)
    )

    # Player B (non-GM): owns PlayerB_Char in the party
    player_b_user = User(discord_id="4442")
    db_session.add(player_b_user)
    db_session.flush()
    player_b_char = Character(
        name="Zara",
        user=player_b_user,
        server=sample_character.server,
        is_active=True,
        inspiration=False,
    )
    db_session.add(player_b_char)
    db_session.flush()
    db_session.add(
        ClassLevel(character_id=player_b_char.id, class_name="Druid", level=1)
    )

    sample_active_party.characters.extend([player_a_char, player_b_char])
    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=player_a_user.id,
            server_id=sample_character.server_id,
            active_party_id=sample_active_party.id,
        )
    )
    db_session.commit()

    # Player A (non-GM) tries to grant inspiration to Player B's character — must be denied
    player_a_interaction = make_interaction(mocker, user_id=4441, guild_id=222)
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(player_a_interaction, partymember="Zara")

    assert (
        player_a_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is True
    )
    msg = player_a_interaction.response.send_message.call_args.args[0]
    assert "GM" in msg
    db_session.refresh(player_b_char)
    assert player_b_char.inspiration is False


async def test_non_gm_can_grant_inspiration_to_own_inactive_character(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A non-GM player can grant inspiration to their own inactive character by name."""
    from models import Character, ClassLevel, User
    from sqlalchemy import insert as sa_insert

    # Create a separate non-GM user with two characters: one active (Riven) and one inactive (Thorin)
    non_gm_user = User(discord_id="5555")
    db_session.add(non_gm_user)
    db_session.flush()

    active_char = Character(
        name="Riven",
        user=non_gm_user,
        server=sample_character.server,
        is_active=True,
    )
    inactive_char = Character(
        name="Thorin",
        user=non_gm_user,
        server=sample_character.server,
        is_active=False,
        inspiration=False,
    )
    db_session.add_all([active_char, inactive_char])
    db_session.flush()
    db_session.add(
        ClassLevel(character_id=active_char.id, class_name="Fighter", level=1)
    )
    db_session.add(
        ClassLevel(character_id=inactive_char.id, class_name="Paladin", level=1)
    )
    sample_active_party.characters.append(inactive_char)
    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=non_gm_user.id,
            server_id=sample_character.server_id,
            active_party_id=sample_active_party.id,
        )
    )
    db_session.commit()

    non_gm_interaction = make_interaction(mocker, user_id=5555, guild_id=222)
    cb = get_callback(inspiration_bot, "inspiration", "grant")
    await cb(non_gm_interaction, partymember="Thorin")

    db_session.refresh(inactive_char)
    assert inactive_char.inspiration is True
    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is not True
    )


async def test_non_gm_can_remove_inspiration_from_own_inactive_character(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """A non-GM player can remove inspiration from their own inactive character by name."""
    from models import Character, ClassLevel, User
    from sqlalchemy import insert as sa_insert

    non_gm_user = User(discord_id="6666")
    db_session.add(non_gm_user)
    db_session.flush()

    active_char = Character(
        name="Sera",
        user=non_gm_user,
        server=sample_character.server,
        is_active=True,
    )
    inactive_char = Character(
        name="Durgin",
        user=non_gm_user,
        server=sample_character.server,
        is_active=False,
        inspiration=True,
    )
    db_session.add_all([active_char, inactive_char])
    db_session.flush()
    db_session.add(ClassLevel(character_id=active_char.id, class_name="Rogue", level=1))
    db_session.add(
        ClassLevel(character_id=inactive_char.id, class_name="Cleric", level=1)
    )
    sample_active_party.characters.append(inactive_char)
    db_session.execute(
        sa_insert(user_server_association).values(
            user_id=non_gm_user.id,
            server_id=sample_character.server_id,
            active_party_id=sample_active_party.id,
        )
    )
    db_session.commit()

    non_gm_interaction = make_interaction(mocker, user_id=6666, guild_id=222)
    cb = get_callback(inspiration_bot, "inspiration", "remove")
    await cb(non_gm_interaction, partymember="Durgin")

    db_session.refresh(inactive_char)
    assert inactive_char.inspiration is False
    assert (
        non_gm_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is not True
    )


async def test_status_for_party_member_no_gm_required(
    mocker,
    inspiration_bot,
    sample_character,
    db_session,
    sample_active_party,
    interaction,
):
    """Any party member can check another member's inspiration status (no GM gate)."""
    from models import Character, ClassLevel, User
    from sqlalchemy import insert as sa_insert

    other_user = User(discord_id="7777")
    db_session.add(other_user)
    db_session.flush()
    target = Character(
        name="Elara",
        user=other_user,
        server=sample_character.server,
        is_active=True,
        inspiration=True,
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(ClassLevel(character_id=target.id, class_name="Cleric", level=1))
    sample_active_party.characters.append(target)
    db_session.commit()

    # Use the regular (non-GM) interaction user_id=111
    cb = get_callback(inspiration_bot, "inspiration", "status")
    await cb(interaction, partymember="Elara")

    msg = _sent_message(interaction)
    assert "Elara" in msg
    # Should contain status info, not a GM-only or not-found error
    assert "GM" not in msg
    assert "not found" not in msg.lower()
