"""Comprehensive tests for the ``/gmroll`` command.

Behaviour contract
------------------
* The rolling player receives an **ephemeral** message showing their full roll
  result (breakdown + total).  No other player can see the roll.
* Every GM of every party that the rolling player's active character belongs to
  receives a **DM** containing the character name, the notation, and the full
  result so they can react without revealing the outcome to the table.
* If the character belongs to multiple parties, all distinct GMs across all
  those parties receive the notification.
* A DM failure (``discord.Forbidden``, ``discord.HTTPException``) must not
  block the player's ephemeral response.
* Pure dice notation (e.g. ``1d20``) does not require an active character.
  Named tokens (skills, saves, initiative) do require one.
* If the active character is not in any party, the player still receives their
  ephemeral result — there are simply no GMs to notify.

Test organisation
-----------------
1.  Player response — ephemeral, contains result
2.  GM DM — sent, contains character name + notation + result
3.  Multiple GMs / multiple parties
4.  Pure-dice vs. character-required notations
5.  No-party / no-character edge cases
6.  DM failure resilience
7.  Advantage / disadvantage
8.  Validation errors
"""

import asyncio

import discord
import pytest
from sqlalchemy import insert

from models import Character, ClassLevel, Party, User, user_server_association
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_client_fetch(mocker, interaction, gm_mocks: dict) -> None:
    """Configure ``interaction.client.fetch_user`` to return per-GM mocks.

    ``gm_mocks`` maps integer discord user IDs to ``AsyncMock`` objects that
    represent the Discord user returned by ``fetch_user``.  Each mock exposes
    a ``send`` async method that tests can later assert on.

    Args:
        mocker: pytest-mock's ``mocker`` fixture.
        interaction: The mocked discord.Interaction.
        gm_mocks: ``{discord_user_id: AsyncMock_user}`` mapping.
    """

    async def _fetch_user(user_id: int):
        return gm_mocks[user_id]

    interaction.client.fetch_user = _fetch_user


def _make_gm_mock(mocker):
    """Return a fresh AsyncMock with a ``send`` attribute."""
    mock = mocker.AsyncMock()
    mock.send = mocker.AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gm_user(db_session, sample_server):
    """A second user (discord_id "555") who will act as GM."""
    user = User(discord_id="555")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def second_gm_user(db_session, sample_server):
    """A third user (discord_id "666") who acts as a second GM."""
    user = User(discord_id="666")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def party_with_gm(db_session, gm_user, sample_server, sample_character):
    """One party where gm_user is the GM and sample_character is a member."""
    party = Party(name="Shadow Guild", gms=[gm_user], server=sample_server)
    db_session.add(party)
    db_session.commit()
    party.characters.append(sample_character)
    db_session.commit()
    db_session.refresh(party)
    return party


@pytest.fixture
def party_with_two_gms(
    db_session, gm_user, second_gm_user, sample_server, sample_character
):
    """One party with two GMs (gm_user + second_gm_user), sample_character is a member."""
    party = Party(
        name="Twin Command",
        gms=[gm_user, second_gm_user],
        server=sample_server,
    )
    db_session.add(party)
    db_session.commit()
    party.characters.append(sample_character)
    db_session.commit()
    db_session.refresh(party)
    return party


@pytest.fixture
def second_party_with_gm(db_session, second_gm_user, sample_server, sample_character):
    """A second party where second_gm_user is GM and sample_character is also a member."""
    party = Party(name="Night Watch", gms=[second_gm_user], server=sample_server)
    db_session.add(party)
    db_session.commit()
    party.characters.append(sample_character)
    db_session.commit()
    db_session.refresh(party)
    return party


# ===========================================================================
# 1. Player response — always ephemeral
# ===========================================================================


