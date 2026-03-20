from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, party_character_association, party_gm_association
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models.user import User
    from models.server import Server
    from models.character import Character
    from models.encounter import Encounter
    from models.party_settings import PartySettings


class Party(Base):
    """A group of characters and their GMs within a server."""

    __tablename__ = "parties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )

    gms: Mapped[list["User"]] = relationship(
        "User", secondary=party_gm_association, back_populates="gm_parties"
    )
    server: Mapped["Server"] = relationship("Server", back_populates="parties")
    characters: Mapped[list["Character"]] = relationship(
        "Character", secondary=party_character_association, back_populates="parties"
    )
    encounters: Mapped[list["Encounter"]] = relationship(
        "Encounter", back_populates="party", cascade="all, delete-orphan"
    )
    settings: Mapped[Optional["PartySettings"]] = relationship(
        "PartySettings",
        back_populates="party",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("server_id", "name", name="_server_party_name_uc"),
    )
