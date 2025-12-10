# Phase 1: Foundation

<div align="center">

**Building the Infrastructure for Advanced AI Agent Capabilities**

*Target: Complete core infrastructure before adding new features*

</div>

---

## Overview

Phase 1 establishes the foundational architecture that all future features will build upon. This includes:

1. Event Stream Architecture
2. Context Engineering System
3. File-Based External Memory (Workspace)
4. Todo.md Task Tracking
5. Base Agent Classes
6. Real-Time Progress API

---

## 1.1 Event Stream Architecture

### Purpose

Create a chronological, append-only log of all agent interactions. This enables:
- Context persistence across turns
- Debugging and replay
- Foundation for real-time progress tracking

### Implementation

**File**: `app/core/event_stream.py`

```python
"""
Event Stream Architecture for MarketInsightsAI

Based on Manus AI patterns. The event stream is the "memory" of the agent,
recording all actions, observations, and decisions in chronological order.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
import json
import uuid


class EventType(str, Enum):
    """Types of events in the stream."""
    USER = "user"           # User message/request
    PLAN = "plan"           # Agent's planned approach
    ACTION = "action"       # Tool call or operation
    OBSERVATION = "observation"  # Result of action
    THOUGHT = "thought"     # Agent's reasoning
    ERROR = "error"         # Error occurred
    COMPLETE = "complete"   # Task completed


@dataclass
class Event:
    """A single event in the stream."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: EventType = EventType.USER
    content: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }

    def to_context_string(self) -> str:
        """Format for inclusion in LLM context."""
        prefix = {
            EventType.USER: "USER",
            EventType.PLAN: "PLAN",
            EventType.ACTION: "ACTION",
            EventType.OBSERVATION: "RESULT",
            EventType.THOUGHT: "THINKING",
            EventType.ERROR: "ERROR",
            EventType.COMPLETE: "DONE"
        }.get(self.type, "EVENT")

        if isinstance(self.content, dict):
            content_str = json.dumps(self.content, indent=2)
        else:
            content_str = str(self.content)

        return f"[{prefix}] {content_str}"


class EventStream:
    """
    Chronological, append-only event log.

    Key principles (from Manus):
    - Append-only: Never modify history
    - Deterministic serialization: For KV-cache hits
    - Bounded: Keep only recent events in context
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.events: List[Event] = []
        self._subscribers: List[callable] = []

    def append(self, event: Event) -> Event:
        """Add event to stream (append-only)."""
        self.events.append(event)
        # Notify subscribers (for real-time updates)
        for callback in self._subscribers:
            callback(event)
        return event

    def add_user_message(self, content: str) -> Event:
        """Add user message event."""
        return self.append(Event(type=EventType.USER, content=content))

    def add_plan(self, plan: Dict[str, Any]) -> Event:
        """Add planning event."""
        return self.append(Event(type=EventType.PLAN, content=plan))

    def add_action(self, tool: str, params: Dict[str, Any]) -> Event:
        """Add action event."""
        return self.append(Event(
            type=EventType.ACTION,
            content={"tool": tool, "params": params}
        ))

    def add_observation(
        self,
        result: Any,
        success: bool = True,
        error: Optional[str] = None
    ) -> Event:
        """Add observation event (result of action)."""
        return self.append(Event(
            type=EventType.OBSERVATION if success else EventType.ERROR,
            content=result if success else {"error": error, "partial_result": result}
        ))

    def add_thought(self, reasoning: str) -> Event:
        """Add agent's reasoning."""
        return self.append(Event(type=EventType.THOUGHT, content=reasoning))

    def add_completion(self, result: Any) -> Event:
        """Mark task as complete."""
        return self.append(Event(type=EventType.COMPLETE, content=result))

    def get_recent(self, n: int = 20) -> List[Event]:
        """Get n most recent events."""
        return self.events[-n:]

    def to_context(self, max_events: int = 20) -> str:
        """
        Serialize for LLM context.
        Uses deterministic formatting for KV-cache optimization.
        """
        recent = self.get_recent(max_events)
        lines = []
        for i, event in enumerate(recent):
            lines.append(f"[{i}] {event.to_context_string()}")
        return "\n\n".join(lines)

    def subscribe(self, callback: callable):
        """Subscribe to new events (for real-time updates)."""
        self._subscribers.append(callback)

    def to_dict(self) -> Dict:
        """Serialize entire stream."""
        return {
            "session_id": self.session_id,
            "events": [e.to_dict() for e in self.events]
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "EventStream":
        """Restore from serialized form."""
        stream = cls(session_id=data["session_id"])
        for e in data["events"]:
            event = Event(
                id=e["id"],
                type=EventType(e["type"]),
                content=e["content"],
                metadata=e.get("metadata", {}),
                timestamp=datetime.fromisoformat(e["timestamp"])
            )
            stream.events.append(event)
        return stream
```

