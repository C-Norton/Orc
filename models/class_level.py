"""ClassLevel model — one row per (character, class) pair."""

from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.character import Character


class ClassLevel(Base):
    """Stores how many levels a character has in a given class.

    Each character may have at most one row per class name (enforced by unique
    constraint).  The primary key is used to infer insertion order, which
    determines which class grants the "max hit-die at level 1" bonus.
    """

    __tablename__ = "class_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    class_name: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    character: Mapped["Character"] = relationship("Character", back_populates="class_levels")

    __table_args__ = (
        UniqueConstraint("character_id", "class_name", name="_character_class_uc"),
    )
