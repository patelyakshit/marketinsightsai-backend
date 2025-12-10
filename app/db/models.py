import os
import enum

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean, Enum, JSON, ForeignKey, Numeric, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db.database import Base
from app.utils.datetime_utils import utc_now

# Use Text type for embeddings if pgvector is disabled (store as JSON string)
# This allows the app to work without pgvector, just without vector search
USE_PGVECTOR = os.environ.get("USE_PGVECTOR", "true").lower() == "true"

if USE_PGVECTOR:
    try:
        from pgvector.sqlalchemy import Vector
        VECTOR_TYPE = Vector(1536)
    except ImportError:
        VECTOR_TYPE = Text  # Fallback to Text (store as JSON)
        USE_PGVECTOR = False
else:
    VECTOR_TYPE = Text


# ============== Auth Models ==============

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for OAuth users
    full_name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)  # For Google profile picture
    google_id = Column(String(255), nullable=True, unique=True, index=True)  # Google OAuth ID
    auth_provider = Column(String(50), nullable=True, default="email")  # 'email' or 'google'
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    saved_reports = relationship("SavedReport", back_populates="user")
    owned_teams = relationship("Team", back_populates="owner", foreign_keys="Team.owner_id")
    team_memberships = relationship("TeamMember", back_populates="user")


class Team(Base):
    __tablename__ = "teams"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    owner = relationship("User", back_populates="owned_teams", foreign_keys=[owner_id])
    members = relationship("TeamMember", back_populates="team")
    saved_reports = relationship("SavedReport", back_populates="team")
    report_templates = relationship("ReportTemplate", back_populates="team")


class TeamRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(String(36), primary_key=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    role = Column(Enum(TeamRole), nullable=False, default=TeamRole.member)
    joined_at = Column(DateTime, default=utc_now)

    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


class SavedReport(Base):
    __tablename__ = "saved_reports"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True)
    store_name = Column(String(255), nullable=False)
    store_id = Column(String(255), nullable=True)
    goal = Column(String(100), nullable=False)
    report_url = Column(Text, nullable=False)
    report_html = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    user = relationship("User", back_populates="saved_reports")
    team = relationship("Team", back_populates="saved_reports")


class ReportTemplate(Base):
    __tablename__ = "report_templates"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    goal = Column(String(100), nullable=False)
    config = Column(JSON, default=dict)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    team = relationship("Team", back_populates="report_templates")


# ============== Knowledge Base Models ==============


class DocumentType(str, enum.Enum):
    system = "system"
    workspace = "workspace"


class DocumentCategory(str, enum.Enum):
    segment = "segment"
    demographic = "demographic"
    brand = "brand"
    other = "other"


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    documents = relationship("KnowledgeDocument", back_populates="workspace")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True)
    type = Column(Enum(DocumentType), nullable=False, default=DocumentType.workspace)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    doc_metadata = Column("metadata", JSON, default=dict)  # renamed to avoid SQLAlchemy reserved name
    embedding = Column(VECTOR_TYPE, nullable=True)  # OpenAI embedding dimension
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    workspace = relationship("Workspace", back_populates="documents")


class TapestrySegment(Base):
    __tablename__ = "tapestry_segments"

    id = Column(String(36), primary_key=True)
    code = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    life_mode = Column(String(100), nullable=True)
    life_stage = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    median_age = Column(Float, nullable=True)
    median_household_income = Column(Float, nullable=True)
    median_net_worth = Column(Float, nullable=True)
    homeownership_rate = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class Store(Base):
    __tablename__ = "stores"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    segment_data = relationship("StoreSegmentData", back_populates="store")


class StoreSegmentData(Base):
    __tablename__ = "store_segment_data"

    id = Column(String(36), primary_key=True)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    segment_code = Column(String(10), ForeignKey("tapestry_segments.code"), nullable=False)
    household_share = Column(Float, nullable=False)
    household_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    store = relationship("Store", back_populates="segment_data")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id = Column(String(36), primary_key=True)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), default="pdf")
    created_at = Column(DateTime, default=utc_now)