### Database Schema (Optional)

For persistence, add to `app/db/models.py`:

```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    status = Column(String, default="active")  # active, completed, failed
    event_stream = Column(JSON)  # Serialized EventStream
    workspace_files = Column(JSON)  # File manifest
    todo_state = Column(JSON)  # Current todo.md state
```

### Tests

```python
# tests/test_event_stream.py
import pytest
from app.core.event_stream import EventStream, Event, EventType

def test_event_stream_append_only():
    stream = EventStream()
    stream.add_user_message("Analyze this location")
    stream.add_plan({"steps": ["geocode", "get_tapestry"]})

    assert len(stream.events) == 2
    assert stream.events[0].type == EventType.USER
    assert stream.events[1].type == EventType.PLAN

def test_event_stream_serialization():
    stream = EventStream()
    stream.add_user_message("Test")
    stream.add_action("geocode", {"address": "123 Main St"})

    data = stream.to_dict()
    restored = EventStream.from_dict(data)

    assert len(restored.events) == 2
    assert restored.session_id == stream.session_id

def test_context_generation():
    stream = EventStream()
    stream.add_user_message("Analyze location")
    stream.add_action("geocode", {"address": "123 Main St"})
    stream.add_observation({"lat": 40.7, "lng": -74.0})

    context = stream.to_context()
    assert "[USER]" in context
    assert "[ACTION]" in context
    assert "[RESULT]" in context
```

---

## 1.2 Context Engineering System

### Purpose

Manage LLM context efficiently using Manus techniques:
- Stable prompt prefixes (KV-cache optimization)
- Goals at end of context (attention manipulation)
- File references instead of full content

### Implementation

**File**: `app/core/context_engine.py`

