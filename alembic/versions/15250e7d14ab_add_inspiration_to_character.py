"""add inspiration to character

Revision ID: 15250e7d14ab
Revises: 2af9a2aa8b72
Create Date: 2026-03-18 16:27:19.471700

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "15250e7d14ab"
down_revision: Union[str, Sequence[str], None] = "2af9a2aa8b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("inspiration", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("inspiration")
