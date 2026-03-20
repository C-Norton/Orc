"""Add party_gm many-to-many table and remove parties.gm_id

Revision ID: d4e8f2a1c6b9
Revises: c7f2a9d1b345
Create Date: 2026-03-16 12:00:00.000000

Replaces the single gm_id FK on the parties table with a party_gm join table
so that parties can have multiple GMs with equal privileges.

Existing gm_id values are migrated into the new table before the column is
dropped.  SQLite does not support DROP COLUMN inline, so we use Alembic's
batch mode (which rebuilds the table) to remove the column cleanly.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8f2a1c6b9"
down_revision: Union[str, None] = "c7f2a9d1b345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create party_gm join table, populate it, then drop parties.gm_id."""
    # 1. Create the new join table
    op.create_table(
        "party_gm",
        sa.Column("party_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # 2. Copy existing GM data from parties.gm_id into the new table
    op.execute("INSERT INTO party_gm (party_id, user_id) SELECT id, gm_id FROM parties")

    # 3. Drop gm_id from parties (batch mode rebuilds the table for SQLite)
    with op.batch_alter_table("parties", schema=None) as batch_op:
        batch_op.drop_column("gm_id")


def downgrade() -> None:
    """Re-add parties.gm_id from party_gm data, then drop the join table."""
    # 1. Add gm_id back as nullable first (cannot know values yet)
    with op.batch_alter_table("parties", schema=None) as batch_op:
        batch_op.add_column(sa.Column("gm_id", sa.Integer(), nullable=True))

    # 2. Populate gm_id from the first entry in party_gm for each party
    op.execute(
        "UPDATE parties SET gm_id = ("
        "  SELECT user_id FROM party_gm"
        "  WHERE party_gm.party_id = parties.id"
        "  LIMIT 1"
        ")"
    )

    # 3. Drop the join table
    op.drop_table("party_gm")
