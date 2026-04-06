"""add hp_manually_set and saves_explicitly_configured to character

Revision ID: e3f4a5b6c7d8
Revises: 15250e7d14ab
Create Date: 2026-04-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "15250e7d14ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop any leftover temp table from a previously interrupted batch run
    # (SQLite batch mode creates _alembic_tmp_<table> and removes it on success;
    # a crash between those two steps leaves the stale table behind).
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_characters"))

    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "hp_manually_set",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "saves_explicitly_configured",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("saves_explicitly_configured")
        batch_op.drop_column("hp_manually_set")
