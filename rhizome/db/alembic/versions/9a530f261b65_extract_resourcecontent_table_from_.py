"""Extract ResourceContent table from Resource

Revision ID: 9a530f261b65
Revises: 419ed0ac8ad2
Create Date: 2026-04-12 21:47:34.926751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '9a530f261b65'
down_revision: Union[str, Sequence[str], None] = '419ed0ac8ad2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create the new table.
    op.create_table('resource_content',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('source_bytes', sa.LargeBinary(), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('resource_id')
    )

    # 2. Copy existing data from resource into resource_content.
    op.execute(
        "INSERT INTO resource_content (resource_id, raw_text, source_bytes, source_metadata) "
        "SELECT id, raw_text, source_bytes, source_metadata FROM resource"
    )

    # 3. Drop the old columns from resource.
    with op.batch_alter_table('resource', schema=None) as batch_op:
        batch_op.drop_column('source_bytes')
        batch_op.drop_column('source_metadata')
        batch_op.drop_column('raw_text')


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Re-add columns to resource.
    with op.batch_alter_table('resource', schema=None) as batch_op:
        batch_op.add_column(sa.Column('raw_text', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('source_metadata', sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column('source_bytes', sa.BLOB(), nullable=True))

    # 2. Copy data back from resource_content.
    op.execute(
        "UPDATE resource SET "
        "raw_text = (SELECT rc.raw_text FROM resource_content rc WHERE rc.resource_id = resource.id), "
        "source_bytes = (SELECT rc.source_bytes FROM resource_content rc WHERE rc.resource_id = resource.id), "
        "source_metadata = (SELECT rc.source_metadata FROM resource_content rc WHERE rc.resource_id = resource.id)"
    )

    # 3. Drop the resource_content table.
    op.drop_table('resource_content')
