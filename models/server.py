from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, user_server_association
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User
    from models.character import Character
    from models.party import Party
    from models.encounter import Encounter


class Server(Base):
    __tablename__ = "servers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    users: Mapped[list["User"]] = relationship(
        "User", secondary=user_server_association, back_populates="servers"
    )
    characters: Mapped[list["Character"]] = relationship(
        "Character", back_populates="server"
    )
    parties: Mapped[list["Party"]] = relationship("Party", back_populates="server")
    encounters: Mapped[list["Encounter"]] = relationship(
        "Encounter", back_populates="server"
    )
