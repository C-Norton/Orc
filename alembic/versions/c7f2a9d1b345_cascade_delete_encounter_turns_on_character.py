"""cascade delete encounter_turns on character delete

Revision ID: c7f2a9d1b345
Revises: b5fa2a3ab209
Create Date: 2026-03-16 00:00:00.000000

SQLite cannot ALTER a foreign key constraint in-place, so we use Alembic's
batch mode which rebuilds the table under the hood.
PostgreSQL keeps the original auto-generated constraint name from the inline
ForeignKey in f3a8c1d2e456 (encounter_turns_character_id_fkey), so we use
ALTER TABLE directly there.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7f2a9d1b345"
down_revision: Union[str, Sequence[str], None] = "b5fa2a3ab209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# PostgreSQL auto-names inline FKs as <table>_<column>_fkey.
_PG_FK_NAME = "encounter_turns_character_id_fkey"


def _rebuild_sqlite(character_fk_clause: str) -> None:
    """Rebuild encounter_turns with the given character_id FK clause.
    SQLite cannot ALTER a FK constraint in-place, so we recreate the table."""
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute(
        f"""
        CREATE TABLE encounter_turns_new (
            id INTEGER PRIMARY KEY NOT NULL,
            encounter_id INTEGER NOT NULL REFERENCES encounters(id),
            character_id INTEGER {character_fk_clause},
            enemy_id INTEGER REFERENCES enemies(id),
            initiative_roll INTEGER NOT NULL,
            order_position INTEGER NOT NULL
        )
    """
    )
    op.execute("INSERT INTO encounter_turns_new SELECT * FROM encounter_turns")
    op.execute("DROP TABLE encounter_turns")
    op.execute("ALTER TABLE encounter_turns_new RENAME TO encounter_turns")
    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Add ON DELETE CASCADE to encounter_turns.character_id FK."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE encounter_turns "
            f"DROP CONSTRAINT IF EXISTS {_PG_FK_NAME}"
        )
        op.execute(
            f"ALTER TABLE encounter_turns "
            f"ADD CONSTRAINT {_PG_FK_NAME} "
            f"FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE"
        )
    else:
        _rebuild_sqlite("REFERENCES characters(id) ON DELETE CASCADE")


def downgrade() -> None:
    """Remove ON DELETE CASCADE from encounter_turns.character_id FK."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE encounter_turns "
            f"DROP CONSTRAINT IF EXISTS {_PG_FK_NAME}"
        )
        op.execute(
            f"ALTER TABLE encounter_turns "
            f"ADD CONSTRAINT {_PG_FK_NAME} "
            f"FOREIGN KEY (character_id) REFERENCES characters(id)"
        )
    else:
        _rebuild_sqlite("REFERENCES characters(id)")
