"""added HP fields to characters

Revision ID: b5fa2a3ab209
Revises: f3a8c1d2e456
Create Date: 2026-03-16 19:05:48.763108

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5fa2a3ab209"
down_revision: Union[str, Sequence[str], None] = "f3a8c1d2e456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_SERVER_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ACTIVE_PARTY_FK_NAME = "fk_user_server_active_party_id_parties"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "max_hp", sa.Integer(), server_default=sa.text("-1"), nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "current_hp", sa.Integer(), server_default=sa.text("-1"), nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "temp_hp", sa.Integer(), server_default=sa.text("0"), nullable=False
            )
        )

    # On PostgreSQL the FK retains the explicit name from ccdde42289b4.
    # On SQLite, batch_alter_table rebuilds the table and applies the naming
    # convention, so the constraint was already renamed to ACTIVE_PARTY_FK_NAME.
    bind = op.get_bind()
    existing_fk_name = (
        "fk_user_server_active_party"
        if bind.dialect.name == "postgresql"
        else ACTIVE_PARTY_FK_NAME
    )

    with op.batch_alter_table(
        "user_server",
        schema=None,
        naming_convention=USER_SERVER_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(existing_fk_name, type_="foreignkey")
        batch_op.create_foreign_key(
            ACTIVE_PARTY_FK_NAME,
            "parties",
            ["active_party_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table(
        "user_server",
        schema=None,
        naming_convention=USER_SERVER_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(ACTIVE_PARTY_FK_NAME, type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_user_server_active_party",
            "parties",
            ["active_party_id"],
            ["id"],
        )

    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("temp_hp")
        batch_op.drop_column("current_hp")
        batch_op.drop_column("max_hp")
