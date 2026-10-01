"""add journal entry

Revision ID: d4e8b1a09c52
Revises: c1a7d9e2f4b3
Create Date: 2026-10-01 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b1a09c52'
down_revision: Union[str, Sequence[str], None] = 'c1a7d9e2f4b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('journal_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('book_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=150), nullable=False),
    sa.Column('subtitle', sa.String(length=300), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('cover_url', sa.String(length=500), nullable=True),
    sa.Column('published', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_journal_entries_id'), 'journal_entries', ['id'], unique=False)
    op.create_index(op.f('ix_journal_entries_user_id'), 'journal_entries', ['user_id'], unique=False)
    op.create_index(op.f('ix_journal_entries_book_id'), 'journal_entries', ['book_id'], unique=False)
    op.create_index(op.f('ix_journal_entries_published'), 'journal_entries', ['published'], unique=False)
    op.create_index(op.f('ix_journal_entries_published_at'), 'journal_entries', ['published_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_journal_entries_published_at'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_published'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_book_id'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_user_id'), table_name='journal_entries')
    op.drop_index(op.f('ix_journal_entries_id'), table_name='journal_entries')
    op.drop_table('journal_entries')