async def test_gmroll_player_response_is_always_ephemeral(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """The player's response is always ephemeral so other users cannot see it."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=15)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_gmroll_no_public_message_sent(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """No non-ephemeral message is sent; the roll is invisible to other players."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    call = interaction.response.send_message.call_args
    assert call.kwargs.get("ephemeral") is True, (
        "send_message must be ephemeral — a non-ephemeral call would reveal the roll"
    )
    # followup.send (if used) must also be ephemeral or absent
    for followup_call in interaction.followup.send.call_args_list:
        assert followup_call.kwargs.get("ephemeral") is True, (
            "followup.send must be ephemeral when used"
        )


async def test_gmroll_player_response_contains_roll_total(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """The player's ephemeral message includes the roll total."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=17)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    msg = interaction.response.send_message.call_args.args[0]
    assert "17" in msg


async def test_gmroll_player_response_contains_notation(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """The player's ephemeral message identifies what was rolled."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    msg = interaction.response.send_message.call_args.args[0]
    assert "1d20" in msg.lower() or "20" in msg


async def test_gmroll_skill_player_response_contains_result(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """When rolling a skill check the player's ephemeral shows the computed total."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("utils.dnd_logic.random.randint", return_value=12)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    # perception: 12 (d20) + 1 (wisdom mod for wis=12) = 13
    assert "13" in msg or "perception" in msg.lower()


# ===========================================================================
# 2. GM DM — sent and contains correct context
# ===========================================================================


async def test_gmroll_sends_dm_to_gm(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """When the character is in a party, the GM receives a DM."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    mock_gm.send.assert_called_once()


async def test_gmroll_gm_dm_contains_character_name(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """The GM's DM identifies which character made the roll."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "aldric" in dm_content.lower()


async def test_gmroll_gm_dm_contains_notation(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """The GM's DM includes the notation so GMs know what was rolled."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "1d20" in dm_content.lower() or "20" in dm_content


async def test_gmroll_gm_dm_contains_roll_total(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """The GM's DM includes the numeric result of the roll."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=14)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "14" in dm_content


async def test_gmroll_skill_gm_dm_contains_computed_total(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """For a skill roll the GM DM shows the computed total (roll + modifier)."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    # d20 = 10; perception uses wisdom (12 → mod +1); total = 11
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="perception")

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "11" in dm_content


async def test_gmroll_gm_is_not_sent_the_players_ephemeral_response(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """The player's ephemeral response and the GM's DM are separate messages.

    The GM does not receive an ephemeral (they can't — DMs are always direct).
    This test confirms the two notification paths don't collapse into one.
    """
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Player got an ephemeral response
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    # GM also got a DM
    mock_gm.send.assert_called_once()


# ===========================================================================
# 3. Multiple GMs / multiple parties
# ===========================================================================


async def test_gmroll_single_party_two_gms_both_receive_dm(
    roll_bot, sample_character, party_with_two_gms, db_session, interaction, mocker
):
    """When a party has two GMs, both receive a separate DM."""
    mock_gm_1 = _make_gm_mock(mocker)
    mock_gm_2 = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm_1, 666: mock_gm_2})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    mock_gm_1.send.assert_called_once()
    mock_gm_2.send.assert_called_once()


async def test_gmroll_character_in_two_parties_all_gms_notified(
    roll_bot,
    sample_character,
    party_with_gm,
    second_party_with_gm,
    db_session,
    interaction,
    mocker,
):
    """When the active character belongs to two parties, the GM of each party
    receives a DM.

    ``party_with_gm`` → GM user 555
    ``second_party_with_gm`` → GM user 666
    Both should receive DMs.
    """
    mock_gm_1 = _make_gm_mock(mocker)
    mock_gm_2 = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm_1, 666: mock_gm_2})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    mock_gm_1.send.assert_called_once()
    mock_gm_2.send.assert_called_once()


async def test_gmroll_character_in_two_parties_same_gm_both_dms_sent(
    roll_bot,
    sample_character,
    gm_user,
    db_session,
    sample_server,
    interaction,
    mocker,
):
    """When the same user is GM of both parties the active character belongs to,
    they receive a DM for each party — one per party, so they have full context
    for both.
    """
    # Build two parties, both with gm_user as GM, both including sample_character
    party_a = Party(name="Alpha Squad", gms=[gm_user], server=sample_server)
    party_b = Party(name="Beta Squad", gms=[gm_user], server=sample_server)
    db_session.add_all([party_a, party_b])
    db_session.commit()
    party_a.characters.append(sample_character)
    party_b.characters.append(sample_character)
    db_session.commit()

    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # One DM per party membership (two parties → two DMs to the same user)
    assert mock_gm.send.call_count == 2


async def test_gmroll_three_parties_one_character_all_gms_notified(
    roll_bot,
    sample_character,
    gm_user,
    second_gm_user,
    db_session,
    sample_server,
    interaction,
    mocker,
):
    """Three parties: party A (GM 555), party B (GM 666), party C (GMs 555 + 666).
    All three party-GM pairings receive a DM (555 × 2, 666 × 2).
    """
    third_party = Party(
        name="Triple Threat",
        gms=[gm_user, second_gm_user],
        server=sample_server,
    )
    party_a = Party(name="Party A", gms=[gm_user], server=sample_server)
    party_b = Party(name="Party B", gms=[second_gm_user], server=sample_server)
    db_session.add_all([third_party, party_a, party_b])
    db_session.commit()

    for party in [third_party, party_a, party_b]:
        party.characters.append(sample_character)
    db_session.commit()

    mock_gm_1 = _make_gm_mock(mocker)
    mock_gm_2 = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm_1, 666: mock_gm_2})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # GM 555 is in triple_threat + party_a = 2 DMs
    # GM 666 is in triple_threat + party_b = 2 DMs
    assert mock_gm_1.send.call_count == 2
    assert mock_gm_2.send.call_count == 2


