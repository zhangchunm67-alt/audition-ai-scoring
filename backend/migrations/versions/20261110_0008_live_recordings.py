"""录播评估：recordings.mode / exclusions，audition_sheets.kind，朗读稿可为空

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recordings', sa.Column('mode', sa.String(16), nullable=False, server_default='audition'))
    op.add_column('recordings', sa.Column('exclusions', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('audition_sheets', sa.Column('kind', sa.String(16), nullable=False, server_default='audition'))
    op.alter_column('audition_sheets', 'reading_script_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # 录播没有朗读稿，降级后无法保留：先删掉录播及其内部记录是数据删除，这里不替使用者做，有录播数据时直接报错
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM audition_sheets WHERE reading_script_id IS NULL LIMIT 1")).first():
        raise RuntimeError("库里已有录播评估数据，不能降级到 0007")
    op.alter_column('audition_sheets', 'reading_script_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('audition_sheets', 'kind')
    op.drop_column('recordings', 'exclusions')
    op.drop_column('recordings', 'mode')
