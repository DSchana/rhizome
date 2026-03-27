"""Add resource, topic_resource, and resource_chunk tables

Revision ID: 4a730d480bae
Revises: a395173f659e
Create Date: 2026-03-27 14:11:21.423560

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a730d480bae'
down_revision: Union[str, Sequence[str], None] = 'a395173f659e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('resource',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('content_hash', sa.String(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('estimated_tokens', sa.Integer(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('loading_preference', sa.Enum('auto', 'context_stuff', 'vector_store', name='loadingpreference'), server_default='auto', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('topic_resource',
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('topic_id', 'resource_id')
    )
    op.create_table('resource_chunk',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=False),
    sa.Column('end_offset', sa.Integer(), nullable=False),
    sa.Column('context_tag', sa.JSON(), nullable=True),
    sa.Column('embedding', sa.LargeBinary(), nullable=True),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('resource_chunk', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_resource_chunk_resource_id'), ['resource_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('resource_chunk', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_resource_chunk_resource_id'))

    op.drop_table('resource_chunk')
    op.drop_table('topic_resource')
    op.drop_table('resource')
