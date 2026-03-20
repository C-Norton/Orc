from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.encounter import Encounter
    from models.character import Character
    from models.enemy import Enemy


class EncounterTurn(Base):
    """One row per participant per encounter. Exactly one of character_id or
    enemy_id must be set; the other must be NULL."""

    __tablename__ = "encounter_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encounter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("encounters.id"), nullable=False
    )

    # Exactly one of these will be non-NULL
    character_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=True
    )
    enemy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("enemies.id"), nullable=True
    )

    initiative_roll: Mapped[int] = mapped_column(Integer, nullable=False)
    order_position: Mapped[int] = mapped_column(Integer, nullable=False)

    encounter: Mapped["Encounter"] = relationship("Encounter", back_populates="turns")
    character: Mapped[Optional["Character"]] = relationship("Character")
    enemy: Mapped[Optional["Enemy"]] = relationship("Enemy", back_populates="turn")