# ============== Folder (Project) Models ==============
# Folders are persistent containers for files and chats (like ChatGPT Projects)

class Folder(Base):
    """A folder/project that can contain files and multiple chat sessions."""
    __tablename__ = "folders"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    user = relationship("User", backref="folders")
    files = relationship("FolderFile", back_populates="folder", cascade="all, delete-orphan")
    chats = relationship("FolderChat", back_populates="folder", cascade="all, delete-orphan")


class FolderFileType(str, enum.Enum):
    xlsx = "xlsx"
    pdf = "pdf"
    csv = "csv"
    txt = "txt"
    json = "json"
    other = "other"


class FolderFile(Base):
    """A file uploaded to a folder. Available to all chats within the folder."""
    __tablename__ = "folder_files"

    id = Column(String(36), primary_key=True)
    folder_id = Column(String(36), ForeignKey("folders.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(Enum(FolderFileType), nullable=False, default=FolderFileType.other)
    file_size = Column(Integer, nullable=True)  # in bytes
    file_path = Column(String(500), nullable=False)  # Storage path
    content_preview = Column(Text, nullable=True)  # For text files, store preview
    file_metadata = Column("metadata", JSON, default=dict)  # Parsed data (e.g., store names from xlsx)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    folder = relationship("Folder", back_populates="files")


class FolderChat(Base):
    """A chat session within a folder. Has access to all folder files."""
    __tablename__ = "folder_chats"

    id = Column(String(36), primary_key=True)
    folder_id = Column(String(36), ForeignKey("folders.id"), nullable=False)
    title = Column(String(255), nullable=True)  # Auto-generated from first message
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    folder = relationship("Folder", back_populates="chats")
    messages = relationship("FolderChatMessage", back_populates="chat", cascade="all, delete-orphan")


class FolderChatMessage(Base):
    """A message in a folder chat."""
    __tablename__ = "folder_chat_messages"

    id = Column(String(36), primary_key=True)
    chat_id = Column(String(36), ForeignKey("folder_chats.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    chat = relationship("FolderChat", back_populates="messages")


# ============== Context Engineering Models ==============
# Implements Manus AI-inspired context management for persistent, optimized AI conversations


class SessionStatus(str, enum.Enum):
    """Status of a chat session."""
    active = "active"
    paused = "paused"
    completed = "completed"
    expired = "expired"


class EventType(str, enum.Enum):
    """Types of events in the event stream."""
    user = "user"           # User message
    assistant = "assistant" # AI response
    action = "action"       # Tool/function call initiated
    observation = "observation"  # Result from action
    plan = "plan"           # Planning/reasoning step
    error = "error"         # Error occurred


class GoalStatus(str, enum.Enum):
    """Status of a session goal."""
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class ChatSession(Base):
    """
    Core session management for context engineering.
    Tracks user sessions with token usage and cost metrics.
    """
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=True)

    # Context metrics
    context_window_used = Column(Integer, default=0)  # Current tokens in context
    total_tokens_used = Column(Integer, default=0)    # Cumulative tokens
    total_cost = Column(Numeric(10, 6), default=0)    # Cumulative cost in USD

    # Session state
    status = Column(Enum(SessionStatus), default=SessionStatus.active, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)  # Auto-cleanup after TTL

    # Timestamps
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    last_activity_at = Column(DateTime, default=utc_now)

    # Relationships
    user = relationship("User", backref="chat_sessions")
    folder = relationship("Folder", backref="chat_sessions")
    events = relationship("SessionEvent", back_populates="session", cascade="all, delete-orphan")
    workspace_files = relationship("SessionWorkspaceFile", back_populates="session", cascade="all, delete-orphan")
    goals = relationship("SessionGoal", back_populates="session", cascade="all, delete-orphan",
                        foreign_keys="SessionGoal.session_id")
    state_cache = relationship("SessionStateCache", back_populates="session", uselist=False, cascade="all, delete-orphan")
    token_usages = relationship("TokenUsage", back_populates="session", cascade="all, delete-orphan")


class SessionEvent(Base):
    """
    Chronological event stream for context persistence.
    Append-only design for KV-cache optimization.
    """
    __tablename__ = "session_events"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence_num = Column(Integer, nullable=False)  # Order within session

    # Event data
    event_type = Column(Enum(EventType), nullable=False, index=True)
    content = Column(Text, nullable=False)  # JSON content

    # Token tracking
    token_count = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)  # For KV-cache tracking

    # Metadata
    event_metadata = Column("metadata", JSONB, default=dict)  # Action results, error traces, etc.
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    session = relationship("ChatSession", back_populates="events")

    # Composite index for efficient retrieval
    __table_args__ = (
        Index("idx_session_events_session_seq", "session_id", "sequence_num"),
    )


class SessionWorkspaceFile(Base):
    """
    File system as extended context.
    Stores references to large content (not in context window).
    """
    __tablename__ = "session_workspace_files"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    # File reference
    reference_key = Column(String(255), nullable=False, index=True)  # e.g., "tapestry_upload_001.xlsx"
    file_type = Column(String(50), nullable=True)  # xlsx, pdf, json, observation

    # Storage location
    storage_path = Column(Text, nullable=True)  # Path to actual file
    content_hash = Column(String(64), nullable=True)  # SHA256 for deduplication

    # Metadata
    size_bytes = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)  # Brief description for context
    file_metadata = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=utc_now)

    # Relationships
    session = relationship("ChatSession", back_populates="workspace_files")


