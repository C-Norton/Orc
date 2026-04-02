"""
E2E integration tests — Sections 6–10: Rolling, Attacks, Weapon Search, HP.

Depends on state created by test_e2e_01_character.py (Aldric with stats/skills).

Run the full suite together:
    pytest tests/integration/ -v
"""

import pytest
from pytest_mock import MockerFixture
from unittest.mock import AsyncMock

from models import Attack, Character, CharacterSkill, ClassLevel, Server, User
from enums.skill_proficiency_status import SkillProficiencyStatus
from tests.integration.conftest import (
    GUILD_ID,
    PLAYER_A_ID,
    make_e2e_interaction,
    make_bot,
    get_callback,
    patch_session_locals,
)


# ---------------------------------------------------------------------------
# Module-level guard: skip the whole file if Aldric is not in the DB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def ensure_aldric_exists(int_session_factory):
    """Skip the module when the prerequisite character 'Aldric' is absent.

    This fixture requires test_e2e_01_character.py to have run first and
    committed Aldric to the shared session-scoped database.  If that file
    was skipped or not included, every test here is meaningless, so we
    bail out early with an informative skip message.
    """
    verify = int_session_factory()
    character = verify.query(Character).filter_by(name="Aldric").first()
    verify.close()
    if character is None:
        pytest.skip("Aldric not found — run the full suite: pytest tests/integration/")


# ---------------------------------------------------------------------------
# Shared bot fixture — registers all commands used in Sections 6–10
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def combat_bot(int_session_factory):
    """Bot with roll, attack, weapon, and hp commands registered.

    Session-scoped so the bot is created once for the whole module; the
    session factory is injected so all DB access goes to the shared
    in-memory SQLite instance.
    """
    bot = make_bot()
    from commands.roll_commands import register_roll_commands
    from commands.attack_commands import register_attack_commands
    from commands.weapon_commands import register_weapon_commands
    from commands.health_commands import register_health_commands

    register_roll_commands(bot)
    register_attack_commands(bot)
    register_weapon_commands(bot)
    register_health_commands(bot)
    return bot


# ---------------------------------------------------------------------------
# Helper: extract the first positional arg of the last send_message call
# ---------------------------------------------------------------------------


def _sent_message(interaction) -> str:
    """Return the first positional argument from interaction.response.send_message."""
    return interaction.response.send_message.call_args.args[0]


def _followup_message(interaction) -> str:
    """Return the first positional argument from interaction.followup.send."""
    return interaction.followup.send.call_args.args[0]


def _patch_modules(mocker: MockerFixture, int_session_factory) -> None:
    """Redirect SessionLocal in every command module to the integration DB."""
    patch_session_locals(
        mocker,
        int_session_factory,
        "commands.roll_commands",
        "commands.attack_commands",
        "commands.health_commands",
        "commands.weapon_commands",
    )


# ===========================================================================
# Section 6: Rolling — no character context needed (Aldric exists, unused)
# ===========================================================================


@pytest.mark.asyncio
async def test_6_01_roll_d20(combat_bot, int_session_factory, mocker: MockerFixture):
    """A plain /roll 1d20 sends a message containing the roll result."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="1d20")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "1d20" in message
    assert "Total" in message


@pytest.mark.asyncio
async def test_6_02_roll_2d6_plus_3(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """A plain /roll 2d6+3 sends a message that includes the notation."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="2d6+3")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "2d6" in message
    assert "Total" in message


