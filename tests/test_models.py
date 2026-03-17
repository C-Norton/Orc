

def test_character_has_hp_fields(db_session, sample_character):
    assert sample_character.current_hp == -1
    assert sample_character.max_hp == -1
    assert sample_character.temp_hp == 0

def test_character_hp_persists(db_session, sample_user, sample_server):
    from models import Character
    char = Character(name="HpTest", user=sample_user, server=sample_server, is_active=True, level=1, max_hp=30, current_hp=30, temp_hp=0)
    db_session.add(char)
    db_session.commit()
    
    # Refresh to ensure we're getting fresh data from the DB
    db_session.refresh(char)
    
    loaded = db_session.query(Character).filter_by(name="HpTest").first()
    assert loaded.max_hp == 30
    assert loaded.current_hp == 30
    assert loaded.temp_hp == 0
