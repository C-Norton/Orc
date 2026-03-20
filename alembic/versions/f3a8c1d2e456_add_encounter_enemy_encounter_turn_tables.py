"""add encounter enemy encounter_turn tables

Revision ID: f3a8c1d2e456
Revises: 1ac033e2009a
Create Date: 2026-03-16 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from enums.encounter_status import EncounterStatus

# revision identifiers, used by Alembic.
revision: str = "f3a8c1d2e456"
down_revision: Union[str, Sequence[str], None] = "1ac033e2009a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "encounters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False
        ),
        sa.Column(
            "server_id", sa.Integer(), sa.ForeignKey("servers.id"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(EncounterStatus),
            nullable=False,
            server_default=EncounterStatus.PENDING.value,
        ),
        sa.Column(
            "current_turn_index", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("channel_id", sa.String(), nullable=True),
    )

    op.create_table(
        "enemies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "encounter_id", sa.Integer(), sa.ForeignKey("encounters.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "initiative_modifier", sa.Integer(), nullable=False, server_default="0"
        ),
        # HP columns are placeholders — full HP tracking is being designed separately
        sa.Column("max_hp", sa.Integer(), nullable=True),
        sa.Column("current_hp", sa.Integer(), nullable=True),
    )

    op.create_table(
        "encounter_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "encounter_id", sa.Integer(), sa.ForeignKey("encounters.id"), nullable=False
        ),
        sa.Column(
            "character_id", sa.Integer(), sa.ForeignKey("characters.id"), nullable=True
        ),
        sa.Column("enemy_id", sa.Integer(), sa.ForeignKey("enemies.id"), nullable=True),
        sa.Column("initiative_roll", sa.Integer(), nullable=False),
        sa.Column("order_position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("encounter_turns")
    op.drop_table("enemies")
    op.drop_table("encounters")
