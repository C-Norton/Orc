"""drop range columns from attack

Revision ID: 60f187b137fd
Revises: dc2151d497c1
Create Date: 2026-03-18 15:00:26.631546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60f187b137fd'
down_revision: Union[str, Sequence[str], None] = 'dc2151d497c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('attacks', schema=None) as batch_op:
        batch_op.drop_column('range_normal')
        batch_op.drop_column('range_long')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('attacks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('range_long', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('range_normal', sa.INTEGER(), nullable=True))
