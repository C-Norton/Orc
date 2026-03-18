from sqlalchemy import Boolean, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.character import Character


class Attack(Base):
    """A saved attack belonging to a character.

    Manual attacks (via ``/attack add``) populate only the core fields.
    Imported attacks (via ``/weapon add``) also set the optional metadata
    columns for richer display and future full-sheet logic.
    """

    __tablename__ = "attacks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("characters.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    hit_modifier: Mapped[int] = mapped_column(Integer, default=0)
    damage_formula: Mapped[str] = mapped_column(String, nullable=False)

    # --- Optional weapon metadata (populated on import, None for manual entries) ---

    damage_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    weapon_category: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # "Simple" or "Martial"
    two_handed_damage: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # e.g. "1d10" for Versatile weapons
    properties_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON array of property name strings
    is_imported: Mapped[bool] = mapped_column(Boolean, default=False)

    character: Mapped["Character"] = relationship("Character", back_populates="attacks")

    __table_args__ = (
        UniqueConstraint("character_id", "name", name="_character_attack_name_uc"),
    )
