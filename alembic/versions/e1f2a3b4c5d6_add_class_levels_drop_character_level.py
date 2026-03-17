"""Add class_levels table and drop characters.level column

Revision ID: e1f2a3b4c5d6
Revises: d4e8f2a1c6b9
Create Date: 2026-03-17 10:00:00.000000

Adds the class_levels table so that character level is derived from the sum of
all ClassLevel.level values rather than stored as a single integer column.

Existing characters have their current level value migrated into a
'Fighter' ClassLevel row as a sensible default.  GMs / players should
update their characters with the correct class via /add_class after this
migration runs.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "d4e8f2a1c6b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the new class_levels table
    op.create_table(
        "class_levels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(length=50), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "class_name", name="_character_class_uc"),
    )

    # 2. Migrate existing level data: every character gets a 'Fighter' ClassLevel
    #    with their current level value as a placeholder.
    op.execute(
        "INSERT INTO class_levels (character_id, class_name, level) "
        "SELECT id, 'Fighter', COALESCE(level, 1) FROM characters"
    )

    # 3. Drop the now-redundant level column from characters
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.drop_column("level")


def downgrade() -> None:
    # 1. Re-add the level column (nullable to avoid issues with existing rows)
    with op.batch_alter_table("characters", schema=None) as batch_op:
        batch_op.add_column(sa.Column("level", sa.Integer(), nullable=True))

    # 2. Restore level values from the sum of class_levels per character
    op.execute(
        "UPDATE characters SET level = ("
        "  SELECT COALESCE(SUM(cl.level), 1) FROM class_levels cl"
        "  WHERE cl.character_id = characters.id"
        ")"
    )

    # 3. Drop the class_levels table
    op.drop_table("class_levels")
