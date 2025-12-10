"""Add context engineering tables

Revision ID: 001_context_engineering
Revises: None
Create Date: 2024-12-09

Adds tables for the Context Engineering System:
- chat_sessions: Core session management
- session_events: Chronological event stream
- session_workspace_files: File system as context
- session_goals: Todo.md style goal tracking
- session_state_cache: Crash recovery state
- token_usage: Cost tracking
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "001_context_engineering"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create session_status enum
    session_status_enum = sa.Enum(
        'active', 'paused', 'completed', 'expired',
        name='sessionstatus'
    )
    session_status_enum.create(op.get_bind(), checkfirst=True)

    # Create event_type enum
    event_type_enum = sa.Enum(
        'user', 'assistant', 'action', 'observation', 'plan', 'error',
        name='eventtype'
    )
    event_type_enum.create(op.get_bind(), checkfirst=True)

    # Create goal_status enum
    goal_status_enum = sa.Enum(
        'pending', 'in_progress', 'completed', 'cancelled',
        name='goalstatus'
    )
    goal_status_enum.create(op.get_bind(), checkfirst=True)

    # 1. Create chat_sessions table
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('folder_id', sa.String(36), sa.ForeignKey('folders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('context_window_used', sa.Integer(), default=0),
        sa.Column('total_tokens_used', sa.Integer(), default=0),
        sa.Column('total_cost', sa.Numeric(10, 6), default=0),
        sa.Column('status', session_status_enum, default='active'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('last_activity_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_chat_sessions_user', 'chat_sessions', ['user_id'])
    op.create_index('idx_chat_sessions_folder', 'chat_sessions', ['folder_id'])
    op.create_index('idx_chat_sessions_status', 'chat_sessions', ['status'])
    op.create_index('idx_chat_sessions_expires', 'chat_sessions', ['expires_at'])

    # 2. Create session_events table
    op.create_table(
        'session_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence_num', sa.Integer(), nullable=False),
        sa.Column('event_type', event_type_enum, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), default=0),
        sa.Column('cached_tokens', sa.Integer(), default=0),
        sa.Column('metadata', JSONB, default={}),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_session_events_session_seq', 'session_events', ['session_id', 'sequence_num'])
    op.create_index('idx_session_events_type', 'session_events', ['event_type'])

    # 3. Create session_workspace_files table
    op.create_table(
        'session_workspace_files',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reference_key', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=True),
        sa.Column('storage_path', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('metadata', JSONB, default={}),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_session_workspace_session', 'session_workspace_files', ['session_id'])
    op.create_index('idx_session_workspace_key', 'session_workspace_files', ['reference_key'])

    # 4. Create session_goals table
    op.create_table(
        'session_goals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('goal_text', sa.Text(), nullable=False),
        sa.Column('status', goal_status_enum, default='pending'),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('parent_goal_id', sa.String(36), sa.ForeignKey('session_goals.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_session_goals_session', 'session_goals', ['session_id'])
    op.create_index('idx_session_goals_status', 'session_goals', ['status'])

    # 5. Create session_state_cache table
    op.create_table(
        'session_state_cache',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('pending_stores', JSONB, default={}),
        sa.Column('pending_disambiguation', JSONB, default=[]),
        sa.Column('pending_marketing', JSONB, nullable=True),
        sa.Column('pending_report', JSONB, nullable=True),
        sa.Column('last_location', JSONB, nullable=True),
        sa.Column('active_segments', JSONB, default=[]),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_session_state_session', 'session_state_cache', ['session_id'])

    # 6. Create token_usage table
    op.create_table(
        'token_usage',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('request_type', sa.String(50), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('cached_tokens', sa.Integer(), default=0),
        sa.Column('cost_usd', sa.Numeric(10, 8), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_token_usage_session', 'token_usage', ['session_id'])
    op.create_index('idx_token_usage_user', 'token_usage', ['user_id'])
    op.create_index('idx_token_usage_date', 'token_usage', ['created_at'])


def downgrade() -> None:
    # Drop tables in reverse order (due to foreign key constraints)
    op.drop_table('token_usage')
    op.drop_table('session_state_cache')
    op.drop_table('session_goals')
    op.drop_table('session_workspace_files')
    op.drop_table('session_events')
    op.drop_table('chat_sessions')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS goalstatus")
    op.execute("DROP TYPE IF EXISTS eventtype")
    op.execute("DROP TYPE IF EXISTS sessionstatus")
