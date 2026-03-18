import pytest
from models import Attack, Character, Enemy, EncounterTurn
from tests.commands.conftest import get_callback
from tests.conftest import make_interaction


# ---------------------------------------------------------------------------
# /attack add
# ---------------------------------------------------------------------------

async def test_add_attack_creates_new(attack_bot, sample_character, interaction, session_factory):
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+3")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "Added" in msg
    assert "Longsword" in msg

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Longsword").first()
    assert attack is not None
    assert attack.hit_modifier == 5
    assert attack.damage_formula == "1d8+3"
    verify.close()


async def test_add_attack_updates_existing(attack_bot, sample_character, interaction, db_session, session_factory):
    existing = Attack(character_id=sample_character.id, name="Dagger", hit_modifier=3, damage_formula="1d4+1")
    db_session.add(existing)
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Dagger", hit_mod=7, damage_formula="1d4+5")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Updated" in msg

    verify = session_factory()
    attack = verify.query(Attack).filter_by(name="Dagger").first()
    assert attack.hit_modifier == 7
    verify.close()


async def test_add_attack_invalid_formula_rejected(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="notadice")

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_add_attack_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Sword", hit_mod=5, damage_formula="1d8")

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /attack roll
# ---------------------------------------------------------------------------

async def test_attack_success(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Longsword", hit_modifier=5, damage_formula="1d8+3"))
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "Aldric" in msg
    assert "Longsword" in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_case_insensitive_lookup(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Longsword", hit_modifier=5, damage_formula="1d8"))
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="longsword")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_not_found(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Vorpal Blade")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_attack_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Sword")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /attack list
# ---------------------------------------------------------------------------

async def test_attacks_list_sends_embed(attack_bot, sample_character, interaction, db_session):
    db_session.add(Attack(character_id=sample_character.id, name="Bow", hit_modifier=4, damage_formula="1d6+2"))
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "list")
    await cb(interaction)

    embed = interaction.response.send_message.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Aldric" in embed.title


async def test_attacks_list_empty(attack_bot, sample_character, interaction):
    cb = get_callback(attack_bot, "attack", "list")
    await cb(interaction)

    msg = interaction.response.send_message.call_args.args[0]
    assert "no attacks" in msg.lower()


async def test_attacks_list_no_character(attack_bot, sample_user, sample_server, interaction):
    cb = get_callback(attack_bot, "attack", "list")
    await cb(interaction)

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------

async def test_add_attack_over_limit_rejected(
    mocker, attack_bot, sample_character, db_session, interaction
):
    """Creating a new attack beyond the per-character cap is rejected."""
    mocker.patch("commands.attack_commands.MAX_ATTACKS_PER_CHARACTER", 2)

    for i in range(2):
        db_session.add(Attack(
            character_id=sample_character.id,
            name=f"Attack{i}",
            hit_modifier=0,
            damage_formula="1d4",
        ))
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="NewAttack", hit_mod=0, damage_formula="1d6")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "maximum" in msg.lower()


async def test_add_attack_update_existing_ignores_limit(
    mocker, attack_bot, sample_character, db_session, interaction
):
    """Updating an existing attack is always allowed even when at the cap."""
    mocker.patch("commands.attack_commands.MAX_ATTACKS_PER_CHARACTER", 1)

    db_session.add(Attack(
        character_id=sample_character.id,
        name="Longsword",
        hit_modifier=3,
        damage_formula="1d8+3",
    ))
    db_session.commit()

    cb = get_callback(attack_bot, "attack", "add")
    await cb(interaction, name="Longsword", hit_mod=5, damage_formula="1d8+5")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


# ---------------------------------------------------------------------------
# /attack roll target=N — Phase 4: targeted attacks
# ---------------------------------------------------------------------------
#
# Test fixtures used:
#   sample_active_encounter  — Aldric (pos 0, init 15) vs Goblin (pos 1, init 10, hp=7)
#   sample_character         — Aldric (the attacker)
#   sample_enemy             — Goblin (the target, max_hp=7, current_hp=7)
#
# Mocking strategy:
#   mocker.patch("commands.attack_commands.random.randint", return_value=N)
#       controls the d20 roll only
#   mocker.patch("commands.attack_commands.roll_dice", return_value=([die], mod, total))
#       controls damage independently of random.randint
#   interaction.client.fetch_user  — mock for GM DM notification


