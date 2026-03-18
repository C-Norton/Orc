"""add type_name and ac to enemies

Revision ID: a1b2c3d4e5f6
Revises: f3a8c1d2e456
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f3a8c1d2e456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add type_name (grouping key) and ac (Armor Class) columns to enemies."""
    op.add_column('enemies', sa.Column('type_name', sa.String(length=100), nullable=False, server_default=''))
    op.add_column('enemies', sa.Column('ac', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove type_name and ac columns from enemies."""
    op.drop_column('enemies', 'ac')
    op.drop_column('enemies', 'type_name')
