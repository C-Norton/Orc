from sqlalchemy import Integer, String, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from enums.skill_proficiency_status import SkillProficiencyStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.character import Character


class CharacterSkill(Base):
    """A skill proficiency entry for a character.

    One row per proficient (or higher) skill.  Skills at NOT_PROFICIENT are not
    stored — absence of a row implies no proficiency.
    """

    __tablename__ = "character_skills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("characters.id"), nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String, nullable=False)
    proficiency: Mapped[SkillProficiencyStatus] = mapped_column(
        Enum(SkillProficiencyStatus, name="proficiencylevel"),
        default=SkillProficiencyStatus.NOT_PROFICIENT,
    )

    character: Mapped["Character"] = relationship("Character", back_populates="skills")
