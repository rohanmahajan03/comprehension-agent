"""add concept source_quotes

Revision ID: f3a7d12c48be
Revises: c1e4a9b7f20d
Create Date: 2026-09-14 09:31:07.412006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3a7d12c48be'
down_revision: Union[str, Sequence[str], None] = 'c1e4a9b7f20d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive, and NOT NULL is safe on a populated table here for the same reason it
    was for documents.status: `server_default` backfills every existing row as `[]`, which
    is accurate rather than merely convenient — no concept had its own source quotes before
    this column existed, extracted ones included. Backfilling them is out of scope
    (docs/specs/2026-09-13-concept-evidence-generation.md §10, and see
    docs/specs/2026-09-14-concept-evidence-measurement-and-generalization.md §7 for why it
    stays that way once extraction starts filling this column).
    """
    op.add_column(
        'concepts',
        sa.Column(
            'source_quotes',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('concepts', 'source_quotes')
