"""set null on active party delete

Revision ID: 1ac033e2009a
Revises: a85d17a1341e
Create Date: 2026-03-16 08:13:39.912904

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1ac033e2009a"
down_revision: Union[str, Sequence[str], None] = "a85d17a1341e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate detected a drift on the active_party_id FK in user_server,
    # but produced `drop_constraint(None)` — invalid because SQLite does not
    # assign names to inline FK constraints and Alembic's batch mode requires
    # a name to drop one. The ON DELETE SET NULL behaviour is already present
    # in the table as created by the original create_all (the Column definition
    # in models/base.py carries `ondelete='SET NULL'`). No schema change needed.
    pass


def downgrade() -> None:
    pass
