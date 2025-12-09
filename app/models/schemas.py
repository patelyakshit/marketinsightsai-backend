from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class DocumentCategory(str, Enum):
    segment = "segment"
    demographic = "demographic"
    brand = "brand"
    other = "other"


# Chat models
class ChatRequest(BaseModel):
    message: str
    use_knowledge_base: bool = True


class ChatResponse(BaseModel):
    response: str
    sources: list[str] = []


class ImageGenerationRequest(BaseModel):
    prompt: str


class ImageGenerationResponse(BaseModel):
    imageUrl: str
    description: str = ""


# Tapestry segment models
class TapestrySegment(BaseModel):
    code: str
    name: str
    household_share: float = Field(alias="householdShare")
    household_count: int = Field(alias="householdCount")
    life_mode: str = Field(alias="lifeMode", default="")
    life_stage: str = Field(alias="lifeStage", default="")
    description: Optional[str] = None
    median_age: Optional[float] = Field(None, alias="medianAge")
    median_household_income: Optional[float] = Field(None, alias="medianHouseholdIncome")
    median_net_worth: Optional[float] = Field(None, alias="medianNetWorth")
    median_home_value: Optional[float] = Field(None, alias="medianHomeValue")
    homeownership_rate: Optional[float] = Field(None, alias="homeownershipRate")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,  # Always serialize using camelCase aliases
    }


