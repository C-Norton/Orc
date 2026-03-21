"""add death save counters to character

Revision ID: 2af9a2aa8b72
Revises: 60f187b137fd
Create Date: 2026-03-18 15:51:21.863806

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2af9a2aa8b72"
down_revision: Union[str, Sequence[str], None] = "60f187b137fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "death_save_successes", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "death_save_failures", sa.Integer(), nullable=False, server_default="0"
            )
        )

    with op.batch_alter_table("party_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "death_save_nat20_mode",
                sa.Enum("regain_hp", "double_success", name="deathsavenat20mode"),
                nullable=False,
                server_default="regain_hp",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("party_settings", schema=None) as batch_op:
        batch_op.drop_column("death_save_nat20_mode")
    # DROP TYPE is PostgreSQL-specific; SQLite has no native enum types.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS deathsavenat20mode")

    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("death_save_failures")
        batch_op.drop_column("death_save_successes")
