"""added HP fields to characters

Revision ID: b5fa2a3ab209
Revises: f3a8c1d2e456
Create Date: 2026-03-16 19:05:48.763108

"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import MetaData, Table as SATable, inspect as sa_inspect, text


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


def _find_active_party_fk_name(bind) -> Optional[str]:
    """Return the current name of the user_server → parties FK.

    SQLite stores FK constraint names when the ``CONSTRAINT name`` syntax is
    used in ``CREATE TABLE``.  Alembic's batch mode uses that syntax, so the
    FK created by ``ccdde42289b4`` is stored as ``"fk_user_server_active_party"``.
    Pre-migration databases (created via ``Base.metadata.create_all``) have
    an unnamed FK; in that case we reflect the table with the naming convention
    to obtain the auto-assigned name that ``batch_alter_table`` will use.

    Returns ``None`` if no FK to ``parties`` is found (should not happen in
    practice, but makes the upgrade step safe to re-run).
    """
    inspector = sa_inspect(bind)
    fks = inspector.get_foreign_keys("user_server")
    parties_fk = next((fk for fk in fks if fk["referred_table"] == "parties"), None)

    if parties_fk is None:
        return None

    if parties_fk["name"]:
        # FK has an explicit stored name (both PostgreSQL and SQLite when the
        # constraint was created via batch_alter_table with a named FK).
        return parties_fk["name"]

    # Unnamed FK (pre-migration SQLite database): reflect with the same naming
    # convention that batch_alter_table uses so we get the identical name.
    nc_metadata = MetaData(naming_convention=USER_SERVER_NAMING_CONVENTION)
    reflected_table = SATable("user_server", nc_metadata, autoload_with=bind)
    parties_fkc = next(
        (
            fkc
            for fkc in reflected_table.foreign_key_constraints
            if any(col.name == "active_party_id" for col in fkc.columns)
        ),
        None,
    )
    return str(parties_fkc.name) if parties_fkc else None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("characters")}

    # SQLite has no transactional DDL: a previous failed run may have left an
    # orphaned _alembic_tmp_characters table.  Drop it before batch_alter_table
    # tries to create it again so the migration is safe to re-run.
    # Use op.execute() rather than bind.execute() so the statement goes through
    # Alembic's context and does not disturb SQLite's transaction state.
    if bind.dialect.name == "sqlite":
        op.execute(text("DROP TABLE IF EXISTS _alembic_tmp_characters"))
        op.execute(text("DROP TABLE IF EXISTS _alembic_tmp_user_server"))

    # Skip if a previous partial run already added the HP columns.
    if "max_hp" not in existing_columns:
        with op.batch_alter_table("characters", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "max_hp", sa.Integer(), server_default=sa.text("-1"), nullable=False
                )
            )
            batch_op.add_column(
                sa.Column(
                    "current_hp",
                    sa.Integer(),
                    server_default=sa.text("-1"),
                    nullable=False,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "temp_hp",
                    sa.Integer(),
                    server_default=sa.text("0"),
                    nullable=False,
                )
            )

    bind = op.get_bind()
    existing_fk_name = _find_active_party_fk_name(bind)

    with op.batch_alter_table(
        "user_server",
        schema=None,
        naming_convention=USER_SERVER_NAMING_CONVENTION,
    ) as batch_op:
        if existing_fk_name:
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