```python
"""
Context Engineering for MarketInsightsAI

Implements Manus-style context management:
1. Stable system prompt prefix (KV-cache hits)
2. Workspace file manifest (external memory)
3. Recent events (bounded history)
4. Todo.md at END (attention manipulation)
"""

from typing import Dict, List, Optional
from .event_stream import EventStream
from .workspace import Workspace
from .todo_tracker import TodoTracker


# STABLE SYSTEM PROMPT - Never put dynamic content here!
SYSTEM_PROMPT = """You are an AI agent for MarketInsightsAI, a location intelligence platform.

## Your Capabilities

You help businesses understand consumer demographics and make location-based decisions using:
- Esri ArcGIS Tapestry segmentation data
- Demographic analysis
- Marketing content generation
- Report generation (PDF, presentations)

## How You Work

1. When given a task, you break it into steps
2. You execute one action at a time
3. You observe results before deciding next action
4. You track progress in your todo list
5. You deliver complete results

## Available Tools

- `geocode`: Convert address to coordinates
- `get_tapestry`: Get tapestry profile for location
- `analyze_demographics`: Analyze demographic data
- `generate_report`: Create PDF report
- `generate_image`: Create marketing images
- `search_knowledge_base`: Search uploaded documents

## Important Rules

- Always acknowledge user requests first
- Break complex tasks into clear steps
- Update your todo list as you progress
- If an action fails, try an alternative approach
- Cite sources when using external data
"""


class ContextEngine:
    """
    Builds optimized context for LLM calls.

    Structure (order matters for KV-cache):
    1. System prompt (STABLE - cached)
    2. Workspace manifest (what files exist)
    3. Recent event history
    4. Current objectives (TODO - at END for attention)
    """

    def __init__(
        self,
        event_stream: EventStream,
        workspace: Workspace,
        todo: TodoTracker
    ):
        self.event_stream = event_stream
        self.workspace = workspace
        self.todo = todo

    def build_system_prompt(self) -> str:
        """
        Build STABLE system prompt.
        Never include timestamps or session-specific data here!
        """
        return SYSTEM_PROMPT

    def build_context(
        self,
        max_events: int = 20,
        include_workspace: bool = True,
        include_todo: bool = True
    ) -> str:
        """
        Build user context (dynamic content).

        Order is intentional:
        - Workspace manifest first (reference for events)
        - Events in chronological order
        - TODO at END (recency bias / attention manipulation)
        """
        sections = []

        # 1. Workspace manifest (if files exist)
        if include_workspace:
            manifest = self.workspace.get_manifest()
            if manifest:
                sections.append(f"## Available Files\n{manifest}")

        # 2. Recent events
        events_context = self.event_stream.to_context(max_events)
        if events_context:
            sections.append(f"## Recent Activity\n{events_context}")

        # 3. TODO at the END (attention manipulation!)
        if include_todo:
            todo_md = self.todo.to_markdown()
            if todo_md:
                sections.append(todo_md)

        return "\n\n".join(sections)

    def build_messages(
        self,
        user_message: Optional[str] = None,
        max_events: int = 20
    ) -> List[Dict]:
        """
        Build messages array for OpenAI API.
        """
        messages = [
            {"role": "system", "content": self.build_system_prompt()}
        ]

        context = self.build_context(max_events)
        if context:
            messages.append({"role": "user", "content": context})
            messages.append({
                "role": "assistant",
                "content": "I understand the context. I'm ready to continue."
            })

        if user_message:
            messages.append({"role": "user", "content": user_message})

        return messages

    def estimate_tokens(self) -> int:
        """Rough token estimate for context."""
        full_context = self.build_system_prompt() + self.build_context()
        # Rough estimate: 4 chars per token
        return len(full_context) // 4
```

---

## 1.3 File-Based External Memory (Workspace)

### Purpose

Store large content (XLSX data, web pages, intermediate results) externally instead of cramming into context. Keep only file references in the LLM context.

### Implementation

**File**: `app/core/workspace.py`

```python
"""
Workspace: File-based external memory for agents.

From Manus: "The file system as the ultimate context: unlimited in size,
persistent by nature, and directly operable by the agent itself."
"""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime
import hashlib


class Workspace:
    """
    File-based external memory for agent sessions.

    Provides unlimited "context" by storing content in files
    and keeping only references in the LLM context.
    """

    def __init__(self, session_id: str, base_path: str = "/tmp/workspaces"):
        self.session_id = session_id
        self.base_path = Path(base_path) / session_id
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.files: Dict[str, Dict] = {}  # name -> metadata
        self._load_manifest()

    def _manifest_path(self) -> Path:
        return self.base_path / "_manifest.json"

    def _load_manifest(self):
        """Load existing file manifest if it exists."""
        if self._manifest_path().exists():
            with open(self._manifest_path(), 'r') as f:
                self.files = json.load(f)

    def _save_manifest(self):
        """Persist file manifest."""
        with open(self._manifest_path(), 'w') as f:
            json.dump(self.files, f, indent=2, default=str)

    def store(
        self,
        name: str,
        content: Any,
        content_type: str = "text",
        description: Optional[str] = None
    ) -> str:
        """
        Store content in workspace.

        Args:
            name: Filename (e.g., "tapestry_data.json")
            content: Content to store
            content_type: "text", "json", "binary"
            description: Human-readable description

        Returns:
            Reference string for context
        """
        file_path = self.base_path / name

        # Write content based on type
        if content_type == "json":
            with open(file_path, 'w') as f:
                json.dump(content, f, indent=2, default=str)
        elif content_type == "binary":
            with open(file_path, 'wb') as f:
                f.write(content)
        else:  # text
            with open(file_path, 'w') as f:
                f.write(str(content))

        # Calculate size and hash
        stat = file_path.stat()
        with open(file_path, 'rb') as f:
            content_hash = hashlib.md5(f.read()).hexdigest()[:8]

        # Update manifest
        self.files[name] = {
            "path": str(file_path),
            "type": content_type,
            "size": stat.st_size,
            "hash": content_hash,
            "description": description or f"Stored {content_type} file",
            "created": datetime.utcnow().isoformat()
        }
        self._save_manifest()

        return f"[Stored: {name} ({self._human_size(stat.st_size)})]"

    def retrieve(self, name: str) -> Optional[Any]:
        """Retrieve content by name."""
        if name not in self.files:
            return None

        file_path = Path(self.files[name]["path"])
        if not file_path.exists():
            return None

        content_type = self.files[name]["type"]

        if content_type == "json":
            with open(file_path, 'r') as f:
                return json.load(f)
        elif content_type == "binary":
            with open(file_path, 'rb') as f:
                return f.read()
        else:
            with open(file_path, 'r') as f:
                return f.read()

    def exists(self, name: str) -> bool:
        """Check if file exists in workspace."""
        return name in self.files

    def delete(self, name: str) -> bool:
        """Delete file from workspace."""
        if name not in self.files:
            return False

        file_path = Path(self.files[name]["path"])
        if file_path.exists():
            file_path.unlink()

        del self.files[name]
        self._save_manifest()
        return True

    def list_files(self) -> List[Dict]:
        """List all files with metadata."""
        return [
            {"name": name, **meta}
            for name, meta in self.files.items()
        ]

    def get_manifest(self) -> str:
        """
        Get file manifest formatted for LLM context.
        Compact format to minimize tokens.
        """
        if not self.files:
            return ""

        lines = ["Files in workspace:"]
        for name, meta in self.files.items():
            size = self._human_size(meta["size"])
            desc = meta.get("description", "")[:50]
            lines.append(f"  - {name} ({size}): {desc}")

        return "\n".join(lines)

    def get_path(self, name: str) -> Optional[Path]:
        """Get full path to file."""
        if name in self.files:
            return Path(self.files[name]["path"])
        return None

    def cleanup(self):
        """Remove entire workspace."""
        if self.base_path.exists():
            shutil.rmtree(self.base_path)

    @staticmethod
    def _human_size(size: int) -> str:
        """Convert bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
```