def _add_longsword(db_session, character, hit_modifier=5):
    """Helper: save a Longsword attack on the given character."""
    attack = Attack(
        character_id=character.id,
        name="Longsword",
        hit_modifier=hit_modifier,
        damage_formula="1d8+3",
    )
    db_session.add(attack)
    db_session.commit()
    return attack


async def test_attack_roll_targeted_hit_reduces_enemy_hp(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, session_factory, interaction, mocker,
):
    """A hit reduces the enemy's current_hp by the rolled damage amount."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=10)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([2], 3, 5))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    # hit_total = 10 + 5 = 15 >= AC 12 → hit, damage = 5
    verify = session_factory()
    refreshed = verify.get(Enemy, sample_enemy.id)
    assert refreshed.current_hp == 2  # 7 - 5
    verify.close()


async def test_attack_roll_targeted_miss_no_hp_change(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, session_factory, interaction, mocker,
):
    """A miss leaves the enemy's HP unchanged."""
    sample_enemy.ac = 20
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=5)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([6], 3, 9))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    # hit_total = 5 + 5 = 10 < AC 20 → miss
    verify = session_factory()
    refreshed = verify.get(Enemy, sample_enemy.id)
    assert refreshed.current_hp == 7
    verify.close()


async def test_attack_roll_targeted_hit_message_not_ephemeral(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """A hit produces a public (non-ephemeral) message."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=10)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([2], 3, 5))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_roll_targeted_miss_message_not_ephemeral(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """A miss also produces a public message."""
    sample_enemy.ac = 20
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=1)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([1], 3, 4))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True


async def test_attack_roll_targeted_hit_message_shows_hit_and_damage(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """The public hit message contains the enemy name, 'HIT', and the damage total."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=10)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([2], 3, 5))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    msg = interaction.response.send_message.call_args.args[0]
    assert "Goblin" in msg
    assert "HIT" in msg
    assert "5" in msg  # damage_total


async def test_attack_roll_targeted_miss_message_hides_damage(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """The public miss message shows 'MISS' and does not include the damage roll."""
    sample_enemy.ac = 20
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=1)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([6], 3, 9))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    msg = interaction.response.send_message.call_args.args[0]
    assert "MISS" in msg
    assert "HIT" not in msg
    assert "Damage" not in msg


async def test_attack_roll_targeted_enemy_at_zero_removed_from_turns(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, session_factory, interaction, mocker,
):
    """An enemy reduced to 0 HP is removed from the initiative order."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    # damage_total (20) exceeds current_hp (7) → HP = 0
    mocker.patch("commands.attack_commands.random.randint", return_value=15)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([17], 3, 20))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    verify = session_factory()
    remaining_turns = (
        verify.query(EncounterTurn)
        .filter_by(encounter_id=sample_active_encounter.id)
        .all()
    )
    enemy_turn_ids = [t.enemy_id for t in remaining_turns if t.enemy_id is not None]
    assert sample_enemy.id not in enemy_turn_ids
    verify.close()


async def test_attack_roll_targeted_enemy_death_announced_publicly(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """Killing an enemy produces a public death-announcement followup."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=15)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([17], 3, 20))
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mocker.AsyncMock())

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    followup_call = interaction.followup.send.call_args
    assert followup_call is not None
    death_msg = (
        followup_call.args[0]
        if followup_call.args
        else followup_call.kwargs.get("content", "")
    )
    assert "Goblin" in death_msg
    assert followup_call.kwargs.get("ephemeral") is not True


