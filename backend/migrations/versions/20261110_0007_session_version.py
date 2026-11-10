"""users.session_version, users.must_change_password

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'session_version')
