"""add answer_overrides

Revision ID: a8f42b91c7d3
Revises: f3a7d12c48be
Create Date: 2026-09-18 10:12:44.918233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f42b91c7d3'
down_revision: Union[str, Sequence[str], None] = 'f3a7d12c48be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    A brand-new table, so none of the NOT-NULL-on-a-populated-table reasoning the recent
    migrations carry applies — there are no existing rows to backfill.

    Note what is absent: **no foreign keys**, unlike every other table in this schema. That
    is the point of the feature rather than an oversight. `study_session_id`, `question_id`,
    `concept_id` and `doc_id` are soft references, and the four snapshot columns carry the
    text, because both delete paths that reach the rest of the schema cascade
    (`study_sessions` → `history_entries`, `documents` → `concepts` → `questions`) and this
    record has to outlive what it describes. See
    docs/specs/2026-09-18-manual-answer-override-design.md §5.

    The unique constraint is load-bearing, not hygiene: an override appends nothing to
    `history_entries`, so it is what stops a double-submitted click from advancing the study
    session twice (design doc §6).
    """
    op.create_table(
        'answer_overrides',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('study_session_id', sa.String(), nullable=False),
        sa.Column('history_seq', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.String(), nullable=False),
        sa.Column('concept_id', sa.String(), nullable=False),
        sa.Column('doc_id', sa.String(), nullable=False),
        sa.Column('question_prompt', sa.String(), nullable=False),
        sa.Column('expected_answer_notes', sa.String(), nullable=False),
        sa.Column('student_answer', sa.String(), nullable=False),
        sa.Column('evaluator_explanation', sa.String(), nullable=False),
        sa.Column('student_note', sa.String(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('study_session_id', 'history_seq'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('answer_overrides')
