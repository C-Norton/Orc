from sqlalchemy import Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, party_character_association
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.user import User
    from models.server import Server
    from models.character_skill import CharacterSkill
    from models.attack import Attack
    from models.party import Party
    from models.class_level import ClassLevel


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )

    # Core Stats
    strength: Mapped[int] = mapped_column(Integer, nullable=True)
    dexterity: Mapped[int] = mapped_column(Integer, nullable=True)
    constitution: Mapped[int] = mapped_column(Integer, nullable=True)
    intelligence: Mapped[int] = mapped_column(Integer, nullable=True)
    wisdom: Mapped[int] = mapped_column(Integer, nullable=True)
    charisma: Mapped[int] = mapped_column(Integer, nullable=True)

    initiative_bonus: Mapped[int] = mapped_column(Integer, nullable=True)
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
    skills: Mapped[list["CharacterSkill"]] = relationship(
        "CharacterSkill", back_populates="character", cascade="all, delete-orphan"
    )
    attacks: Mapped[list["Attack"]] = relationship(
        "Attack", back_populates="character", cascade="all, delete-orphan"
    )
    parties: Mapped[list["Party"]] = relationship(
        "Party", secondary=party_character_association, back_populates="characters"
    )
    class_levels: Mapped[list["ClassLevel"]] = relationship(
        "ClassLevel", back_populates="character", cascade="all, delete-orphan"
    )

    max_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    current_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    temp_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ac: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Inspiration (5e: awarded by GM or via Perkins crit rule; spent for advantage)
    inspiration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    # Death saving throw counters (reset on stabilize, death, or healing from ≤ 0 HP)
    death_save_successes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    death_save_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "server_id", "name", name="_user_server_name_uc"),
    )

    @property
    def level(self) -> int:
        """Total character level — sum of all class levels."""
        return sum(cl.level for cl in self.class_levels)

    @level.setter
    def level(self, value: int) -> None:  # noqa: F811
        """No-op setter so ORM assignment like ``Character(level=5)`` doesn't crash."""
