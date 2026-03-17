from database import SessionLocal
from models import User, Server, Character, Attack, CharacterSkill
from sqlalchemy import create_engine
import os

def test_delete_character():
    db = SessionLocal()
    try:
        # Setup mock data
        user = db.query(User).filter_by(discord_id="test_user").first()
        if not user:
            user = User(discord_id="test_user")
            db.add(user)
        
        server = db.query(Server).filter_by(discord_id="test_server").first()
        if not server:
            server = Server(discord_id="test_server", name="Test Server")
            db.add(server)
        
        db.commit()
        db.refresh(user)
        db.refresh(server)

        # Create a character to delete
        char_name = "To Be Deleted"
        char = db.query(Character).filter_by(user_id=user.id, server_id=server.id, name=char_name).first()
        if not char:
            char = Character(name=char_name, user_id=user.id, server_id=server.id)
            db.add(char)
            db.commit()
            db.refresh(char)
        
        # Add some associated data
        attack = Attack(character_id=char.id, name="Test Attack", hit_modifier=5, damage_formula="1d8")
        skill = CharacterSkill(character_id=char.id, skill_name="Athletics")
        db.add(attack)
        db.add(skill)
        db.commit()

        # Verify existence
        assert db.query(Character).filter_by(id=char.id).first() is not None
        assert db.query(Attack).filter_by(character_id=char.id).first() is not None
        assert db.query(CharacterSkill).filter_by(character_id=char.id).first() is not None
        print(f"✓ Character '{char_name}' and associated data created.")

        # Simulate delete_character logic
        # 1. Ownership check (simulated by query filter)
        target_char = db.query(Character).filter_by(user=user, server=server, name=char_name).first()
        assert target_char is not None
        
        # 2. Delete
        db.delete(target_char)
        db.commit()
        print(f"✓ Character '{char_name}' deleted.")

        # Verify deletion and cascade
        assert db.query(Character).filter_by(id=char.id).first() is None
        assert db.query(Attack).filter_by(character_id=char.id).first() is None
        assert db.query(CharacterSkill).filter_by(character_id=char.id).first() is None
        print("✓ Associated data correctly cascaded.")

        # Test deleting non-existent character (should not fail, but find nothing)
        target_char = db.query(Character).filter_by(user=user, server=server, name="Does Not Exist").first()
        assert target_char is None
        print("✓ Correctly handled non-existent character.")

        # Test ownership (simulated)
        user2 = db.query(User).filter_by(discord_id="other_user").first()
        if not user2:
            user2 = User(discord_id="other_user")
            db.add(user2)
            db.commit()
        
        char3 = Character(name="Owner Test", user_id=user.id, server_id=server.id)
        db.add(char3)
        db.commit()

        # User 2 tries to find User 1's character
        found = db.query(Character).filter_by(user=user2, server=server, name="Owner Test").first()
        assert found is None
        print("✓ Ownership check verified (User 2 cannot find User 1's character).")

        # Cleanup
        db.delete(char3)
        db.commit()

    finally:
        db.close()

if __name__ == "__main__":
    test_delete_character()