# ===========================================================================
# 4. Pure dice vs. character-required notations
# ===========================================================================


async def test_gmroll_pure_dice_succeeds_without_active_character(
    roll_bot, sample_server, db_session, interaction, mocker
):
    """Pure dice notation (``1d20``, ``2d6+3``) does not require an active
    character — the roll is resolved without a DB lookup.
    The player gets an ephemeral result; there are no parties to DM.
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=8)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="2d6+3")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    # 2d6 (both 8 capped by faces, but randint returns 6 at max): just check result sent
    assert msg  # any non-empty response


async def test_gmroll_skill_notation_requires_active_character(
    roll_bot, sample_server, db_session, interaction, mocker
):
    """``/gmroll perception`` with no active character must return an ephemeral
    CHARACTER_NOT_FOUND error, not crash.
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="perception")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_gmroll_save_notation_requires_active_character(
    roll_bot, sample_server, db_session, interaction, mocker
):
    """``/gmroll strength save`` requires an active character."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="strength save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


async def test_gmroll_initiative_notation_requires_active_character(
    roll_bot, sample_server, db_session, interaction, mocker
):
    """``/gmroll initiative`` requires an active character."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="initiative")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "character" in msg.lower()


# ===========================================================================
# 5. No-party / no-character edge cases
# ===========================================================================


async def test_gmroll_character_in_no_parties_no_dm_sent(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """A character not belonging to any party still gets an ephemeral result.
    No DMs are sent (there are no GMs to notify).
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    interaction.client.fetch_user.assert_not_called()


async def test_gmroll_pure_dice_no_character_no_party_no_dm(
    roll_bot, sample_server, db_session, interaction, mocker
):
    """Pure dice roll with no user row or character row at all.
    Player gets ephemeral result; no DMs attempted.
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=5)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    interaction.client.fetch_user.assert_not_called()


async def test_gmroll_character_in_party_with_no_gms_no_dm_sent(
    roll_bot, sample_character, db_session, sample_server, interaction, mocker
):
    """If a party somehow has no GMs (edge case), no DM is attempted and the
    player still receives their result.
    """
    # Create a party with no GMs via direct DB manipulation
    from models import Party as PartyModel
    from models.base import Base

    party = PartyModel(name="Leaderless", server=sample_server)
    db_session.add(party)
    db_session.commit()
    party.characters.append(sample_character)
    db_session.commit()

    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    interaction.client.fetch_user.assert_not_called()


