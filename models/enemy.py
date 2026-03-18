from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.encounter import Encounter
    from models.encounter_turn import EncounterTurn


class Enemy(Base):
    __tablename__ = "enemies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encounter_id: Mapped[int] = mapped_column(Integer, ForeignKey("encounters.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    initiative_modifier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # HP — max_hp stores the rolled/parsed value; current_hp is set to max_hp on creation
    max_hp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_hp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ac: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    encounter: Mapped["Encounter"] = relationship("Encounter", back_populates="enemies")
    turn: Mapped[Optional["EncounterTurn"]] = relationship(
        "EncounterTurn", back_populates="enemy", uselist=False, cascade="all, delete-orphan"
    )
