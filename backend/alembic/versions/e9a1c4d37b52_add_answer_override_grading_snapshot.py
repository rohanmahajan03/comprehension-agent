"""add answer override grading snapshot

Revision ID: e9a1c4d37b52
Revises: b7d2e5f81c09
Create Date: 2026-10-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e9a1c4d37b52'
down_revision: Union[str, Sequence[str], None] = 'b7d2e5f81c09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive and deliberately **not** backfilled, unlike `questions.required_points`.
    An override written before this column was graded against points nobody recorded, and
    the soft `question_id` may no longer resolve, so the honest value is NULL ("unknown")
    rather than `[]` (which means "the evaluator chose its own points"). See
    docs/specs/2026-10-11-override-feedback-loop-design.md §3.
    """
    op.add_column(
        'answer_overrides',
        sa.Column('required_points', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column('answer_overrides', sa.Column('evaluator_model', sa.String(), nullable=True))
    op.add_column('answer_overrides', sa.Column('question_kind', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('answer_overrides', 'question_kind')
    op.drop_column('answer_overrides', 'evaluator_model')
    op.drop_column('answer_overrides', 'required_points')
