from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, ForeignKey, Table, Column

class Base(DeclarativeBase):
    pass

user_server_association = Table(
    'user_server',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('server_id', Integer, ForeignKey('servers.id')),
    Column('active_party_id', Integer, ForeignKey('parties.id', ondelete='SET NULL')))

party_character_association = Table(
    'party_character',
    Base.metadata,
    Column('party_id', Integer, ForeignKey('parties.id')),
    Column('character_id', Integer, ForeignKey('characters.id'))
)

party_gm_association = Table(
    'party_gm',
    Base.metadata,
    Column('party_id', Integer, ForeignKey('parties.id', ondelete='CASCADE')),
    Column('user_id', Integer, ForeignKey('users.id'))
)
