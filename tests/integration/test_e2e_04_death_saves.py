"""
E2E integration tests — Sections 19–20: Temp HP Edge Cases and Death Save System.

Depends on state from prior test files (Aldric in The Fellowship with HP set).
When run in isolation, a session-scoped autouse fixture seeds the required
prerequisite state so these tests are also runnable standalone.

Run the full suite together:
    pytest tests/integration/ -v
"""

import pytest

from sqlalchemy import insert

from models import (
    Base,
    Character,
    ClassLevel,
    Party,
    PartySettings,
    Server,
    User,
    user_server_association,
)
from enums.death_save_nat20_mode import DeathSaveNat20Mode
from tests.integration.conftest import (
    GUILD_ID,
    PLAYER_A_ID,
    PLAYER_B_ID,
    get_callback,
    make_bot,
    make_e2e_interaction,
    patch_session_locals,
)


# ---------------------------------------------------------------------------
# Constants used throughout this file
# ---------------------------------------------------------------------------

ALDRIC_NAME = "Aldric"
BRAMBLE_NAME = "Bramble"
PARTY_NAME = "The Fellowship"
ALDRIC_MAX_HP = 30
BRAMBLE_MAX_HP = 20


# ---------------------------------------------------------------------------
# Session-scoped prerequisite guard / seeder
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def ensure_prerequisites(int_session_factory):
    """Verify that Aldric exists with HP set; seed the DB if running in isolation.

    When the full integration suite is executed in order, earlier test files
    create all required state.  When this file runs alone, this fixture seeds
    the minimum required records so the tests still pass.
    """
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name=ALDRIC_NAME).first()
        if aldric is not None:
            # Prerequisites from earlier test files are in place — nothing to do.
            return

        # --- seed prerequisite state ---

        # Users
        player_a = session.query(User).filter_by(discord_id=PLAYER_A_ID).first()
        if player_a is None:
            player_a = User(discord_id=PLAYER_A_ID)
            session.add(player_a)
            session.flush()

        player_b = session.query(User).filter_by(discord_id=PLAYER_B_ID).first()
        if player_b is None:
            player_b = User(discord_id=PLAYER_B_ID)
            session.add(player_b)
            session.flush()

        # Server
        server = session.query(Server).filter_by(discord_id=GUILD_ID).first()
        if server is None:
            server = Server(discord_id=GUILD_ID, name="Integration Test Server")
            session.add(server)
            session.flush()

        # Party
        party = session.query(Party).filter_by(name=PARTY_NAME, server_id=server.id).first()
        if party is None:
            party = Party(name=PARTY_NAME, gms=[player_a], server=server)
            session.add(party)
            session.flush()

        # Aldric (player_a's active character)
        aldric = Character(
            name=ALDRIC_NAME,
            user=player_a,
            server=server,
            is_active=True,
            max_hp=ALDRIC_MAX_HP,
            current_hp=ALDRIC_MAX_HP,
            temp_hp=0,
            death_save_successes=0,
            death_save_failures=0,
        )
        session.add(aldric)
        session.flush()
        session.add(ClassLevel(character_id=aldric.id, class_name="Fighter", level=5))
        party.characters.append(aldric)
        session.flush()

        # Bramble (player_b's active character)
        bramble = session.query(Character).filter_by(name=BRAMBLE_NAME).first()
        if bramble is None:
            bramble = Character(
                name=BRAMBLE_NAME,
                user=player_b,
                server=server,
                is_active=True,
                max_hp=BRAMBLE_MAX_HP,
                current_hp=BRAMBLE_MAX_HP,
                temp_hp=0,
                death_save_successes=0,
                death_save_failures=0,
            )
            session.add(bramble)
            session.flush()
            session.add(ClassLevel(character_id=bramble.id, class_name="Rogue", level=4))
            party.characters.append(bramble)

        # Link player_a to server with party as active
        existing_assoc = session.execute(
            user_server_association.select().where(
                user_server_association.c.user_id == player_a.id,
                user_server_association.c.server_id == server.id,
            )
        ).fetchone()
        if existing_assoc is None:
            session.execute(
                insert(user_server_association).values(
                    user_id=player_a.id,
                    server_id=server.id,
                    active_party_id=party.id,
                )
            )

        # Link player_b to server with party as active
        existing_assoc_b = session.execute(
            user_server_association.select().where(
                user_server_association.c.user_id == player_b.id,
                user_server_association.c.server_id == server.id,
            )
        ).fetchone()
        if existing_assoc_b is None:
            session.execute(
                insert(user_server_association).values(
                    user_id=player_b.id,
                    server_id=server.id,
                    active_party_id=party.id,
                )
            )

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _get_sent_message(interaction) -> str:
    """Return the first positional argument of the last send_message call."""
    return interaction.response.send_message.call_args.args[0]


