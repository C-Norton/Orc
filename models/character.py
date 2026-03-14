from sqlalchemy import Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, party_character_association
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User
    from models.server import Server
    from models.character_skill import CharacterSkill
    from models.attack import Attack
    from models.party import Party

class Character(Base):
    __tablename__ = 'characters'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey('servers.id'), nullable=False)
    
    # Core Stats
    strength: Mapped[int] = mapped_column(Integer, default=10)
    dexterity: Mapped[int] = mapped_column(Integer, default=10)
    constitution: Mapped[int] = mapped_column(Integer, default=10)
    intelligence: Mapped[int] = mapped_column(Integer, default=10)
    wisdom: Mapped[int] = mapped_column(Integer, default=10)
    charisma: Mapped[int] = mapped_column(Integer, default=10)
    
    level: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Saving Throw Proficiency Status
    st_prof_strength: Mapped[bool] = mapped_column(Boolean, default=False)
    st_prof_dexterity: Mapped[bool] = mapped_column(Boolean, default=False)
    st_prof_constitution: Mapped[bool] = mapped_column(Boolean, default=False)
    st_prof_intelligence: Mapped[bool] = mapped_column(Boolean, default=False)
    st_prof_wisdom: Mapped[bool] = mapped_column(Boolean, default=False)
    st_prof_charisma: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="characters")
    server: Mapped["Server"] = relationship("Server", back_populates="characters")
    skills: Mapped[list["CharacterSkill"]] = relationship("CharacterSkill", back_populates="character", cascade="all, delete-orphan")
    attacks: Mapped[list["Attack"]] = relationship("Attack", back_populates="character", cascade="all, delete-orphan")
    parties: Mapped[list["Party"]] = relationship("Party", secondary=party_character_association, back_populates="characters")

    __table_args__ = (UniqueConstraint('user_id', 'server_id', 'name', name='_user_server_name_uc'),)