---

## 1.4 Todo.md Task Tracking

### Purpose

Implement Manus's "attention manipulation" technique. By constantly updating a todo list at the END of context, we push current objectives into the model's recent attention span.

### Implementation

**File**: `app/core/todo_tracker.py`

```python
"""
Todo.md Task Tracking for MarketInsightsAI

From Manus: "By constantly rewriting the todo list, Manus is reciting its
objectives into the end of the context. This pushes the global plan into
the model's recent attention span."

A typical task requires ~50 tool calls. Without this technique,
the model would lose track of the original goal.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """A single task in the todo list."""
    id: int
    description: str
    status: TaskStatus = TaskStatus.PENDING
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def to_markdown_line(self) -> str:
        """Format as markdown checkbox."""
        if self.status == TaskStatus.COMPLETED:
            checkbox = "[x]"
        elif self.status == TaskStatus.IN_PROGRESS:
            checkbox = "[~]"  # In progress indicator
        elif self.status == TaskStatus.FAILED:
            checkbox = "[!]"  # Failed indicator
        else:
            checkbox = "[ ]"

        line = f"{self.id}. {checkbox} {self.description}"
        if self.notes:
            line += f" ({self.notes})"
        return line


class TodoTracker:
    """
    Markdown-based task tracking with attention manipulation.

    The todo list serves multiple purposes:
    1. Keeps agent focused on goals (attention at end of context)
    2. Shows progress to users
    3. Enables task resumption if context is lost
    4. Provides structure for complex multi-step tasks
    """

    def __init__(self, title: str = "Current Objectives"):
        self.title = title
        self.tasks: List[Task] = []
        self._next_id = 1

    def add_task(self, description: str, notes: Optional[str] = None) -> Task:
        """Add a new task."""
        task = Task(
            id=self._next_id,
            description=description,
            notes=notes
        )
        self.tasks.append(task)
        self._next_id += 1
        return task

    def add_tasks(self, descriptions: List[str]) -> List[Task]:
        """Add multiple tasks at once."""
        return [self.add_task(desc) for desc in descriptions]

    def start_task(self, task_id: int) -> Optional[Task]:
        """Mark task as in progress."""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.IN_PROGRESS
        return task

    def complete_task(
        self,
        task_id: int,
        notes: Optional[str] = None
    ) -> Optional[Task]:
        """Mark task as completed."""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            if notes:
                task.notes = notes
        return task

    def fail_task(
        self,
        task_id: int,
        reason: Optional[str] = None
    ) -> Optional[Task]:
        """Mark task as failed."""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            if reason:
                task.notes = reason
        return task

    def get_current_task(self) -> Optional[Task]:
        """Get the currently in-progress task."""
        for task in self.tasks:
            if task.status == TaskStatus.IN_PROGRESS:
                return task
        return None

    def get_next_pending(self) -> Optional[Task]:
        """Get next pending task."""
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def is_complete(self) -> bool:
        """Check if all tasks are done."""
        return all(
            t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            for t in self.tasks
        )

    def get_progress(self) -> dict:
        """Get progress statistics."""
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        in_progress = sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)
        pending = total - completed - failed - in_progress

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "percent": (completed / total * 100) if total > 0 else 0
        }

    def to_markdown(self) -> str:
        """
        Generate todo.md content.
        This goes at the END of context for attention manipulation!
        """
        if not self.tasks:
            return ""

        lines = [f"# {self.title}\n"]

        for task in self.tasks:
            lines.append(task.to_markdown_line())

        # Add progress summary
        progress = self.get_progress()
        lines.append("")
        lines.append(
            f"Progress: {progress['completed']}/{progress['total']} complete "
            f"({progress['percent']:.0f}%)"
        )

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "title": self.title,
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description,
                    "status": t.status.value,
                    "notes": t.notes,
                    "created_at": t.created_at.isoformat(),
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None
                }
                for t in self.tasks
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoTracker":
        """Restore from serialized form."""
        tracker = cls(title=data.get("title", "Current Objectives"))
        for t in data.get("tasks", []):
            task = Task(
                id=t["id"],
                description=t["description"],
                status=TaskStatus(t["status"]),
                notes=t.get("notes"),
                created_at=datetime.fromisoformat(t["created_at"]),
                completed_at=datetime.fromisoformat(t["completed_at"]) if t.get("completed_at") else None
            )
            tracker.tasks.append(task)
            tracker._next_id = max(tracker._next_id, task.id + 1)
        return tracker

    def _find_task(self, task_id: int) -> Optional[Task]:
        """Find task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
```

