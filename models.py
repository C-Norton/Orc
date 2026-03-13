from sqlalchemy import Integer, String, Boolean, ForeignKey, Table, UniqueConstraint, Enum, Column
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from enums.skill_proficiency_status import SkillProficiencyStatus

class Base(DeclarativeBase):
    pass

user_server_association = Table(
    'user_server',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('server_id', Integer, ForeignKey('servers.id')),
    Column('active_party_id', Integer, ForeignKey('parties.id'))
)

party_character_association = Table(
    'party_character',
    Base.metadata,
    Column('party_id', Integer, ForeignKey('parties.id')),
    Column('character_id', Integer, ForeignKey('characters.id'))
)

class Server(Base):
    __tablename__ = 'servers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    
    users: Mapped[list["User"]] = relationship("User", secondary=user_server_association, back_populates="servers")
    characters: Mapped[list["Character"]] = relationship("Character", back_populates="server")
    parties: Mapped[list["Party"]] = relationship("Party", back_populates="server")

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    
    servers: Mapped[list["Server"]] = relationship("Server", secondary=user_server_association, back_populates="users")
    characters: Mapped[list["Character"]] = relationship("Character", back_populates="user")
    gm_parties: Mapped[list["Party"]] = relationship("Party", back_populates="gm")

class Party(Base):
    __tablename__ = 'parties'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    gm_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey('servers.id'), nullable=False)

    gm: Mapped["User"] = relationship("User", back_populates="gm_parties")
    server: Mapped["Server"] = relationship("Server", back_populates="parties")
    characters: Mapped[list["Character"]] = relationship("Character", secondary=party_character_association, back_populates="parties")

    __table_args__ = (UniqueConstraint('server_id', 'name', name='_server_party_name_uc'),)

class Character(Base):
    __tablename__ = 'characters'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey('servers.id'), nullable=False)
    
    # Core Stats
    strength: Mapped[int] = mapped_column(Integer, default=10)
    dexterity: Mapped[int] = mapped_column(Integer, default=10)
    constitution: Mapped[int] = mapped_column(Integer, default=10)
    intelligence: Mapped[int] = mapped_column(Integer, default=10)
    wisdom: Mapped[int] = mapped_column(Integer, default=10)
    charisma: Mapped[int] = mapped_column(Integer, default=10)
    
    level: Mapped[int] = mapped_column(Integer, default=1)
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
    skills: Mapped[list["CharacterSkill"]] = relationship("CharacterSkill", back_populates="character", cascade="all, delete-orphan")
    attacks: Mapped[list["Attack"]] = relationship("Attack", back_populates="character", cascade="all, delete-orphan")
    parties: Mapped[list["Party"]] = relationship("Party", secondary=party_character_association, back_populates="characters")

    __table_args__ = (UniqueConstraint('user_id', 'server_id', 'name', name='_user_server_name_uc'),)

class CharacterSkill(Base):
    __tablename__ = 'character_skills'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(Integer, ForeignKey('characters.id'), nullable=False)
    skill_name: Mapped[str] = mapped_column(String, nullable=False)
    proficiency: Mapped[SkillProficiencyStatus] = mapped_column(Enum(SkillProficiencyStatus), default=SkillProficiencyStatus.NOT_PROFICIENT)
    
    character: Mapped["Character"] = relationship("Character", back_populates="skills")

class Attack(Base):
    __tablename__ = 'attacks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(Integer, ForeignKey('characters.id'), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hit_modifier: Mapped[int] = mapped_column(Integer, default=0)
    damage_formula: Mapped[str] = mapped_column(String, nullable=False)
    
    character: Mapped["Character"] = relationship("Character", back_populates="attacks")
