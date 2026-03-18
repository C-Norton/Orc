"""add_crit_rule_to_party_settings

Revision ID: 775c1697e29e
Revises: 0ab11be76904
Create Date: 2026-03-17 22:10:55.910849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '775c1697e29e'
down_revision: Union[str, Sequence[str], None] = '0ab11be76904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('party_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'crit_rule',
            sa.Enum('double_dice', 'perkins', 'double_damage', 'max_damage', 'none', name='critrule'),
            nullable=False,
            server_default='double_dice',
        ))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('party_settings', schema=None) as batch_op:
        batch_op.drop_column('crit_rule')
