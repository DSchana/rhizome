"""drop question_text and user_response from review_interaction, rename feedback to summary

Revision ID: fa2217307327
Revises: ceb251e4f0dd
Create Date: 2026-03-30 17:09:40.058266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa2217307327'
down_revision: Union[str, Sequence[str], None] = 'ceb251e4f0dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop question_text and user_response, rename feedback to summary."""
    with op.batch_alter_table('review_interaction', schema=None) as batch_op:
        batch_op.drop_column('question_text')
        batch_op.drop_column('user_response')
        batch_op.alter_column('feedback', new_column_name='summary')


def downgrade() -> None:
    """Restore question_text and user_response, rename summary back to feedback."""
    with op.batch_alter_table('review_interaction', schema=None) as batch_op:
        batch_op.alter_column('summary', new_column_name='feedback')
        batch_op.add_column(sa.Column('user_response', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('question_text', sa.Text(), nullable=False, server_default=''))