class Store(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    store_number: Optional[str] = Field(None, alias="storeNumber")
    drive_time: Optional[str] = Field(None, alias="driveTime")
    segments: list[TapestrySegment] = []

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class TapestryUploadResponse(BaseModel):
    stores: list[Store]
    message: str = ""


class ReportGenerateRequest(BaseModel):
    store_id: str = Field(alias="storeId")

    class Config:
        populate_by_name = True


class ReportGenerateResponse(BaseModel):
    report_url: str = Field(alias="reportUrl")
    message: str = ""

    class Config:
        populate_by_name = True


# Map action types
class MapActionType(str, Enum):
    zoom_to = "zoom_to"
    disambiguate = "disambiguate"


class MapLocation(BaseModel):
    """A location for map actions."""
    name: str
    longitude: float
    latitude: float
    zoom: int = 12


class MapAction(BaseModel):
    """Action for the map component to perform."""
    type: MapActionType
    location: Optional[MapLocation] = None  # For zoom_to action
    options: list[MapLocation] = []  # For disambiguate action (multiple matches)
    query: Optional[str] = None  # Original query for context

    class Config:
        populate_by_name = True


# AI Chat with file support
class AIChatResponse(BaseModel):
    response: str
    sources: list[str] = []
    stores: list[Store] = []  # Populated when a tapestry file is uploaded
    report_url: Optional[str] = Field(None, alias="reportUrl")  # Populated when report is generated
    map_action: Optional[MapAction] = Field(None, alias="mapAction")  # For map navigation commands
    marketing_action: Optional["MarketingAction"] = Field(None, alias="marketingAction")  # For marketing post flow

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


# Knowledge base models
class DocumentMetadata(BaseModel):
    segment_code: Optional[str] = Field(None, alias="segmentCode")
    category: Optional[DocumentCategory] = None

    class Config:
        populate_by_name = True


class KnowledgeDocument(BaseModel):
    id: str
    workspace_id: Optional[str] = Field(None, alias="workspaceId")
    title: str
    content: str
    metadata: DocumentMetadata
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True


class DocumentListResponse(BaseModel):
    documents: list[KnowledgeDocument]


class DocumentUploadResponse(BaseModel):
    document: KnowledgeDocument
    message: str = ""


# Marketing post models
class MarketingPlatform(str, Enum):
    instagram = "instagram"
    linkedin = "linkedin"
    facebook = "facebook"
    twitter = "twitter"


class MarketingRecommendation(BaseModel):
    """AI-generated marketing recommendation based on segment data."""
    store_id: str = Field(alias="storeId")
    store_name: str = Field(alias="storeName")
    headline: str
    body: str
    hashtags: list[str] = []
    suggested_platforms: list[MarketingPlatform] = Field(alias="suggestedPlatforms")
    visual_concept: str = Field(alias="visualConcept")
    segment_insights: str = Field(alias="segmentInsights")
    awaiting_approval: bool = Field(default=True, alias="awaitingApproval")

    class Config:
        populate_by_name = True


class MarketingPost(BaseModel):
    """A generated marketing post with image."""
    id: str
    store_id: str = Field(alias="storeId")
    store_name: str = Field(alias="storeName")
    platform: MarketingPlatform
    headline: str
    body: str
    hashtags: list[str] = []
    image_url: Optional[str] = Field(None, alias="imageUrl")
    image_prompt: Optional[str] = Field(None, alias="imagePrompt")
    is_generating: bool = Field(default=False, alias="isGenerating")
    created_at: datetime = Field(alias="createdAt")

    class Config:
        populate_by_name = True


class MarketingActionType(str, Enum):
    """Types of marketing-related actions."""
    recommendation = "recommendation"  # Show recommendation to user
    generate_image = "generate_image"  # Generate the marketing image
    none = "none"  # No marketing action


class MarketingAction(BaseModel):
    """Action for marketing post flow."""
    type: MarketingActionType
    recommendation: Optional[MarketingRecommendation] = None
    post: Optional[MarketingPost] = None
    platform: Optional[MarketingPlatform] = None

    class Config:
        populate_by_name = True


# ============== Folder (Project) Schemas ==============

class FolderFileType(str, Enum):
    xlsx = "xlsx"
    pdf = "pdf"
    csv = "csv"
    txt = "txt"
    json = "json"
    other = "other"


class FolderFileBase(BaseModel):
    """Base schema for folder files."""
    original_filename: str = Field(alias="originalFilename")
    file_type: FolderFileType = Field(alias="fileType")
    file_size: Optional[int] = Field(None, alias="fileSize")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class FolderFileResponse(FolderFileBase):
    """Response schema for folder files."""
    id: str
    folder_id: str = Field(alias="folderId")
    filename: str
    content_preview: Optional[str] = Field(None, alias="contentPreview")
    metadata: dict = {}
    created_at: datetime = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class FolderChatMessageResponse(BaseModel):
    """Response schema for chat messages."""
    id: str
    chat_id: str = Field(alias="chatId")
    role: str
    content: str
    image_url: Optional[str] = Field(None, alias="imageUrl")
    created_at: datetime = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class FolderChatResponse(BaseModel):
    """Response schema for folder chats."""
    id: str
    folder_id: str = Field(alias="folderId")
    title: Optional[str] = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    messages: list[FolderChatMessageResponse] = []

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class FolderBase(BaseModel):
    """Base schema for folders."""
    name: str
    description: Optional[str] = None


class FolderCreate(FolderBase):
    """Schema for creating a folder."""
    pass


class FolderUpdate(BaseModel):
    """Schema for updating a folder."""
    name: Optional[str] = None
    description: Optional[str] = None


class FolderResponse(FolderBase):
    """Response schema for folders."""
    id: str
    user_id: str = Field(alias="userId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    file_count: int = Field(0, alias="fileCount")
    chat_count: int = Field(0, alias="chatCount")
    files: list[FolderFileResponse] = []

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class FolderListResponse(BaseModel):
    """Response schema for listing folders."""
    folders: list[FolderResponse]


class FolderChatCreate(BaseModel):
    """Schema for creating a chat in a folder."""
    title: Optional[str] = None


class FolderChatMessageCreate(BaseModel):
    """Schema for creating a message in a folder chat."""
    role: str
    content: str
    image_url: Optional[str] = Field(None, alias="imageUrl")

    model_config = {
        "populate_by_name": True,
    }


# ============== Context Engineering Schemas ==============
# Pydantic schemas for session management, events, goals, and context tracking


class SessionStatus(str, Enum):
    """Status of a chat session."""
    active = "active"
    paused = "paused"
    completed = "completed"
    expired = "expired"


class EventType(str, Enum):
    """Types of events in the event stream."""
    user = "user"
    assistant = "assistant"
    action = "action"
    observation = "observation"
    plan = "plan"
    error = "error"


class GoalStatus(str, Enum):
    """Status of a session goal."""
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


# Session schemas
class SessionCreate(BaseModel):
    """Schema for creating a new chat session."""
    folder_id: Optional[str] = Field(None, alias="folderId")
    title: Optional[str] = None

    model_config = {
        "populate_by_name": True,
    }


class SessionResponse(BaseModel):
    """Response schema for chat sessions."""
    id: str
    user_id: str = Field(alias="userId")
    folder_id: Optional[str] = Field(None, alias="folderId")
    title: Optional[str] = None
    status: SessionStatus
    context_window_used: int = Field(0, alias="contextWindowUsed")
    total_tokens_used: int = Field(0, alias="totalTokensUsed")
    total_cost: float = Field(0, alias="totalCost")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    last_activity_at: datetime = Field(alias="lastActivityAt")
    expires_at: Optional[datetime] = Field(None, alias="expiresAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class SessionListResponse(BaseModel):
    """Response schema for listing sessions."""
    sessions: list[SessionResponse]
    total: int = 0


# Event schemas
class EventCreate(BaseModel):
    """Schema for creating a session event."""
    event_type: EventType = Field(alias="eventType")
    content: dict
    metadata: Optional[dict] = None

    model_config = {
        "populate_by_name": True,
    }


class EventResponse(BaseModel):
    """Response schema for session events."""
    id: str
    session_id: str = Field(alias="sessionId")
    sequence_num: int = Field(alias="sequenceNum")
    event_type: EventType = Field(alias="eventType")
    content: dict
    token_count: int = Field(0, alias="tokenCount")
    cached_tokens: int = Field(0, alias="cachedTokens")
    metadata: dict = {}
    created_at: datetime = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class EventListResponse(BaseModel):
    """Response schema for listing events."""
    events: list[EventResponse]
    total: int = 0


# Goal schemas
class GoalCreate(BaseModel):
    """Schema for creating a session goal."""
    goal_text: str = Field(alias="goalText")
    parent_goal_id: Optional[str] = Field(None, alias="parentGoalId")
    priority: int = 0

    model_config = {
        "populate_by_name": True,
    }


class GoalUpdate(BaseModel):
    """Schema for updating a goal."""
    goal_text: Optional[str] = Field(None, alias="goalText")
    status: Optional[GoalStatus] = None
    priority: Optional[int] = None

    model_config = {
        "populate_by_name": True,
    }


class GoalResponse(BaseModel):
    """Response schema for session goals."""
    id: str
    session_id: str = Field(alias="sessionId")
    goal_text: str = Field(alias="goalText")
    status: GoalStatus
    priority: int = 0
    parent_goal_id: Optional[str] = Field(None, alias="parentGoalId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: Optional[datetime] = Field(None, alias="completedAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class GoalListResponse(BaseModel):
    """Response schema for listing goals."""
    goals: list[GoalResponse]


# Workspace file schemas
class WorkspaceFileResponse(BaseModel):
    """Response schema for workspace files."""
    id: str
    session_id: str = Field(alias="sessionId")
    reference_key: str = Field(alias="referenceKey")
    file_type: Optional[str] = Field(None, alias="fileType")
    size_bytes: Optional[int] = Field(None, alias="sizeBytes")
    summary: Optional[str] = None
    metadata: dict = {}
    created_at: datetime = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


# Token usage schemas
class TokenUsageResponse(BaseModel):
    """Response schema for token usage."""
    id: str
    session_id: str = Field(alias="sessionId")
    model: str
    request_type: Optional[str] = Field(None, alias="requestType")
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    cached_tokens: int = Field(0, alias="cachedTokens")
    cost_usd: float = Field(alias="costUsd")
    created_at: datetime = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class SessionUsageStats(BaseModel):
    """Aggregated usage statistics for a session."""
    session_id: str = Field(alias="sessionId")
    total_requests: int = Field(alias="totalRequests")
    total_input_tokens: int = Field(alias="totalInputTokens")
    total_output_tokens: int = Field(alias="totalOutputTokens")
    total_cached_tokens: int = Field(alias="totalCachedTokens")
    total_cost_usd: float = Field(alias="totalCostUsd")
    cache_hit_rate: float = Field(alias="cacheHitRate")  # 0.0 - 1.0

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


# Context metrics schema
class ContextMetrics(BaseModel):
    """Metrics about the current context window."""
    total_tokens: int = Field(alias="totalTokens")
    system_tokens: int = Field(alias="systemTokens")
    history_tokens: int = Field(alias="historyTokens")
    goals_tokens: int = Field(alias="goalsTokens")
    available_tokens: int = Field(alias="availableTokens")
    max_tokens: int = Field(alias="maxTokens")
    utilization: float  # 0.0 - 1.0
    cache_hit_estimate: float = Field(alias="cacheHitEstimate")  # 0.0 - 1.0

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


# Session state schema (for crash recovery)
class SessionState(BaseModel):
    """In-memory session state that can be persisted."""
    pending_stores: dict[str, Store] = Field(default_factory=dict, alias="pendingStores")
    pending_disambiguation: list[MapLocation] = Field(default_factory=list, alias="pendingDisambiguation")
    pending_marketing: Optional[MarketingRecommendation] = Field(None, alias="pendingMarketing")
    pending_report: Optional[dict] = Field(None, alias="pendingReport")
    last_location: Optional[MapLocation] = Field(None, alias="lastLocation")
    active_segments: list[str] = Field(default_factory=list, alias="activeSegments")

    model_config = {
        "populate_by_name": True,
        "serialize_by_alias": True,
    }