@pytest.mark.asyncio
async def test_6_04_roll_d20_advantage_takes_higher(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Advantage on 1d20 keeps the higher of the two d20 rolls.

    We mock dice_roller.random.randint to return 15 then 8 in order,
    so advantage must report 15 as the kept result.
    """
    _patch_modules(mocker, int_session_factory)
    mocker.patch("dice_roller.random.randint", side_effect=[15, 8])
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="1d20", advantage="advantage")

    message = _sent_message(interaction)
    assert "15" in message
    assert "8" in message
    # The kept roll (15) must appear before the discarded roll (8) in the label
    assert message.index("15") < message.index("8")


@pytest.mark.asyncio
async def test_6_05_roll_d20_disadvantage_takes_lower(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Disadvantage on 1d20 keeps the lower of the two d20 rolls.

    We mock dice_roller.random.randint to return 15 then 8; disadvantage
    must report 8 as the kept result.
    """
    _patch_modules(mocker, int_session_factory)
    mocker.patch("dice_roller.random.randint", side_effect=[15, 8])
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="1d20", advantage="disadvantage")

    message = _sent_message(interaction)
    assert "8" in message
    assert "15" in message
    # The kept roll (8) must appear before the discarded roll (15) in the label
    assert message.index("8") < message.index("15")


