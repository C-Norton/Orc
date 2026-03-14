from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.character import Character

class Attack(Base):
    __tablename__ = 'attacks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(Integer, ForeignKey('characters.id'), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hit_modifier: Mapped[int] = mapped_column(Integer, default=0)
    damage_formula: Mapped[str] = mapped_column(String, nullable=False)
    
    character: Mapped["Character"] = relationship("Character", back_populates="attacks")

    __table_args__ = (UniqueConstraint('character_id', 'name', name='_character_attack_name_uc'),)
