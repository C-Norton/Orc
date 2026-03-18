"""Tests for PartySettings model, get_or_create helper, and /party settings commands."""
import pytest
from models import Party, PartySettings
from enums.enemy_initiative_mode import EnemyInitiativeMode
from tests.conftest import make_interaction
from tests.commands.conftest import get_callback


# ---------------------------------------------------------------------------
# Model / helper tests
# ---------------------------------------------------------------------------


def test_party_settings_default_initiative_mode_is_by_type(db_session, sample_active_party):
    """PartySettings created with no explicit mode defaults to BY_TYPE."""
    settings = PartySettings(party_id=sample_active_party.id)
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    assert settings.initiative_mode == EnemyInitiativeMode.BY_TYPE


def test_party_settings_default_enemy_ac_public_is_false(db_session, sample_active_party):
    """PartySettings created with no explicit value defaults enemy_ac_public to False."""
    settings = PartySettings(party_id=sample_active_party.id)
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    assert settings.enemy_ac_public is False


def test_get_or_create_returns_defaults_for_new_party(db_session, sample_active_party):
    """Helper creates settings with defaults when none exist."""
    from commands.party_commands import _get_or_create_party_settings

    settings = _get_or_create_party_settings(db_session, sample_active_party)
    assert settings.party_id == sample_active_party.id
    assert settings.initiative_mode == EnemyInitiativeMode.BY_TYPE
    assert settings.enemy_ac_public is False


def test_get_or_create_does_not_duplicate_on_second_call(db_session, sample_active_party):
    """Calling the helper twice returns the same settings row, not a duplicate."""
    from commands.party_commands import _get_or_create_party_settings

    settings_first = _get_or_create_party_settings(db_session, sample_active_party)
    db_session.commit()
    settings_second = _get_or_create_party_settings(db_session, sample_active_party)
    assert settings_first.id == settings_second.id
    all_settings = db_session.query(PartySettings).filter_by(
        party_id=sample_active_party.id
    ).all()
    assert len(all_settings) == 1


# ---------------------------------------------------------------------------
# /party settings view
# ---------------------------------------------------------------------------


async def test_settings_view_shows_current_settings(
    party_bot, sample_active_party, interaction
):
    """View shows the default initiative mode and enemy_ac_public for a party."""
    cb = get_callback(party_bot, "party", "settings", "view")
    await cb(interaction)

    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "by_type" in msg.lower() or "by type" in msg.lower()


async def test_settings_view_shows_correct_initiative_mode_after_update(
    db_session, party_bot, sample_active_party, interaction
):
    """View reflects the current initiative_mode after it has been changed."""
    from commands.party_commands import _get_or_create_party_settings

    settings = _get_or_create_party_settings(db_session, sample_active_party)
    settings.initiative_mode = EnemyInitiativeMode.INDIVIDUAL
    db_session.commit()

    cb = get_callback(party_bot, "party", "settings", "view")
    await cb(interaction)

    msg = interaction.response.send_message.call_args.args[0]
    assert "individual" in msg.lower()


# ---------------------------------------------------------------------------
# /party settings initiative_mode
# ---------------------------------------------------------------------------


async def test_settings_initiative_mode_update_success(
    party_bot, sample_active_party, interaction, session_factory
):
    """GM can update initiative_mode to 'individual'."""
    cb = get_callback(party_bot, "party", "settings", "initiative_mode")
    await cb(interaction, party_name="The Fellowship", mode="individual")

    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args.args[0]
    assert "individual" in msg.lower()

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(
        party_id=sample_active_party.id
    ).first()
    assert settings is not None
    assert settings.initiative_mode == EnemyInitiativeMode.INDIVIDUAL
    verify.close()


async def test_settings_initiative_mode_updates_to_shared(
    party_bot, sample_active_party, interaction, session_factory
):
    """GM can update initiative_mode to 'shared'."""
    cb = get_callback(party_bot, "party", "settings", "initiative_mode")
    await cb(interaction, party_name="The Fellowship", mode="shared")

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(
        party_id=sample_active_party.id
    ).first()
    assert settings.initiative_mode == EnemyInitiativeMode.SHARED
    verify.close()


async def test_settings_initiative_mode_invalid_value_rejected(
    party_bot, sample_active_party, interaction
):
    """An unrecognised mode string sends an ephemeral error."""
    cb = get_callback(party_bot, "party", "settings", "initiative_mode")
    await cb(interaction, party_name="The Fellowship", mode="random")

    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    msg = interaction.response.send_message.call_args.args[0]
    assert "invalid" in msg.lower() or "choose" in msg.lower()


async def test_settings_initiative_mode_not_gm_rejected(
    mocker, party_bot, sample_active_party
):
    """A non-GM cannot change initiative mode."""
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party", "settings", "initiative_mode")
    await cb(other, party_name="The Fellowship", mode="individual")

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True


# ---------------------------------------------------------------------------
# /party settings enemy_ac
# ---------------------------------------------------------------------------


async def test_settings_enemy_ac_set_to_true(
    party_bot, sample_active_party, interaction, session_factory
):
    """GM can set enemy_ac_public to True."""
    cb = get_callback(party_bot, "party", "settings", "enemy_ac")
    await cb(interaction, party_name="The Fellowship", public=True)

    interaction.response.send_message.assert_called_once()

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(
        party_id=sample_active_party.id
    ).first()
    assert settings.enemy_ac_public is True
    verify.close()


async def test_settings_enemy_ac_set_to_false(
    db_session, party_bot, sample_active_party, interaction, session_factory
):
    """GM can set enemy_ac_public to False (from an existing True state)."""
    # Pre-create settings with enemy_ac_public=True
    pre_settings = PartySettings(
        party_id=sample_active_party.id,
        enemy_ac_public=True,
    )
    db_session.add(pre_settings)
    db_session.commit()

    cb = get_callback(party_bot, "party", "settings", "enemy_ac")
    await cb(interaction, party_name="The Fellowship", public=False)

    verify = session_factory()
    settings = verify.query(PartySettings).filter_by(
        party_id=sample_active_party.id
    ).first()
    assert settings.enemy_ac_public is False
    verify.close()


async def test_settings_enemy_ac_not_gm_rejected(
    mocker, party_bot, sample_active_party
):
    """A non-GM cannot change enemy AC visibility."""
    other = make_interaction(mocker, user_id=999)
    cb = get_callback(party_bot, "party", "settings", "enemy_ac")
    await cb(other, party_name="The Fellowship", public=True)

    assert other.response.send_message.call_args.kwargs.get("ephemeral") is True
