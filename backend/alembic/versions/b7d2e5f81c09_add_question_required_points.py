"""add question required_points

Revision ID: b7d2e5f81c09
Revises: a8f42b91c7d3
Create Date: 2026-09-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7d2e5f81c09'
down_revision: Union[str, Sequence[str], None] = 'a8f42b91c7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive; `server_default` backfills every existing question as `[]`. That is
    accurate, not just convenient: no question had required points before this column, and
    the evaluator treats an empty list as "grade against the model answer alone", which is
    exactly how those questions were graded when they were written. Backfilling them would
    take a generation call per question and is out of scope.
    """
    op.add_column(
        'questions',
        sa.Column(
            'required_points',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('questions', 'required_points')