def _reset_aldric_to_full_hp(int_session_factory) -> None:
    """Reset Aldric to full HP and clear death save counters in the DB."""
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name=ALDRIC_NAME).first()
        aldric.current_hp = aldric.max_hp
        aldric.temp_hp = 0
        aldric.death_save_successes = 0
        aldric.death_save_failures = 0
        session.commit()
    finally:
        session.close()


def _reset_aldric_to_zero_hp(int_session_factory) -> None:
    """Set Aldric to 0 HP and clear death save counters (enter dying state)."""
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name=ALDRIC_NAME).first()
        aldric.current_hp = 0
        aldric.temp_hp = 0
        aldric.death_save_successes = 0
        aldric.death_save_failures = 0
        session.commit()
    finally:
        session.close()


def _get_aldric(int_session_factory) -> Character:
    """Load a fresh Aldric instance from the DB and return it (session closed)."""
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name=ALDRIC_NAME).first()
        # Detach from session so attributes are accessible after close.
        session.expunge(aldric)
        return aldric
    finally:
        session.close()


def _get_bramble(int_session_factory) -> Character:
    """Load a fresh Bramble instance from the DB and return it (session closed)."""
    session = int_session_factory()
    try:
        bramble = session.query(Character).filter_by(name=BRAMBLE_NAME).first()
        session.expunge(bramble)
        return bramble
    finally:
        session.close()


def _build_bots(mocker, int_session_factory):
    """Register all required command bots for this test file.

    Returns a tuple of (health_bot, roll_bot, party_bot).
    """
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.health_commands",
        "commands.roll_commands",
        "commands.party_commands",
    )

    health_bot = make_bot()
    from commands.health_commands import register_health_commands
    register_health_commands(health_bot)

    roll_bot = make_bot()
    from commands.roll_commands import register_roll_commands
    register_roll_commands(roll_bot)

    party_bot = make_bot()
    from commands.party_commands import register_party_commands
    register_party_commands(party_bot)

    return health_bot, roll_bot, party_bot


# ===========================================================================
# Section 19: Temp HP Edge Cases
# ===========================================================================


@pytest.mark.asyncio
async def test_19_01_temp_hp_set(int_session_factory, mocker) -> None:
    """19.1: /hp temp amount:5 sets Aldric's temp_hp to 5."""
    _reset_aldric_to_full_hp(int_session_factory)

    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "temp")
    await callback(interaction, amount=5)

    aldric = _get_aldric(int_session_factory)
    assert aldric.temp_hp == 5, (
        f"Expected temp_hp=5 after /hp temp amount:5, got {aldric.temp_hp}"
    )
    message = _get_sent_message(interaction)
    assert "5" in message


@pytest.mark.asyncio
async def test_19_02_temp_hp_not_replaced_by_lower_value(
    int_session_factory, mocker
) -> None:
    """19.2: /hp temp amount:3 — lower value is ignored; temp_hp stays at 5 (5e rule)."""
    # Precondition: Aldric has temp_hp=5 from test_19_01.
    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "temp")
    await callback(interaction, amount=3)

    aldric = _get_aldric(int_session_factory)
    assert aldric.temp_hp == 5, (
        f"Expected temp_hp to remain 5 (higher wins), got {aldric.temp_hp}"
    )