# ===========================================================================
# 6. DM failure resilience
# ===========================================================================


async def test_gmroll_dm_forbidden_does_not_block_player_response(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """If the bot cannot DM the GM (e.g. they have DMs disabled), the player
    still receives their ephemeral response.
    """
    mock_gm = mocker.AsyncMock()
    mock_gm.send = mocker.AsyncMock(
        side_effect=discord.Forbidden(
            mocker.MagicMock(), "Cannot send messages to this user"
        )
    )
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Player still gets their ephemeral result
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert msg  # non-empty


async def test_gmroll_dm_http_exception_does_not_block_player_response(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """``discord.HTTPException`` during DM delivery is silently absorbed."""
    mock_gm = mocker.AsyncMock()
    mock_gm.send = mocker.AsyncMock(
        side_effect=discord.HTTPException(mocker.MagicMock(), "Internal server error")
    )
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_gmroll_first_gm_dm_fails_second_gm_still_notified(
    roll_bot, sample_character, party_with_two_gms, db_session, interaction, mocker
):
    """When a party has two GMs and the first DM fails, the second GM is still
    notified — a single failure must not abort the notification loop.
    """
    mock_gm_1 = mocker.AsyncMock()
    mock_gm_1.send = mocker.AsyncMock(
        side_effect=discord.Forbidden(mocker.MagicMock(), "DMs disabled")
    )
    mock_gm_2 = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm_1, 666: mock_gm_2})
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Player response unaffected
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    # Second GM received their DM despite first failing
    mock_gm_2.send.assert_called_once()


async def test_gmroll_network_error_in_fetch_user_does_not_abort_remaining_gms(
    roll_bot, sample_character, party_with_two_gms, db_session, interaction, mocker
):
    """A non-discord exception (e.g. asyncio.TimeoutError) from fetch_user for
    the first GM must not prevent the second GM from receiving their DM.

    Currently fails because only discord.Forbidden / discord.HTTPException are
    caught in _notify_gmroll_gms, so asyncio.TimeoutError propagates out of the
    loop and aborts all remaining notifications.
    """

    async def _fetch_user(user_id: int):
        if user_id == 555:
            raise asyncio.TimeoutError()
        mock = _make_gm_mock(mocker)
        return mock

    interaction.client.fetch_user = _fetch_user
    mock_gm_2 = _make_gm_mock(mocker)

    async def _fetch_user_tracking(user_id: int):
        if user_id == 555:
            raise asyncio.TimeoutError()
        return mock_gm_2

    interaction.client.fetch_user = _fetch_user_tracking
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Second GM still receives their DM
    mock_gm_2.send.assert_called_once()


async def test_gmroll_network_error_does_not_corrupt_player_ephemeral(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """A network-level exception during DM delivery must not cause a SERVER_ERROR
    message to replace the player's roll result.  The player should only ever see
    one ephemeral message — their roll result.
    """

    async def _fetch_raises(_user_id: int):
        raise asyncio.TimeoutError()

    interaction.client.fetch_user = _fetch_raises
    mocker.patch("dice_roller.random.randint", return_value=10)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Only one send_message call — the roll result, not a SERVER_ERROR
    assert interaction.response.send_message.call_count == 1
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "10" in msg


async def test_gmroll_roller_who_is_gm_receives_dm(
    roll_bot,
    sample_character,
    sample_server,
    sample_user,
    db_session,
    interaction,
    mocker,
):
    """When the rolling user is also a GM of the party their character belongs to,
    they receive a DM just like any other GM.
    """
    # Make sample_user (the roller, discord_id="111") the GM of a party
    # that contains sample_character
    from models import Party

    party = Party(name="Self-GM Party", gms=[sample_user], server=sample_server)
    db_session.add(party)
    db_session.commit()
    party.characters.append(sample_character)
    db_session.commit()

    mock_self = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {111: mock_self})
    mocker.patch("dice_roller.random.randint", return_value=12)

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20")

    # Player gets ephemeral
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    # Roller (who is also GM) receives the GM DM
    mock_self.send.assert_called_once()


