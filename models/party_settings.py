"""PartySettings model — per-party configuration table."""

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from enums.crit_rule import CritRule
from enums.death_save_nat20_mode import DeathSaveNat20Mode
from enums.enemy_initiative_mode import EnemyInitiativeMode
from models.base import Base

if TYPE_CHECKING:
    from models.party import Party


class PartySettings(Base):
    """Per-party configuration, lazy-created on first access.

    Holds GM-configurable options that change how encounters behave for a
    specific party, such as how enemy initiative is rolled and whether enemy
    AC values are visible to players.
    """

    __tablename__ = "party_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("parties.id"), unique=True, nullable=False
    )
    initiative_mode: Mapped[EnemyInitiativeMode] = mapped_column(
        SAEnum(EnemyInitiativeMode),
        nullable=False,
        default=EnemyInitiativeMode.BY_TYPE,
    )
    enemy_ac_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    crit_rule: Mapped[CritRule] = mapped_column(
        SAEnum(CritRule, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CritRule.DOUBLE_DICE,
    )
    death_save_nat20_mode: Mapped[DeathSaveNat20Mode] = mapped_column(
        SAEnum(DeathSaveNat20Mode, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeathSaveNat20Mode.REGAIN_HP,
        server_default=DeathSaveNat20Mode.REGAIN_HP.value,
    )

    party: Mapped["Party"] = relationship("Party", back_populates="settings")
