from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, party_character_association
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User
    from models.server import Server
    from models.character import Character
    from models.encounter import Encounter

class Party(Base):
    __tablename__ = 'parties'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    gm_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey('servers.id'), nullable=False)

    gm: Mapped["User"] = relationship("User", back_populates="gm_parties")
    server: Mapped["Server"] = relationship("Server", back_populates="parties")
    characters: Mapped[list["Character"]] = relationship("Character", secondary=party_character_association, back_populates="parties")
    encounters: Mapped[list["Encounter"]] = relationship("Encounter", back_populates="party")

    __table_args__ = (UniqueConstraint('server_id', 'name', name='_server_party_name_uc'),)