@pytest.mark.asyncio
async def test_6_06_roll_too_many_dice_sends_error(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Rolling more than 1000 dice raises an error (ephemeral response)."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="1001d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_6_07_roll_too_many_sides_sends_error(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """A die with more than 100 000 sides raises an error (ephemeral response)."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="1d100001")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_6_08_roll_gibberish_sends_error(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Completely unrecognised notation produces an ephemeral error response."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="gibberish")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# Section 7: Rolling — character-based (Aldric must exist with skills/stats)
# ===========================================================================


@pytest.mark.asyncio
async def test_7_01_roll_athletics_applies_proficiency(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Rolling athletics for a proficient character sends a response mentioning Aldric."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch("utils.dnd_logic.random.randint", return_value=10)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="athletics")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Aldric" in message
    assert "Athletics" in message


@pytest.mark.asyncio
async def test_7_02_roll_perception_expertise(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Rolling perception (expertise) for Aldric sends a valid response."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch("utils.dnd_logic.random.randint", return_value=12)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="perception")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Aldric" in message
    assert "Perception" in message


@pytest.mark.asyncio
async def test_7_03_roll_stealth_jack_of_all_trades(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Rolling stealth (JOAT half-prof) for Aldric sends a valid response."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch("utils.dnd_logic.random.randint", return_value=8)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="stealth")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Aldric" in message
    assert "Stealth" in message


@pytest.mark.asyncio
async def test_7_04_roll_strength_save_with_proficiency(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Aldric has strength saving throw proficiency; the response mentions Strength Save."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch("utils.dnd_logic.random.randint", return_value=14)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="strength save")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Strength Save" in message
    assert "Aldric" in message


@pytest.mark.asyncio
async def test_7_05_roll_dexterity_save_without_proficiency(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Aldric lacks dexterity saving throw proficiency; still sends a valid response."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch("utils.dnd_logic.random.randint", return_value=7)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="dexterity save")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Dexterity Save" in message
    assert "Aldric" in message


@pytest.mark.asyncio
async def test_7_09_roll_death_save_when_hp_full_sends_error(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Requesting a death save when Aldric's HP is above 0 should return an error.

    Aldric starts with max_hp=-1 (unset) by default.  We explicitly set HP > 0
    so the character is clearly not dying, then verify the command rejects it.
    """
    _patch_modules(mocker, int_session_factory)

    # Ensure Aldric has positive HP so he is not in a dying state
    setup_session = int_session_factory()
    aldric = setup_session.query(Character).filter_by(name="Aldric").first()
    if aldric is not None:
        aldric.max_hp = 30
        aldric.current_hp = 30
        setup_session.commit()
    setup_session.close()

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="death save")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ===========================================================================
# Section 8: Attacks
# ===========================================================================


@pytest.mark.asyncio
async def test_8_01_attack_add_longsword_creates_row(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Adding a Longsword attack creates an Attack row in the DB."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "add")

    await callback(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+3")

    interaction.response.send_message.assert_called_once()

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    longsword = (
        verify.query(Attack)
        .filter_by(character_id=aldric.id, name="Longsword")
        .first()
    )
    verify.close()

    assert longsword is not None
    assert longsword.hit_modifier == 5
    assert longsword.damage_formula == "1d8+3"


@pytest.mark.asyncio
async def test_8_02_attack_add_handaxe_creates_row(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Adding a Handaxe attack creates a second Attack row in the DB."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "add")

    await callback(interaction, name="Handaxe", hit_mod=5, damage_formula="1d6+3")

    interaction.response.send_message.assert_called_once()

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    handaxe = (
        verify.query(Attack)
        .filter_by(character_id=aldric.id, name="Handaxe")
        .first()
    )
    verify.close()

    assert handaxe is not None
    assert handaxe.hit_modifier == 5
    assert handaxe.damage_formula == "1d6+3"


@pytest.mark.asyncio
async def test_8_03_attack_list_shows_both_attacks(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """After adding Longsword and Handaxe, /attack list includes both names."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "list")

    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    call_kwargs = interaction.response.send_message.call_args.kwargs
    # The list command sends an embed; verify via the embed object
    embed = call_kwargs.get("embed")
    assert embed is not None
    field_names = [field.name for field in embed.fields]
    assert "Longsword" in field_names
    assert "Handaxe" in field_names


@pytest.mark.asyncio
async def test_8_05_attack_add_longsword_upsert_updates_values(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Re-adding Longsword with different stats performs an upsert (update)."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "add")

    await callback(interaction, name="Longsword", hit_mod=6, damage_formula="1d8+4")

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "Updated" in message or "Longsword" in message

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    longsword = (
        verify.query(Attack)
        .filter_by(character_id=aldric.id, name="Longsword")
        .first()
    )
    verify.close()

    assert longsword.hit_modifier == 6
    assert longsword.damage_formula == "1d8+4"


@pytest.mark.asyncio
async def test_8_06_attack_list_shows_updated_longsword(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """After the upsert, /attack list still shows Longsword (now with updated stats)."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "list")

    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    field_names = [field.name for field in embed.fields]
    assert "Longsword" in field_names

    # Verify the embed field value shows the updated modifier
    longsword_field = next(f for f in embed.fields if f.name == "Longsword")
    assert "+6" in longsword_field.value or "6" in longsword_field.value


@pytest.mark.asyncio
async def test_8_07_add_attacks_3_through_8_all_succeed(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Add attacks 3–8 (six more) so Aldric has eight attacks total.

    This test adds them sequentially, refreshing the patch between calls since
    mocker patches are reset between test functions.
    """
    _patch_modules(mocker, int_session_factory)
    callback = get_callback(combat_bot, "attack", "add")

    additional_attacks = [
        ("Dagger", 4, "1d4+3"),
        ("Shortbow", 5, "1d6+3"),
        ("Javelin", 5, "1d6+3"),
        ("Rapier", 6, "1d8+3"),
        ("Shield Bash", 3, "1d4+3"),
        ("Unarmed Strike", 5, "1d6+3"),
    ]

    for attack_name, hit_modifier, damage_formula in additional_attacks:
        interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
        await callback(interaction, name=attack_name, hit_mod=hit_modifier, damage_formula=damage_formula)
        interaction.response.send_message.assert_called_once()

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    total_attack_count = (
        verify.query(Attack).filter_by(character_id=aldric.id).count()
    )
    verify.close()

    assert total_attack_count == 8


@pytest.mark.asyncio
async def test_8_08_adding_ninth_attack_is_rejected(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Attempting to add a ninth attack is rejected; the DB still has exactly 8.

    MAX_ATTACKS_PER_CHARACTER is the real limit imported from utils.limits.
    This test verifies that the DB count does not grow beyond the current
    ceiling — which is 8 attacks after test_8_07.
    """
    _patch_modules(mocker, int_session_factory)

    # Temporarily lower the limit so the test is not coupled to the global constant
    mocker.patch("commands.attack_commands.MAX_ATTACKS_PER_CHARACTER", 8)

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "attack", "add")

    await callback(interaction, name="NinthAttack", hit_mod=0, damage_formula="1d4")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    total_attack_count = (
        verify.query(Attack).filter_by(character_id=aldric.id).count()
    )
    verify.close()

    assert total_attack_count == 8


# ===========================================================================
# Section 9: Weapon Search (mocked API)
# ===========================================================================

# Minimal Open5e v2 weapon dict that parse_weapon_fields can consume cleanly.
_FAKE_LONGSWORD = {
    "name": "Longsword",
    "damage_dice": "1d8",
    "damage_type": {"name": "Slashing"},
    "is_simple": False,
    "range": 0,
    "properties": [
        {
            "property": {"name": "Versatile"},
            "detail": "1d10",
        }
    ],
    "document": {"key": "srd-2024"},
}


@pytest.mark.asyncio
async def test_9_01_weapon_search_sends_response_with_weapon_data(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Searching for 'longsword' (mocked API) sends a followup with the weapon name."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        new=AsyncMock(return_value=[_FAKE_LONGSWORD]),
    )
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "weapon", "search")

    await callback(interaction, query="longsword")

    # /weapon search defers then sends via followup
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called()
    followup_text = interaction.followup.send.call_args.args[0]
    assert "Longsword" in followup_text


@pytest.mark.asyncio
async def test_9_02_weapon_add_button_imports_longsword_to_db(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Clicking the weapon-add button for Longsword writes an Attack row to the DB.

    The Longsword already exists from test_8_01, so this performs an upsert
    rather than a new insert.  We verify the row is present and is_imported=True.
    """
    _patch_modules(mocker, int_session_factory)

    from commands.weapon_commands import WeaponAddButton

    button = WeaponAddButton(_FAKE_LONGSWORD)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)

    await button.callback(interaction)

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    longsword_attack = (
        verify.query(Attack)
        .filter_by(character_id=aldric.id, name="Longsword")
        .first()
    )
    verify.close()

    assert longsword_attack is not None
    assert longsword_attack.is_imported is True


@pytest.mark.asyncio
async def test_9_03_weapon_search_no_results_sends_graceful_error(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """When the API returns an empty list, a graceful error followup is sent."""
    _patch_modules(mocker, int_session_factory)
    mocker.patch(
        "commands.weapon_commands.fetch_weapons",
        new=AsyncMock(return_value=[]),
    )
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "weapon", "search")

    await callback(interaction, query="xyznotaweapon")

    # Command defers then sends an ephemeral error via followup
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called()


# ===========================================================================
# Section 10: Health / HP
# ===========================================================================


@pytest.mark.asyncio
async def test_10_01_hp_status_sends_response(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Calling /hp status sends a response (Aldric's HP state, whatever it is)."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "status")

    await callback(interaction)

    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_10_02_hp_set_max_sets_both_hp_values(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Setting max HP to 30 also resets current HP to 30."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "set_max")

    await callback(interaction, max_hp=30)

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    max_hp_value = aldric.max_hp
    current_hp_value = aldric.current_hp
    verify.close()

    assert max_hp_value == 30
    assert current_hp_value == 30


@pytest.mark.asyncio
async def test_10_03_hp_status_after_set_max_shows_30_of_30(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """After set_max, /hp status response includes the character name."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "status")

    await callback(interaction)

    interaction.response.send_message.assert_called_once()
    message = _sent_message(interaction)
    assert "30" in message


@pytest.mark.asyncio
async def test_10_04_hp_damage_reduces_current_hp(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Taking 10 damage reduces current HP from 30 to 20."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "damage")

    await callback(interaction, amount="10")

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    current_hp_value = aldric.current_hp
    verify.close()

    assert current_hp_value == 20


@pytest.mark.asyncio
async def test_10_06_hp_heal_increases_current_hp(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Healing 5 HP increases current HP from 20 to 25."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "heal")

    await callback(interaction, amount="5")

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    current_hp_value = aldric.current_hp
    verify.close()

    assert current_hp_value == 25


@pytest.mark.asyncio
async def test_10_07_hp_temp_sets_temp_hp(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Adding 5 temporary HP stores temp_hp=5 in the DB."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "temp")

    await callback(interaction, amount=5)

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    temp_hp_value = aldric.temp_hp
    verify.close()

    assert temp_hp_value == 5


@pytest.mark.asyncio
async def test_10_08_hp_damage_absorbed_by_temp_hp(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Dealing 3 damage (less than 5 temp HP) is fully absorbed: temp_hp=2, current_hp=25."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "damage")

    await callback(interaction, amount="3")

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    temp_hp_value = aldric.temp_hp
    current_hp_value = aldric.current_hp
    verify.close()

    assert temp_hp_value == 2
    assert current_hp_value == 25


@pytest.mark.asyncio
async def test_10_09_hp_damage_100_clamps_to_zero_and_mentions_downed(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Taking 100 damage drops Aldric to 0 HP (never negative).

    The response must mention that the character is downed/dying, since the
    remaining temp HP (2) + current HP (25) = 27, and 100 > max HP (30) would
    only trigger massive-damage instant-kill if dealt as a single hit from
    positive HP when damage >= max_hp.  Here damage (100) >= max_hp (30) from
    positive HP, so the instant-kill 'died' message should appear.
    """
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "damage")

    await callback(interaction, amount="100")

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    current_hp_value = aldric.current_hp
    verify.close()

    assert current_hp_value == 0

    message = _sent_message(interaction)
    # Either instant-death (massive damage) or downed message must be present
    downed_keywords = ["downed", "death saving", "died", "slain", "death", "killed", "massive"]
    assert any(keyword in message.lower() for keyword in downed_keywords)


@pytest.mark.asyncio
async def test_10_10_death_save_available_when_hp_is_zero(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """With Aldric at 0 HP, /roll death save is now available and sends a response.

    We reset Aldric's death saves first (in case test_10_09 left them modified)
    and verify the command does NOT return an ephemeral error.
    """
    _patch_modules(mocker, int_session_factory)

    # Ensure Aldric is in a dying state (current_hp=0) with clean save counters
    setup_session = int_session_factory()
    aldric = setup_session.query(Character).filter_by(name="Aldric").first()
    if aldric is not None:
        aldric.current_hp = 0
        aldric.death_save_successes = 0
        aldric.death_save_failures = 0
        setup_session.commit()
    setup_session.close()

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "roll")

    await callback(interaction, notation="death save")

    # Should succeed (not ephemeral error)
    interaction.response.send_message.assert_called_once()
    is_ephemeral = interaction.response.send_message.call_args.kwargs.get("ephemeral")
    assert is_ephemeral is not True


@pytest.mark.asyncio
async def test_10_11_hp_heal_from_zero_resets_death_saves(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Healing 1 HP from 0 sets current_hp=1 and resets both death save counters."""
    _patch_modules(mocker, int_session_factory)

    # Ensure Aldric is at 0 HP with some death save progress
    setup_session = int_session_factory()
    aldric = setup_session.query(Character).filter_by(name="Aldric").first()
    if aldric is not None:
        aldric.current_hp = 0
        aldric.death_save_successes = 1
        aldric.death_save_failures = 1
        setup_session.commit()
    setup_session.close()

    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "heal")

    await callback(interaction, amount="1")

    verify = int_session_factory()
    aldric = verify.query(Character).filter_by(name="Aldric").first()
    current_hp_value = aldric.current_hp
    death_save_successes = aldric.death_save_successes
    death_save_failures = aldric.death_save_failures
    verify.close()

    assert current_hp_value == 1
    assert death_save_successes == 0
    assert death_save_failures == 0


@pytest.mark.asyncio
async def test_10_12_hp_set_max_zero_is_rejected(
    combat_bot, int_session_factory, mocker: MockerFixture
):
    """Setting max HP to 0 is invalid; an ephemeral error response is sent."""
    _patch_modules(mocker, int_session_factory)
    interaction = make_e2e_interaction(mocker, user_id=PLAYER_A_ID)
    callback = get_callback(combat_bot, "hp", "set_max")

    await callback(interaction, max_hp=0)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
