from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, user_server_association, party_gm_association
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.server import Server
    from models.character import Character
    from models.party import Party


class User(Base):
    """A Discord user registered with the bot."""

    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    servers: Mapped[list["Server"]] = relationship(
        "Server", secondary=user_server_association, back_populates="users"
    )
    characters: Mapped[list["Character"]] = relationship("Character", back_populates="user")
    gm_parties: Mapped[list["Party"]] = relationship(
        "Party", secondary=party_gm_association, back_populates="gms"
    )
