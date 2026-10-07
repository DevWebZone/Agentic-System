"""initialize schema baseline

Revision ID: 20261008_0001
Revises:
Create Date: 2026-10-08 00:00:00
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20261008_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish Alembic versioning before domain tables are introduced."""


def downgrade() -> None:
    """The baseline contains no domain objects to remove."""
