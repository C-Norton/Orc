from sqlalchemy import Integer, String, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base
from enums.encounter_status import EncounterStatus
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.party import Party
    from models.server import Server
    from models.enemy import Enemy
    from models.encounter_turn import EncounterTurn


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("parties.id"), nullable=False
    )
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )
    status: Mapped[EncounterStatus] = mapped_column(
        SAEnum(EncounterStatus), nullable=False, default=EncounterStatus.PENDING
    )
    current_turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Stored so /next_turn can edit the original message
    message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    channel_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    party: Mapped["Party"] = relationship("Party", back_populates="encounters")
    server: Mapped["Server"] = relationship("Server", back_populates="encounters")
    enemies: Mapped[list["Enemy"]] = relationship(
        "Enemy", back_populates="encounter", cascade="all, delete-orphan"
    )
    turns: Mapped[list["EncounterTurn"]] = relationship(
        "EncounterTurn", back_populates="encounter", cascade="all, delete-orphan"
    )