@pytest.mark.asyncio
async def test_19_03_temp_hp_replaced_by_higher_value(
    int_session_factory, mocker
) -> None:
    """19.3: /hp temp amount:10 — higher value replaces existing 5; temp_hp=10."""
    # Precondition: Aldric has temp_hp=5 from test_19_01.
    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "temp")
    await callback(interaction, amount=10)

    aldric = _get_aldric(int_session_factory)
    assert aldric.temp_hp == 10, (
        f"Expected temp_hp=10 after /hp temp amount:10, got {aldric.temp_hp}"
    )


@pytest.mark.asyncio
async def test_19_04_party_temp_higher_kept_lower_applied(
    int_session_factory, mocker
) -> None:
    """19.4: /hp party_temp amount:5 — Aldric keeps 10 (10>5); Bramble gains 5 (0<5)."""
    # Precondition: Aldric has temp_hp=10 from test_19_03; Bramble has temp_hp=0.
    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "party_temp")
    await callback(interaction, amount=5)

    aldric = _get_aldric(int_session_factory)
    bramble = _get_bramble(int_session_factory)

    assert aldric.temp_hp == 10, (
        f"Aldric already had 10 temp HP — should keep it (10>5), got {aldric.temp_hp}"
    )
    assert bramble.temp_hp == 5, (
        f"Bramble had 0 temp HP — should gain 5, got {bramble.temp_hp}"
    )

    message = _get_sent_message(interaction)
    # Response should list party members
    assert BRAMBLE_NAME in message or ALDRIC_NAME in message


# ===========================================================================
# Section 20: Death Save System — Standard Path
# ===========================================================================


@pytest.mark.asyncio
async def test_20_01_damage_to_zero_shows_downed(
    int_session_factory, mocker
) -> None:
    """20.1: /hp damage amount:999 — current_hp=0; response mentions downed/dying."""
    _reset_aldric_to_full_hp(int_session_factory)

    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "damage")
    await callback(interaction, amount="999")

    aldric = _get_aldric(int_session_factory)
    assert aldric.current_hp == 0, (
        f"HP should be clamped to 0 after massive damage, got {aldric.current_hp}"
    )

    message = _get_sent_message(interaction)
    message_lower = message.lower()
    assert (
        "downed" in message_lower
        or "dying" in message_lower
        or "death saving" in message_lower
        or "died" in message_lower
        or "dead" in message_lower
        or "slain" in message_lower
    ), f"Expected death/downed message, got: {message!r}"


@pytest.mark.asyncio
async def test_20_02_hp_status_shows_zero(int_session_factory, mocker) -> None:
    """20.2: /hp status — response shows 0/{max_hp} HP for the dying character."""
    # Precondition: Aldric is at 0 HP from test_20_01.
    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "status")
    await callback(interaction)

    message = _get_sent_message(interaction)
    # The status message should contain "0" and the max HP value.
    assert "0" in message
    assert str(ALDRIC_MAX_HP) in message


@pytest.mark.asyncio
async def test_20_03_first_death_save_success(int_session_factory, mocker) -> None:
    """20.3: /roll notation:death save — mocked roll 15 (success); successes becomes 1."""
    # Precondition: Aldric is at 0 HP, counters at 0.
    health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 15))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    assert aldric.death_save_successes == 1, (
        f"Expected 1 success after roll of 15, got {aldric.death_save_successes}"
    )
    assert aldric.death_save_failures == 0

    message = _get_sent_message(interaction)
    assert "Success" in message or "success" in message


@pytest.mark.asyncio
async def test_20_04_three_successes_stabilize(int_session_factory, mocker) -> None:
    """20.4: Two more successes (mocked=15) stabilize Aldric; counters reset; HP stays 0."""
    # Precondition: Aldric at 0 HP, 1 success from test_20_03.
    health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 15))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")

    # Second success
    await callback(interaction, notation="death save")
    # Third success — triggers stabilize
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    assert aldric.death_save_successes == 0, (
        f"Counters should reset after stabilizing, got successes={aldric.death_save_successes}"
    )
    assert aldric.death_save_failures == 0, (
        f"Counters should reset after stabilizing, got failures={aldric.death_save_failures}"
    )
    assert aldric.current_hp == 0, (
        f"Stabilized character stays at 0 HP; got {aldric.current_hp}"
    )

    final_message = _get_sent_message(interaction)
    assert "stabilized" in final_message.lower(), (
        f"Expected stabilize message on 3rd success, got: {final_message!r}"
    )


