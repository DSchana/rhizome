"""change score constraint from 0-5 to 0-3

Revision ID: ceb251e4f0dd
Revises: 4a730d480bae
Create Date: 2026-03-30 16:36:30.940459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ceb251e4f0dd'
down_revision: Union[str, Sequence[str], None] = '4a730d480bae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Narrow score constraint from 0-5 to 0-3."""
    with op.batch_alter_table('review_interaction', schema=None) as batch_op:
        batch_op.drop_constraint('score_range', type_='check')
        batch_op.create_check_constraint('score_range', 'score >= 0 AND score <= 3')


def downgrade() -> None:
    """Restore score constraint to 0-5."""
    with op.batch_alter_table('review_interaction', schema=None) as batch_op:
        batch_op.drop_constraint('score_range', type_='check')
        batch_op.create_check_constraint('score_range', 'score >= 0 AND score <= 5')