# ===========================================================================
# 7. Advantage / disadvantage
# ===========================================================================


async def test_gmroll_advantage_takes_higher_of_two_rolls(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """With advantage the higher of two d20 rolls is used."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    # First roll = 5, second roll = 14 → advantage takes 14
    mocker.patch("dice_roller.random.randint", side_effect=[5, 14])

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20", advantage="advantage")

    msg = interaction.response.send_message.call_args.args[0]
    assert "14" in msg

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "14" in dm_content


async def test_gmroll_disadvantage_takes_lower_of_two_rolls(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """With disadvantage the lower of two d20 rolls is used."""
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    # First roll = 18, second roll = 3 → disadvantage takes 3
    mocker.patch("dice_roller.random.randint", side_effect=[18, 3])

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20", advantage="disadvantage")

    msg = interaction.response.send_message.call_args.args[0]
    assert "3" in msg

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    assert "3" in dm_content


async def test_gmroll_advantage_gm_dm_shows_both_rolls(
    roll_bot, sample_character, party_with_gm, db_session, interaction, mocker
):
    """With advantage the GM DM should show both dice values so the GM can see
    the full roll (not just the selected value).
    """
    mock_gm = _make_gm_mock(mocker)
    _setup_client_fetch(mocker, interaction, {555: mock_gm})
    mocker.patch("dice_roller.random.randint", side_effect=[7, 19])

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1d20", advantage="advantage")

    args, kwargs = mock_gm.send.call_args
    dm_content = _extract_dm_text(args, kwargs)
    # Both rolls (7 and 19) should appear in the GM's DM
    assert "19" in dm_content
    assert "7" in dm_content


# ===========================================================================
# 8. Validation errors
# ===========================================================================


async def test_gmroll_invalid_dice_notation_returns_ephemeral_error(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """Unknown named notation returns an ephemeral error without crashing and
    without DMing any GM.

    ``perform_roll`` catches ``ValueError`` internally and returns a formatted
    error string (``ROLL_ERROR_CHAR``).  The gmroll command must send this
    result ephemerally — the player sees it, no one else does.
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="notaroll")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    # perform_roll returns a ROLL_ERROR_CHAR string containing "❌" for unknown notation
    assert "❌" in msg or "error" in msg.lower()
    interaction.client.fetch_user.assert_not_called()


async def test_gmroll_zero_dice_returns_ephemeral_response(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """``0d6`` evaluates to a total of 0 and is sent ephemerally.

    ``0d6`` is not rejected by the dice roller (it produces total 0); the
    important thing is that the response is private to the player.
    """
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="0d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_gmroll_over_dice_limit_returns_ephemeral_error(
    roll_bot, sample_character, db_session, interaction, mocker
):
    """``1001d6`` exceeds the 1000-dice cap and must return an ephemeral error."""
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(roll_bot, "gmroll")
    await cb(interaction, notation="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _extract_dm_text(args: tuple, kwargs: dict) -> str:
    """Extract displayable text from a ``send()`` call's args/kwargs.

    Handles both plain-string calls (``send("text")``) and embed calls
    (``send(embed=embed)``).  Returns everything concatenated so callers can
    do simple substring checks.
    """
    parts: list[str] = []

    # Positional string argument
    for arg in args:
        if isinstance(arg, str):
            parts.append(arg)

    # Keyword content=
    if "content" in kwargs and isinstance(kwargs["content"], str):
        parts.append(kwargs["content"])

    # Embed fields
    embed = kwargs.get("embed")
    if embed is not None:
        if hasattr(embed, "title") and embed.title:
            parts.append(str(embed.title))
        if hasattr(embed, "description") and embed.description:
            parts.append(str(embed.description))
        if hasattr(embed, "footer") and embed.footer and embed.footer.text:
            parts.append(str(embed.footer.text))
        if hasattr(embed, "fields"):
            for field in embed.fields:
                parts.append(str(field.name))
                parts.append(str(field.value))

    return " ".join(parts)