---

## 1.5 Base Agent Classes

### Purpose

Create the foundation for multi-agent architecture. Start simple, evolve as needed.

### Implementation

**File**: `app/agents/base.py`

```python
"""
Base Agent Classes for MarketInsightsAI

Foundation for multi-agent architecture.
Start with simple structure, evolve to full Orchestrator pattern.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from enum import Enum

from app.core.event_stream import EventStream
from app.core.workspace import Workspace
from app.core.todo_tracker import TodoTracker
from app.core.context_engine import ContextEngine


class AgentRole(str, Enum):
    """Agent roles in the system."""
    ORCHESTRATOR = "orchestrator"  # Routes tasks, manages workflow
    PLANNER = "planner"           # Breaks down tasks, creates plans
    EXECUTOR = "executor"         # Executes specific actions
    VERIFIER = "verifier"         # Validates outputs
    SPECIALIST = "specialist"     # Domain-specific agent


@dataclass
class AgentTask:
    """A task for an agent to execute."""
    id: str
    type: str
    input: Dict[str, Any]
    context: Dict[str, Any]
    parent_task_id: Optional[str] = None


@dataclass
class AgentResult:
    """Result from agent execution."""
    task_id: str
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class BaseAgent(ABC):
    """
    Base class for all agents.

    Each agent has:
    - A role (what it does)
    - Access to shared context (event stream, workspace, todo)
    - Ability to execute tasks
    """

    role: AgentRole = AgentRole.EXECUTOR

    def __init__(
        self,
        event_stream: EventStream,
        workspace: Workspace,
        todo: TodoTracker
    ):
        self.event_stream = event_stream
        self.workspace = workspace
        self.todo = todo
        self.context_engine = ContextEngine(event_stream, workspace, todo)

    @abstractmethod
    async def can_handle(self, task: AgentTask) -> bool:
        """Check if this agent can handle the given task."""
        pass

    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        """Execute the task and return result."""
        pass

    def log_action(self, tool: str, params: Dict[str, Any]):
        """Log an action to event stream."""
        self.event_stream.add_action(tool, params)

    def log_observation(self, result: Any, success: bool = True, error: str = None):
        """Log observation to event stream."""
        self.event_stream.add_observation(result, success, error)

    def log_thought(self, reasoning: str):
        """Log agent's reasoning."""
        self.event_stream.add_thought(reasoning)


class SimpleAgent(BaseAgent):
    """
    Simple single-purpose agent.

    Good starting point before full multi-agent orchestration.
    """

    def __init__(
        self,
        event_stream: EventStream,
        workspace: Workspace,
        todo: TodoTracker,
        tools: Dict[str, callable]
    ):
        super().__init__(event_stream, workspace, todo)
        self.tools = tools

    async def can_handle(self, task: AgentTask) -> bool:
        """Check if we have a tool for this task type."""
        return task.type in self.tools

    async def execute(self, task: AgentTask) -> AgentResult:
        """Execute using appropriate tool."""
        if not await self.can_handle(task):
            return AgentResult(
                task_id=task.id,
                success=False,
                output=None,
                error=f"No tool for task type: {task.type}"
            )

        tool = self.tools[task.type]
        self.log_action(task.type, task.input)

        try:
            result = await tool(**task.input)
            self.log_observation(result, success=True)
            return AgentResult(
                task_id=task.id,
                success=True,
                output=result
            )
        except Exception as e:
            self.log_observation(None, success=False, error=str(e))
            return AgentResult(
                task_id=task.id,
                success=False,
                output=None,
                error=str(e)
            )
```

