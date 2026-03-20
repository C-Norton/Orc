"""merge encounter enhancements with character branch

Revision ID: 0ab11be76904
Revises: b2c3d4e5f6a7, f2a3b4c5d6e7
Create Date: 2026-03-17 20:39:23.729625

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0ab11be76904"
down_revision: Union[str, Sequence[str], None] = ("b2c3d4e5f6a7", "f2a3b4c5d6e7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
