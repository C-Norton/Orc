"""add party_settings table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create party_settings table with initiative_mode and enemy_ac_public columns."""
    op.create_table(
        "party_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "party_id",
            sa.Integer(),
            sa.ForeignKey("parties.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "initiative_mode",
            sa.Enum("by_type", "individual", "shared", name="enemyinitiativemode"),
            nullable=False,
            server_default="by_type",
        ),
        sa.Column(
            "enemy_ac_public",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop party_settings table and the enemyinitiativemode enum type."""
    op.drop_table("party_settings")
    op.execute("DROP TYPE IF EXISTS enemyinitiativemode")