async def test_attack_roll_targeted_notifies_gms_on_hit(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """After a hit the GM is DMed with the HP update."""
    sample_enemy.ac = 12
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=10)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([2], 3, 5))
    mock_gm_user = mocker.AsyncMock()
    interaction.client.fetch_user = mocker.AsyncMock(return_value=mock_gm_user)

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    # sample_user (discord_id="111") is the GM of sample_active_party
    interaction.client.fetch_user.assert_called_once_with(111)
    mock_gm_user.send.assert_called_once()
    embed = mock_gm_user.send.call_args.kwargs["embed"]
    assert "Test Dungeon" in embed.title
    assert "The Fellowship" in embed.footer.text
    assert "Goblin" in embed.description
    assert "2/7" in embed.description  # HP after 5 damage: 7-5=2


async def test_attack_roll_targeted_no_ac_shows_error(
    attack_bot, sample_active_encounter, sample_enemy, sample_character,
    db_session, interaction, mocker,
):
    """Targeting an enemy with no AC set returns an ephemeral error."""
    # sample_enemy.ac is None by default
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=15)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([5], 3, 8))

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "AC" in msg


async def test_attack_roll_targeted_enemy_not_found(
    attack_bot, sample_active_encounter, sample_character,
    db_session, interaction, mocker,
):
    """Typing a name that doesn't match any enemy returns an ephemeral error."""
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=15)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([5], 3, 8))

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Dragon")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "Dragon" in msg


async def test_attack_roll_targeted_no_active_encounter(
    attack_bot, sample_active_party, sample_character,
    db_session, interaction, mocker,
):
    """Providing a target when there is no active encounter returns an error."""
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=15)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([5], 3, 8))

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target="Goblin")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


async def test_attack_roll_target_autocomplete_returns_enemy_names(
    attack_bot, sample_active_encounter, sample_enemy, interaction,
):
    """Target autocomplete returns the names of enemies in the active encounter."""
    from commands.attack_commands import register_attack_commands
    from tests.commands.conftest import get_callback

    autocomplete_cb = get_callback(attack_bot, "attack", "roll")
    # Call the autocomplete handler directly via the registered command's autocomplete
    attack_cmd = attack_bot.tree.get_command("attack").get_command("roll")
    autocomplete_fn = attack_cmd._params["target"].autocomplete

    choices = await autocomplete_fn(interaction, current="")
    names = [c.name for c in choices]
    assert "Goblin" in names


async def test_attack_roll_target_autocomplete_filters_by_current(
    attack_bot, sample_active_encounter, db_session, sample_pending_encounter, interaction,
):
    """Target autocomplete filters suggestions based on the current input."""
    from models import Enemy, EncounterTurn
    # Add a second enemy so we can verify filtering
    orc = Enemy(
        encounter_id=sample_active_encounter.id,
        name="Orc",
        type_name="Orc",
        initiative_modifier=0,
        max_hp=15,
        current_hp=15,
    )
    db_session.add(orc)
    db_session.flush()
    orc_turn = EncounterTurn(
        encounter_id=sample_active_encounter.id,
        enemy_id=orc.id,
        initiative_roll=8,
        order_position=2,
    )
    db_session.add(orc_turn)
    db_session.commit()

    attack_cmd = attack_bot.tree.get_command("attack").get_command("roll")
    autocomplete_fn = attack_cmd._params["target"].autocomplete

    choices = await autocomplete_fn(interaction, current="Orc")
    names = [c.name for c in choices]
    assert "Orc" in names
    assert "Goblin" not in names


async def test_attack_roll_without_target_unchanged(
    attack_bot, sample_active_encounter, sample_character,
    db_session, interaction, mocker,
):
    """Omitting target produces the original non-targeted message with no HP change."""
    _add_longsword(db_session, sample_character)

    mocker.patch("commands.attack_commands.random.randint", return_value=12)
    mocker.patch("commands.attack_commands.roll_dice", return_value=([5], 3, 8))

    cb = get_callback(attack_bot, "attack", "roll")
    await cb(interaction, attack_name="Longsword", target=None)

    msg = interaction.response.send_message.call_args.args[0]
    assert "HIT" not in msg
    assert "MISS" not in msg
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is not True