class SessionGoal(Base):
    """
    Todo.md style goal tracking.
    Goals are placed at END of context to combat "lost-in-the-middle" effect.
    """
    __tablename__ = "session_goals"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Goal content
    goal_text = Column(Text, nullable=False)
    status = Column(Enum(GoalStatus), default=GoalStatus.pending, index=True)
    priority = Column(Integer, default=0)

    # Hierarchy (for subtasks)
    parent_goal_id = Column(String(36), ForeignKey("session_goals.id", ondelete="CASCADE"), nullable=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    session = relationship("ChatSession", back_populates="goals", foreign_keys=[session_id])
    parent_goal = relationship("SessionGoal", remote_side="SessionGoal.id", backref="sub_goals")


class SessionStateCache(Base):
    """
    Crash recovery: Persist in-memory state to database.
    Replaces _chat_stores, _pending_* dicts from chat.py
    """
    __tablename__ = "session_state_cache"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Cached state (JSON serialized) - replaces in-memory dicts
    pending_stores = Column(JSONB, default=dict)        # Replaces _chat_stores
    pending_disambiguation = Column(JSONB, default=list)  # Replaces _pending_disambiguation
    pending_marketing = Column(JSONB, nullable=True)    # Replaces _pending_marketing
    pending_report = Column(JSONB, nullable=True)       # Replaces _pending_report

    # Esri/map context
    last_location = Column(JSONB, nullable=True)
    active_segments = Column(JSONB, default=list)

    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    session = relationship("ChatSession", back_populates="state_cache")


class TokenUsage(Base):
    """
    Token usage and cost tracking per request.
    Enables cost analysis, budgeting, and optimization.
    """
    __tablename__ = "token_usage"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Request details
    model = Column(String(100), nullable=False)
    request_type = Column(String(50), nullable=True)  # chat, embedding, image

    # Token counts
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cached_tokens = Column(Integer, default=0)

    # Cost
    cost_usd = Column(Numeric(10, 8), nullable=False)

    created_at = Column(DateTime, default=utc_now, index=True)

    # Relationships
    session = relationship("ChatSession", back_populates="token_usages")
    user = relationship("User", backref="token_usages")