@pytest.mark.asyncio
async def test_20_05_damage_while_dying_adds_failure(
    int_session_factory, mocker
) -> None:
    """20.5: /hp damage amount:1 while at 0 HP — adds 1 death save failure."""
    # Bring Aldric back to 0 HP with fresh counters.
    _reset_aldric_to_zero_hp(int_session_factory)

    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "damage")
    await callback(interaction, amount="1")

    aldric = _get_aldric(int_session_factory)
    assert aldric.death_save_failures == 1, (
        f"Expected 1 failure after damage while dying, got {aldric.death_save_failures}"
    )
    assert aldric.current_hp == 0


@pytest.mark.asyncio
async def test_20_06_three_failures_slain(int_session_factory, mocker) -> None:
    """20.6: Two more failed saves (mocked=5) bring total failures to 3 — slain; counters reset."""
    # Precondition: Aldric at 0 HP with 1 failure from test_20_05.
    health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 5))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")

    # Second failure
    await callback(interaction, notation="death save")
    # Third failure — triggers slain
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    assert aldric.death_save_failures == 0, (
        f"Counters should reset after being slain, got failures={aldric.death_save_failures}"
    )
    assert aldric.death_save_successes == 0

    final_message = _get_sent_message(interaction)
    assert "slain" in final_message.lower(), (
        f"Expected slain message on 3rd failure, got: {final_message!r}"
    )


@pytest.mark.asyncio
async def test_20_07_heal_from_dying_resets_saves_and_restores_hp(
    int_session_factory, mocker
) -> None:
    """20.7: Bring Aldric to 0 HP then /hp heal amount:5 — HP=5; saves cleared."""
    _reset_aldric_to_zero_hp(int_session_factory)

    # Dirty the counters to verify they get reset.
    session = int_session_factory()
    try:
        aldric = session.query(Character).filter_by(name=ALDRIC_NAME).first()
        aldric.death_save_successes = 1
        aldric.death_save_failures = 1
        session.commit()
    finally:
        session.close()

    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "heal")
    await callback(interaction, amount="5")

    aldric = _get_aldric(int_session_factory)
    assert aldric.current_hp == 5, (
        f"Expected HP=5 after healing 5 from 0, got {aldric.current_hp}"
    )
    assert aldric.death_save_successes == 0, (
        f"Saves should reset on healing from dying, got successes={aldric.death_save_successes}"
    )
    assert aldric.death_save_failures == 0, (
        f"Saves should reset on healing from dying, got failures={aldric.death_save_failures}"
    )

    message = _get_sent_message(interaction)
    assert "reset" in message.lower(), (
        f"Expected save-reset mention in heal message, got: {message!r}"
    )


# ===========================================================================
# Section 20a: Death Save — Natural 1
# ===========================================================================


@pytest.mark.asyncio
async def test_20a_01_setup_zero_hp_for_nat1_section(
    int_session_factory, mocker
) -> None:
    """20a setup: Reset Aldric to 0 HP with cleared counters for the nat-1 section."""
    _reset_aldric_to_zero_hp(int_session_factory)

    aldric = _get_aldric(int_session_factory)
    assert aldric.current_hp == 0
    assert aldric.death_save_failures == 0
    assert aldric.death_save_successes == 0


@pytest.mark.asyncio
async def test_20a_02_nat_1_counts_double(int_session_factory, mocker) -> None:
    """20a.2: Natural 1 on a death save counts as 2 failures at once; failures=2."""
    # Precondition: Aldric at 0 HP, counters clean (from test_20a_01).
    _health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 1))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    assert aldric.death_save_failures == 2, (
        f"Nat 1 should add 2 failures, got {aldric.death_save_failures}"
    )

    message = _get_sent_message(interaction)
    assert "Natural 1" in message or "nat 1" in message.lower() or "1" in message


