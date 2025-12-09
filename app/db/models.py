from datetime import datetime
import os
from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean, Enum, JSON, ForeignKey
from sqlalchemy.orm import relationship
import enum

from app.db.database import Base

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    saved_reports = relationship("SavedReport", back_populates="user")
    owned_teams = relationship("Team", back_populates="owner", foreign_keys="Team.owner_id")
    team_memberships = relationship("TeamMember", back_populates="user")


class Team(Base):
    __tablename__ = "teams"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    joined_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Store(Base):
    __tablename__ = "stores"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    segment_data = relationship("StoreSegmentData", back_populates="store")


class StoreSegmentData(Base):
    __tablename__ = "store_segment_data"

    id = Column(String(36), primary_key=True)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    segment_code = Column(String(10), ForeignKey("tapestry_segments.code"), nullable=False)
    household_share = Column(Float, nullable=False)
    household_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", back_populates="segment_data")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id = Column(String(36), primary_key=True)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), default="pdf")
    created_at = Column(DateTime, default=datetime.utcnow)


# ============== Folder (Project) Models ==============
# Folders are persistent containers for files and chats (like ChatGPT Projects)

class Folder(Base):
    """A folder/project that can contain files and multiple chat sessions."""
    __tablename__ = "folders"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    folder = relationship("Folder", back_populates="files")


class FolderChat(Base):
    """A chat session within a folder. Has access to all folder files."""
    __tablename__ = "folder_chats"

    id = Column(String(36), primary_key=True)
    folder_id = Column(String(36), ForeignKey("folders.id"), nullable=False)
    title = Column(String(255), nullable=True)  # Auto-generated from first message
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    chat = relationship("FolderChat", back_populates="messages")
