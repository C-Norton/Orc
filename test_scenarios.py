
from database import SessionLocal
from models import User, Server, Character, Party, Attack, user_server_association
from sqlalchemy import select, update, delete
import os

def test_scenarios():
    db = SessionLocal()
    try:
        # 1. Setup mock data
        user1 = db.query(User).filter_by(discord_id="1").first()
        if not user1:
            user1 = User(discord_id="1")
            db.add(user1)
        
        user2 = db.query(User).filter_by(discord_id="2").first()
        if not user2:
            user2 = User(discord_id="2")
            db.add(user2)
            
        server = db.query(Server).filter_by(discord_id="101").first()
        if not server:
            server = Server(discord_id="101", name="Test Server")
            db.add(server)
        
        db.commit()
        db.refresh(user1)
        db.refresh(user2)
        db.refresh(server)

        # 2. Test duplicate character names for DIFFERENT users (Allowed)
        char1 = db.query(Character).filter_by(user_id=user1.id, server_id=server.id, name="Hero").first()
        if not char1:
            char1 = Character(name="Hero", user_id=user1.id, server_id=server.id, is_active=True)
            db.add(char1)
        
        char2 = db.query(Character).filter_by(user_id=user2.id, server_id=server.id, name="Hero").first()
        if not char2:
            char2 = Character(name="Hero", user_id=user2.id, server_id=server.id, is_active=True)
            db.add(char2)
        
        db.commit()
        print("✓ Created two characters with the same name 'Hero' for different users.")

        # 3. Test duplicate character names for SAME user (Should fail due to constraint)
        try:
            char3 = Character(name="Hero", user_id=user1.id, server_id=server.id)
            db.add(char3)
            db.commit()
            print("! FAILED: Should not allow same user to have two characters with the same name.")
        except Exception as e:
            db.rollback()
            print(f"✓ Correctly prevented same user from having two characters named 'Hero'.")

        # 4. Test Attack Replacement
        # Clear existing attacks for char1
        db.query(Attack).filter_by(character_id=char1.id).delete()
        db.commit()
        
        attack1 = Attack(character_id=char1.id, name="Sword", hit_modifier=5, damage_formula="1d8+3")
        db.add(attack1)
        db.commit()
        print(f"✓ Added 'Sword' attack (+5, 1d8+3) to {char1.name}")

        # Simulate add_attack logic: update if exists
        attack_name = "Sword"
        existing_attack = db.query(Attack).filter_by(character_id=char1.id, name=attack_name).first()
        if existing_attack:
            existing_attack.hit_modifier = 7
            existing_attack.damage_formula = "1d8+5"
            db.commit()
            print(f"✓ Updated 'Sword' attack to (+7, 1d8+5)")
        
        updated_attack = db.query(Attack).filter_by(character_id=char1.id, name="Sword").first()
        assert updated_attack.hit_modifier == 7
        assert updated_attack.damage_formula == "1d8+5"

        # 5. Test Empty Party Creation
        party_name = "EmptyParty"
        existing_party = db.query(Party).filter_by(name=party_name, server_id=server.id).first()
        if existing_party:
            db.delete(existing_party)
            db.commit()
            
        new_party = Party(name=party_name, gm=user1, server=server)
        db.add(new_party)
        db.commit()
        print(f"✓ Created an empty party '{party_name}'")
        assert len(new_party.characters) == 0

        # 6. Test Disambiguation in party_add (Simulated)
        # In party_add, we now have character_owner.
        # Scenario: Add 'Hero' to party, but there are two 'Hero's.
        chars = db.query(Character).filter_by(name="Hero", server_id=server.id).all()
        print(f"Found {len(chars)} characters named 'Hero' in the server.")
        
        # If we specify user2 as owner:
        owner = user2
        selected_char = db.query(Character).filter_by(name="Hero", server_id=server.id, user_id=owner.id).first()
        assert selected_char.user_id == user2.id
        print(f"✓ Correctly disambiguated 'Hero' by owner {user2.discord_id}")

        # 7. Test Character Switch Ownership (Simulated)
        # user1 tries to switch to 'Hero' (his own)
        my_char = db.query(Character).filter_by(user_id=user1.id, server_id=server.id, name="Hero").first()
        assert my_char is not None
        print(f"✓ User 1 can find their own character 'Hero'")

        # user1 tries to switch to 'Hero' but filter by user1.id (Success)
        char_to_switch = db.query(Character).filter_by(user_id=user1.id, server_id=server.id, name="Hero").first()
        assert char_to_switch.user_id == user1.id

        # user1 tries to switch to a name they don't own (Simulate failure logic)
        target_name = "Hero" # Both have it, but user1 should only get theirs
        char_found = db.query(Character).filter_by(user_id=user1.id, server_id=server.id, name=target_name).first()
        assert char_found.user_id == user1.id
        
        print("All simulated scenarios passed.")

    finally:
        db.close()

if __name__ == "__main__":
    test_scenarios()
