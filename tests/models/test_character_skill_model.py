"""Model-level tests for CharacterSkill.

These tests inspect SQLAlchemy column metadata directly and do not require
a database connection.
"""

import sqlalchemy

from models.character_skill import CharacterSkill


def _get_proficiency_column() -> sqlalchemy.Column:
    """Return the SQLAlchemy Column object for CharacterSkill.proficiency."""
    return CharacterSkill.__table__.c["proficiency"]


def test_proficiency_enum_type_name_is_proficiencylevel() -> None:
    """The proficiency column's Enum type must carry the name 'proficiencylevel'.

    SQLAlchemy derives the PostgreSQL enum type name from the ``name``
    argument passed to ``Enum(...)``.  Without an explicit name, SQLAlchemy
    would fall back to the Python class name ('skillproficiencystatus'),
    which does not match the type created by the initial migration
    ('proficiencylevel') and causes a production error.

    This test fails if the ``name="proficiencylevel"`` argument is removed
    from the column definition.
    """
    column = _get_proficiency_column()
    assert column.type.name == "proficiencylevel"


def test_proficiency_column_type_is_enum() -> None:
    """The proficiency column must use a SQLAlchemy Enum type."""
    column = _get_proficiency_column()
    assert isinstance(column.type, sqlalchemy.Enum)
