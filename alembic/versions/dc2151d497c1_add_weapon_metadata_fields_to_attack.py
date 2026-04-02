"""add weapon metadata fields to attack

Revision ID: dc2151d497c1
Revises: 775c1697e29e
Create Date: 2026-03-18 14:37:34.560308

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dc2151d497c1"
down_revision: Union[str, Sequence[str], None] = "775c1697e29e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("attacks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("damage_type", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("weapon_category", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(sa.Column("range_normal", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("range_long", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("two_handed_damage", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(sa.Column("properties_json", sa.Text(), nullable=True))
        batch_op.add_column(
            # sa.false() renders as 0 on SQLite and false on PostgreSQL.
            sa.Column(
                "is_imported", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    # NOTE: the encounter_turns.character_id CASCADE FK change was already
    # applied by c7f2a9d1b345, which runs earlier in the chain.  The
    # auto-generated drop_constraint(None) that appeared here was invalid
    # (Alembic detected model drift that had already been resolved) and has
    # been removed.


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("attacks", schema=None) as batch_op:
        batch_op.drop_column("is_imported")
        batch_op.drop_column("properties_json")
        batch_op.drop_column("two_handed_damage")
        batch_op.drop_column("range_long")
        batch_op.drop_column("range_normal")
        batch_op.drop_column("weapon_category")
        batch_op.drop_column("damage_type")
