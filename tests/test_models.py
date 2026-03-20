def test_character_has_hp_fields(db_session, sample_character):
    assert sample_character.current_hp == -1
    assert sample_character.max_hp == -1
    assert sample_character.temp_hp == 0


def test_character_hp_persists(db_session, sample_user, sample_server):
    from models import Character

    char = Character(
        name="HpTest",
        user=sample_user,
        server=sample_server,
        is_active=True,
        level=1,
        max_hp=30,
        current_hp=30,
        temp_hp=0,
    )
    db_session.add(char)
    db_session.commit()

    # Refresh to ensure we're getting fresh data from the DB
    db_session.refresh(char)

    loaded = db_session.query(Character).filter_by(name="HpTest").first()
    assert loaded.max_hp == 30
    assert loaded.current_hp == 30
    assert loaded.temp_hp == 0


def test_party_settings_crit_rule_reads_lowercase_value_from_db(
    db_session,
    sample_user,
    sample_server,
):
    """PartySettings.crit_rule must deserialise 'double_dice' (the lowercase
    string value written by the migration server_default) back to
    CritRule.DOUBLE_DICE without raising a LookupError.

    Regression test for: SQLAlchemy SAEnum storing enum names (uppercase) while
    the migration wrote lowercase values, causing a LookupError on reads.
    """
    from sqlalchemy import text
    from enums.crit_rule import CritRule
    from models import Party, PartySettings

    party = Party(name="CritTestParty", server=sample_server, gms=[sample_user])
    db_session.add(party)
    db_session.commit()
    db_session.refresh(party)

    # Insert a row directly with the lowercase value as the migration does via
    # server_default, bypassing the ORM type coercion.
    db_session.execute(
        text(
            "INSERT INTO party_settings (party_id, initiative_mode, enemy_ac_public, crit_rule) "
            "VALUES (:party_id, 'BY_TYPE', 0, 'double_dice')"
        ),
        {"party_id": party.id},
    )
    db_session.commit()

    # Reading back through the ORM must not raise.
    settings = db_session.query(PartySettings).filter_by(party_id=party.id).first()
    assert settings is not None
    assert settings.crit_rule == CritRule.DOUBLE_DICE