@pytest.mark.asyncio
async def test_20a_03_second_nat_1_exceeds_three_failures_slain(
    int_session_factory, mocker
) -> None:
    """20a.3: Another nat 1 with existing 2 failures (total ≥ 3) — character slain; counters reset."""
    # Precondition: Aldric at 0 HP, failures=2 from test_20a_02.
    _health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 1))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    # Counters must be reset after death.
    assert aldric.death_save_failures == 0, (
        f"Failures should reset after being slain, got {aldric.death_save_failures}"
    )

    message = _get_sent_message(interaction)
    assert "slain" in message.lower(), (
        f"Expected slain message when failures exceed 3, got: {message!r}"
    )


# ===========================================================================
# Section 20b: Death Save — Nat 20 Mode: regain_hp
# ===========================================================================


@pytest.mark.asyncio
async def test_20b_01_set_party_death_save_nat20_to_regain_hp(
    int_session_factory, mocker
) -> None:
    """20b.1: Set The Fellowship's death_save_nat20 mode to regain_hp via /party settings."""
    _health_bot, _roll_bot, party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(party_bot, "party", "settings", "death_save_nat20")
    await callback(interaction, party_name=PARTY_NAME, mode="regain_hp")

    # Verify the setting was persisted.
    session = int_session_factory()
    try:
        server = session.query(Server).filter_by(discord_id=GUILD_ID).first()
        party = session.query(Party).filter_by(
            name=PARTY_NAME, server_id=server.id
        ).first()
        party_settings = session.query(PartySettings).filter_by(
            party_id=party.id
        ).first()
        assert party_settings is not None, "PartySettings should be created."
        assert party_settings.death_save_nat20_mode == DeathSaveNat20Mode.REGAIN_HP, (
            f"Expected REGAIN_HP mode, got {party_settings.death_save_nat20_mode}"
        )
    finally:
        session.close()

    message = _get_sent_message(interaction)
    assert message is not None


@pytest.mark.asyncio
async def test_20b_02_setup_aldric_at_zero_hp_for_nat20_section(
    int_session_factory, mocker
) -> None:
    """20b setup: Bring Aldric to 0 HP with clean counters for the nat-20 section."""
    _reset_aldric_to_zero_hp(int_session_factory)

    aldric = _get_aldric(int_session_factory)
    assert aldric.current_hp == 0
    assert aldric.death_save_successes == 0
    assert aldric.death_save_failures == 0


@pytest.mark.asyncio
async def test_20b_03_nat_20_regains_hp(int_session_factory, mocker) -> None:
    """20b.3: Natural 20 in regain_hp mode — current_hp set to 1; counters reset."""
    # Precondition: Aldric at 0 HP, REGAIN_HP mode set (from tests 20b_01 and 20b_02).
    _health_bot, roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    mocker.patch("commands.roll_commands.roll_dice", return_value=([], 0, 20))

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(roll_bot, "roll")
    await callback(interaction, notation="death save")

    aldric = _get_aldric(int_session_factory)
    assert aldric.current_hp == 1, (
        f"Natural 20 in regain_hp mode should set HP to 1, got {aldric.current_hp}"
    )
    assert aldric.death_save_successes == 0, (
        f"Counters should reset after nat-20 heal, got successes={aldric.death_save_successes}"
    )
    assert aldric.death_save_failures == 0, (
        f"Counters should reset after nat-20 heal, got failures={aldric.death_save_failures}"
    )

    message = _get_sent_message(interaction)
    assert "Natural 20" in message or "natural 20" in message.lower(), (
        f"Expected Natural 20 message, got: {message!r}"
    )
    assert "1 hp" in message.lower() or "regain" in message.lower(), (
        f"Expected HP-regain mention in message, got: {message!r}"
    )


@pytest.mark.asyncio
async def test_20b_04_status_after_nat20_shows_one_hp(
    int_session_factory, mocker
) -> None:
    """20b.4: /hp status — response shows 1/{max_hp} HP after nat-20 heal."""
    # Precondition: Aldric is at 1 HP from test_20b_03.
    health_bot, _roll_bot, _party_bot = _build_bots(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    callback = get_callback(health_bot, "hp", "status")
    await callback(interaction)

    message = _get_sent_message(interaction)
    assert "1" in message, f"Expected HP=1 in status message, got: {message!r}"
    assert str(ALDRIC_MAX_HP) in message, (
        f"Expected max HP ({ALDRIC_MAX_HP}) in status message, got: {message!r}"
    )