---

## 1.6 Integration with Existing AI Service

### Purpose

Integrate the new foundation components with the existing `ai_service.py`.

### Changes to `app/services/ai_service.py`

```python
# Add to imports
from app.core.event_stream import EventStream
from app.core.workspace import Workspace
from app.core.todo_tracker import TodoTracker
from app.core.context_engine import ContextEngine

# Add session management
class AIService:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}  # session_id -> components

    def get_or_create_session(self, session_id: str) -> Dict:
        """Get or create session components."""
        if session_id not in self.sessions:
            event_stream = EventStream(session_id)
            workspace = Workspace(session_id)
            todo = TodoTracker()

            self.sessions[session_id] = {
                "event_stream": event_stream,
                "workspace": workspace,
                "todo": todo,
                "context_engine": ContextEngine(event_stream, workspace, todo)
            }

        return self.sessions[session_id]

    async def chat_with_context(
        self,
        message: str,
        session_id: str,
        **kwargs
    ) -> str:
        """Chat with full context engineering."""
        session = self.get_or_create_session(session_id)

        # Add user message to event stream
        session["event_stream"].add_user_message(message)

        # Build context-aware messages
        messages = session["context_engine"].build_messages(message)

        # Call OpenAI
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs
        )

        result = response.choices[0].message.content

        # Log the response
        session["event_stream"].add_observation(result)

        return result
```

---

## Testing Strategy

### Unit Tests

1. `test_event_stream.py` - Event stream operations
2. `test_workspace.py` - File storage and retrieval
3. `test_todo_tracker.py` - Task tracking
4. `test_context_engine.py` - Context building

### Integration Tests

1. Test full session flow (create → interact → persist)
2. Test context building with all components
3. Test session restoration from storage

---

## Acceptance Criteria

Phase 1 is complete when:

- [ ] EventStream logs all interactions
- [ ] Workspace stores and retrieves files
- [ ] TodoTracker maintains task state
- [ ] ContextEngine builds optimized prompts
- [ ] AI service uses new context system
- [ ] All tests pass
- [ ] Documentation updated

---

## Next Steps

After Phase 1:
1. Add WebSocket for real-time progress (1.5)
2. Begin Phase 2: Slide Generation
3. Add ArcGIS Direct API integration

---

## Related Documents

- [Implementation Tracker](../IMPLEMENTATION_TRACKER.md)
- [AI Agent Patterns](../research/ai-agent-patterns.md)
- [Roadmap Overview](./README.md)
