"""
Context Engineering Services

Manus AI-inspired context management for MarketInsightsAI.
Provides session management, event streaming, token tracking, and context building.

Components:
- token_service: Token counting and cost tracking
- session_service: Session lifecycle management
- event_stream_service: Chronological event logging
- context_builder_service: KV-cache optimized context assembly
- workspace_service: File system as extended context
- goal_service: Todo.md style goal tracking
"""

from app.services.context import token_service
from app.services.context import session_service
from app.services.context import event_stream_service
from app.services.context import context_builder_service
from app.services.context import workspace_service
from app.services.context import goal_service

# Token service exports
from app.services.context.token_service import (
    count_tokens,
    count_messages_tokens,
    calculate_cost,
    record_usage,
    get_session_usage,
    get_user_usage,
    estimate_context_tokens,
    PRICING,
)

# Session service exports
from app.services.context.session_service import (
    create_session,
    get_session,
    get_session_with_relations,
    get_or_create_session,
    list_user_sessions,
    restore_session_state,
    save_session_state,
    update_session_metrics,
    update_session_status,
    delete_session,
    expire_stale_sessions,
    cleanup_expired_sessions,
)

# Event stream service exports
from app.services.context.event_stream_service import (
    append_event,
    record_user_message,
    record_assistant_response,
    record_action,
    record_observation,
    record_plan,
    record_error,
    get_recent_events,
    get_events,
    get_conversation_messages,
    get_total_event_tokens,
    update_cached_tokens,
)

# Context builder service exports
from app.services.context.context_builder_service import (
    get_stable_system_prompt,
    format_event_for_context,
    compress_old_events,
    format_goals_section,
    build_context,
    build_messages_for_api,
    estimate_cache_savings,
    CONTEXT_LIMITS,
)

# Workspace service exports
from app.services.context.workspace_service import (
    store_large_observation,
    retrieve_workspace_file,
    get_workspace_file,
    list_workspace_files,
    get_workspace_summary,
    get_workspace_references,
    delete_workspace_file,
    cleanup_workspace,
    store_api_response,
)

# Goal service exports
from app.services.context.goal_service import (
    add_goal,
    get_goal,
    get_goals,
    get_active_goals,
    update_goal,
    update_goal_status,
    complete_goal,
    cancel_goal,
    start_goal,
    delete_goal,
    format_goals_for_context,
    parse_goals_from_response,
    add_goals_from_response,
)

__all__ = [
    # Modules
    "token_service",
    "session_service",
    "event_stream_service",
    "context_builder_service",
    "workspace_service",
    "goal_service",
    # Token service
    "count_tokens",
    "count_messages_tokens",
    "calculate_cost",
    "record_usage",
    "get_session_usage",
    "get_user_usage",
    "estimate_context_tokens",
    "PRICING",
    # Session service
    "create_session",
    "get_session",
    "get_session_with_relations",
    "get_or_create_session",
    "list_user_sessions",
    "restore_session_state",
    "save_session_state",
    "update_session_metrics",
    "update_session_status",
    "delete_session",
    "expire_stale_sessions",
    "cleanup_expired_sessions",
    # Event stream service
    "append_event",
    "record_user_message",
    "record_assistant_response",
    "record_action",
    "record_observation",
    "record_plan",
    "record_error",
    "get_recent_events",
    "get_events",
    "get_conversation_messages",
    "get_total_event_tokens",
    "update_cached_tokens",
    # Context builder service
    "get_stable_system_prompt",
    "format_event_for_context",
    "compress_old_events",
    "format_goals_section",
    "build_context",
    "build_messages_for_api",
    "estimate_cache_savings",
    "CONTEXT_LIMITS",
    # Workspace service
    "store_large_observation",
    "retrieve_workspace_file",
    "get_workspace_file",
    "list_workspace_files",
    "get_workspace_summary",
    "get_workspace_references",
    "delete_workspace_file",
    "cleanup_workspace",
    "store_api_response",
    # Goal service
    "add_goal",
    "get_goal",
    "get_goals",
    "get_active_goals",
    "update_goal",
    "update_goal_status",
    "complete_goal",
    "cancel_goal",
    "start_goal",
    "delete_goal",
    "format_goals_for_context",
    "parse_goals_from_response",
    "add_goals_from_response",
]
