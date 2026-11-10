"""human scoring source: recordings.human_scores, awaiting_human statuses

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE 不能在事务块里与使用新值的语句混用；这里只加值，不使用
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE recording_status ADD VALUE IF NOT EXISTS 'awaiting_human' BEFORE 'done'")
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'awaiting_human' BEFORE 'completed'")
    op.add_column('recordings', sa.Column('human_scores', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))


def downgrade() -> None:
    # PostgreSQL 不支持删除枚举值；降级只删列，枚举值保留不用
    op.drop_column('recordings', 'human_scores')
