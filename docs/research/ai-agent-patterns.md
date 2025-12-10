# AI Agent Patterns

<div align="center">

**Research Notes: Learnings from Manus AI and Industry Leaders**

*Reference material for MarketInsightsAI architecture decisions*

*Last Updated: December 9, 2024*

</div>

---

## Overview

This document captures key patterns and techniques from leading AI agent platforms, particularly Manus AI, that inform our architecture decisions for MarketInsightsAI.

## Sources

### Primary Sources (Verified Dec 9, 2024)

- [Manus Context Engineering Blog](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) - Official blog post
- [Manus Wide Research](https://manus.im/blog/introducing-wide-research) - Parallel agent feature
- [Manus Slide Generation](https://manus.im/blog/can-manus-create-slides) - PPTX workflow
- [Technical GitHub Gist](https://gist.github.com/renschni/4fbc70b31bad8dd57f3370239dccd58f) - Deep technical analysis
- [Multi-Agent Orchestration Guide](https://natesnewsletter.substack.com/p/the-complete-guide-to-ai-multi-agent)
- [arXiv: Rise of Manus AI](https://arxiv.org/html/2505.02024v1) - Academic analysis

### Research Papers

- [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) - Failure taxonomy
- [Multi-Agent Systems Security](https://arxiv.org/abs/2503.12188) - Security considerations

### ArcGIS AI Sources

- [ArcGIS Geospatial AI Platform](https://architecture.arcgis.com/en/overview/introduction-to-arcgis/geospatial-ai.html)
- [Esri AI Overview](https://www.esri.com/en-us/geospatial-artificial-intelligence/overview)

---

## 1. Multi-Agent Architecture

### Manus Pattern

Manus employs a distributed approach where a central "orchestrator" coordinates with specialized subagents:

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                              │
│  - Routes tasks to appropriate agents                        │
│  - Manages overall workflow                                  │
│  - Coordinates parallel execution                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│    PLANNER    │ │   EXECUTOR    │ │   VERIFIER    │
│  - Breaks down│ │  - Runs tools │ │  - Reviews    │
│    tasks      │ │  - API calls  │ │    outputs    │
│  - Strategizes│ │  - Code exec  │ │  - Fixes bugs │
└───────────────┘ └───────────────┘ └───────────────┘
```

### Three-Layer System

1. **Planning Layer**: Decomposes objectives into actionable steps
2. **Execution Layer**: Deploys specialized sub-agents for specific tasks
3. **Validation Layer**: Ensures output quality

### Specialized Sub-Agents (Manus)

Each subagent in Manus Wide Research is a **fully capable Manus instance**, not a limited specialist. This enables:

- Maximum flexibility (not constrained to rigid formats)
- Task not domain-dependent
- Agent-to-agent collaboration protocol

### Key Insights

| Aspect | Manus Approach | Application to MarketInsightsAI |
|--------|---------------|--------------------------------|
| **Task Distribution** | Delegate to specialized agents | Create domain-specific agents (Esri, Reports, Marketing) |
| **Parallelism** | Run independent subtasks simultaneously | Generate insights while rendering reports |
| **Error Handling** | Verifier agent catches and fixes issues | Add validation step before report delivery |
| **Flexibility** | Each agent is general-purpose | Start specialist, evolve to general |

### Implementation Blueprint

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class Task:
    id: str
    type: str
    input: Dict[str, Any]
    context: Dict[str, Any]

@dataclass
class TaskResult:
    task_id: str
    status: str  # "success" | "error" | "needs_verification"
    output: Any
    errors: List[str]

class BaseAgent(ABC):
    """Base class for all agents."""

    @abstractmethod
    async def can_handle(self, task: Task) -> bool:
        """Check if this agent can handle the task."""
        pass

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """Execute the task and return result."""
        pass

class AgentOrchestrator:
    """Coordinates specialized agents for complex tasks."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.executors: List[BaseAgent] = []
        self.verifier = VerifierAgent()

    def register_executor(self, agent: BaseAgent):
        self.executors.append(agent)

    async def process_task(self, task: Task) -> TaskResult:
        # 1. Plan the approach
        plan = await self.planner.create_plan(task)

        # 2. Execute each step
        results = []
        for step in plan.steps:
            # Find appropriate executor
            executor = self._find_executor(step)
            result = await executor.execute(step)
            results.append(result)

            # Check for errors mid-execution
            if result.status == "error":
                # Attempt recovery or re-plan
                recovery = await self.planner.recover(step, result)
                if recovery:
                    result = await executor.execute(recovery)
                    results[-1] = result

        # 3. Verify outputs
        verified = await self.verifier.validate(results)

        return verified

    def _find_executor(self, step: Task) -> BaseAgent:
        for executor in self.executors:
            if executor.can_handle(step):
                return executor
        raise ValueError(f"No executor for task type: {step.type}")
```

---

## 2. Context Engineering

### The Problem

Large Language Models have limited context windows. Even with 200K tokens, complex multi-step tasks can exceed capacity. The agent must manage what information to keep, compress, or externalize.

### The Critical Metric: KV-Cache Hit Rate

> "The KV-cache hit rate is the single most important metric for a production-stage AI agent."

| Cost | Cached | Uncached |
|------|--------|----------|
| Claude Sonnet | $0.30/MTok | $3.00/MTok |

**This is a 10x difference!**

### Manus Techniques

#### 2.1 Stable Prompt Prefixes

```python
# BAD - timestamp invalidates entire cache every request
system_prompt = f"""
Current time: {datetime.now()}
You are a location analytics assistant...
"""

# GOOD - stable prefix, dynamic content at END
system_prompt = """
You are a location analytics assistant for MarketInsightsAI.
You help businesses understand consumer demographics using Esri Tapestry data.
...
"""

# Add dynamic content in user message or at end
user_context = f"""
Current session: {session_id}
User query: {query}
"""
```

#### 2.2 File System as Extended Context

> "The file system as the ultimate context in Manus: unlimited in size, persistent by nature."

Instead of keeping all information in the context window:
- Store large observations (web pages, PDFs, XLSX data) externally
- Keep only references/paths in context
- Retrieve on-demand when needed

```python
class Workspace:
    """File-based external memory for agents."""

    def __init__(self, session_id: str):
        self.base_path = f"/tmp/workspace/{session_id}"
        os.makedirs(self.base_path, exist_ok=True)
        self.files: Dict[str, str] = {}

    def store(self, name: str, content: str) -> str:
        """Store content externally, return reference."""
        path = os.path.join(self.base_path, name)
        with open(path, 'w') as f:
            f.write(content)
        self.files[name] = path
        return f"[Stored: {name}]"

    def retrieve(self, name: str) -> str:
        """Retrieve content by name."""
        path = self.files.get(name)
        if path and os.path.exists(path):
            with open(path, 'r') as f:
                return f.read()
        return ""

    def get_manifest(self) -> str:
        """Get list of stored files for context."""
        return "\n".join([f"- {name}" for name in self.files.keys()])

# Usage in context building:
# Instead of:
context = f"Web page content: {full_page_content}"  # 50K tokens

# Do this:
workspace.store("competitor_analysis.html", full_page_content)
context = "Retrieved competitor analysis saved to competitor_analysis.html"  # 10 tokens
```

#### 2.3 Todo.md Recitation (Attention Manipulation)

Combat the "lost-in-the-middle" phenomenon:

> "By constantly rewriting the todo list, Manus is reciting its objectives into the end of the context. This pushes the global plan into the model's recent attention span."

A typical Manus task requires **~50 tool calls on average**. Without this technique, the model would lose track of the original goal.

```python
class TodoTracker:
    """Markdown-based task tracking with attention manipulation."""

    def __init__(self):
        self.tasks: List[Dict] = []

    def add_task(self, task: str):
        self.tasks.append({"task": task, "done": False})

    def complete_task(self, index: int):
        if 0 <= index < len(self.tasks):
            self.tasks[index]["done"] = True

    def to_markdown(self) -> str:
        """Generate todo.md content."""
        lines = ["# Current Objectives\n"]
        for i, t in enumerate(self.tasks):
            checkbox = "[x]" if t["done"] else "[ ]"
            lines.append(f"{i+1}. {checkbox} {t['task']}")
        return "\n".join(lines)

class ContextEngine:
    """Build context with goals at the end for recency bias."""

    def __init__(self):
        self.event_stream: List[Dict] = []
        self.workspace = Workspace()
        self.todo = TodoTracker()

    def build_context(self, max_events: int = 20) -> str:
        context = []

        # 1. System instructions (stable prefix - cached)
        context.append(self.system_prompt)

        # 2. Workspace manifest (what files are available)
        context.append(f"\n## Available Files\n{self.workspace.get_manifest()}")

        # 3. Recent events (oldest to newest)
        recent_events = self.event_stream[-max_events:]
        context.append("\n## Recent Activity")
        for event in recent_events:
            context.append(self._format_event(event))

        # 4. Current goals at the END (recency matters!)
        context.append(f"\n{self.todo.to_markdown()}")

        return "\n".join(context)
```

#### 2.4 Append-Only Context with Deterministic Ordering

For maximum KV-cache hits:

```python
class EventStream:
    """Chronological, append-only event log."""

    def __init__(self):
        self.events: List[Event] = []
        self._hash_cache: Dict[int, str] = {}

    def append(self, event: Event):
        """Only append, never modify history."""
        self.events.append(event)

    def serialize(self) -> str:
        """Deterministic serialization for cache consistency."""
        lines = []
        for i, event in enumerate(self.events):
            # Use consistent formatting
            lines.append(f"[{i}] {event.type}: {json.dumps(event.data, sort_keys=True)}")
        return "\n".join(lines)
```

#### 2.5 Preserve Failure States

> "Keep error traces and stack traces in context so models adapt rather than repeat mistakes."

Counter-intuitive but critical: **Leave failed actions in context**.

```python
async def execute_with_error_preservation(self, action: Action) -> Observation:
    try:
        result = await self.execute(action)
        return Observation(
            type="success",
            action=action,
            result=result
        )
    except Exception as e:
        # DON'T sanitize - keep full error
        return Observation(
            type="error",
            action=action,
            error=str(e),
            traceback=traceback.format_exc(),
            context=f"Attempted: {action.description}"
        )
        # Model sees this and learns to try different approach
```

#### 2.6 Action Space Management (Token Logit Masking)

Rather than dynamically removing tools (which breaks KV-cache), Manus masks token logits at decode time:

```python
class ActionController:
    """Control available actions without breaking cache."""

    def __init__(self):
        self.all_tools = [...]
        self.mode = "auto"  # auto | required | specified
        self.allowed_tools: Optional[List[str]] = None

    def get_tool_prompt(self) -> str:
        """Return stable tool list - masking happens at decode."""
        # Always include all tools in prompt (stable prefix)
        return self._format_tools(self.all_tools)

    def filter_response(self, response: str) -> str:
        """Post-process to enforce tool restrictions."""
        if self.mode == "specified" and self.allowed_tools:
            # Validate tool call is in allowed list
            tool_call = self._extract_tool(response)
            if tool_call and tool_call.name not in self.allowed_tools:
                raise InvalidToolError(f"Tool {tool_call.name} not allowed")
        return response
```

---

## 3. Tool Orchestration

### Single-Action-Per-Cycle Model

Manus "must await the result of each action before deciding the next step."

```python
class AgentLoop:
    """Core agent execution loop."""

    async def run(self, initial_task: str) -> str:
        self.event_stream.append(Event(type="user", content=initial_task))

        while not self.task_complete:
            # 1. Build context from event stream
            context = self.context_engine.build_context()

            # 2. Get next action from model
            response = await self.model.generate(context)
            action = self.parse_action(response)

            # 3. Log the action
            self.event_stream.append(Event(type="action", content=action))

            # 4. Execute action
            result = await self.execute_action(action)

            # 5. Record observation
            self.event_stream.append(Event(type="observation", content=result))

            # 6. Update todo.md
            self.update_progress(action, result)

            # 7. Check completion
            self.task_complete = self.check_completion(result)

        return self.compile_final_output()
```

### CodeAct Paradigm

Rather than fixed tool calls, the LLM generates executable Python code:

```python
# Traditional tool calling (JSON)
{"tool": "search_web", "query": "tapestry segments affluent"}

# CodeAct approach (Python)
code = """
results = tools.search_web("tapestry segments affluent")
if len(results) < 5:
    # Expand search if insufficient results
    results += tools.search_web("esri tapestry demographics affluent")

# Filter for relevance
relevant = [r for r in results if "affluent" in r.title.lower()]
return relevant[:10]
"""
```

**Benefits:**
- Flexibility: Code can combine multiple tools
- Conditional logic within single action
- Error handling in-line
- State management across steps

**Implementation Consideration**: Start with structured tool calls, evolve to CodeAct once patterns are established.

---

## 4. Agent Loop Structure

### Manus Agent Loop

```
┌─────────────────────────────────────────────────────────┐
│                    AGENT LOOP                            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌──────────────┐                                      │
│   │ 1. ANALYZE   │ ← Process user request + events      │
│   │    EVENTS    │                                      │
│   └──────┬───────┘                                      │
│          ▼                                              │
│   ┌──────────────┐                                      │
│   │ 2. SELECT    │ ← Choose tool based on plan          │
│   │    TOOLS     │                                      │
│   └──────┬───────┘                                      │
│          ▼                                              │
│   ┌──────────────┐                                      │
│   │ 3. EXECUTE   │ ← Run in sandbox environment         │
│   │    COMMAND   │                                      │
│   └──────┬───────┘                                      │
│          ▼                                              │
│   ┌──────────────┐                                      │
│   │ 4. ITERATE   │ ← Refine based on results            │
│   │              │                                      │
│   └──────┬───────┘                                      │
│          ▼                                              │
│   ┌──────────────┐                                      │
│   │ 5. SUBMIT    │ ← Deliver final output               │
│   │    RESULTS   │                                      │
│   └──────┬───────┘                                      │
│          ▼                                              │
│   ┌──────────────┐                                      │
│   │ 6. STANDBY   │ ← Await new tasks                    │
│   │              │                                      │
│   └──────────────┘                                      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Execution Environment

### Manus Sandbox

- Cloud-based Ubuntu Linux containers
- gVisor security isolation
- Python/Node.js interpreters
- Browser automation (Playwright)
- File system access
- Network access (controlled)
- **Continues running even when user disconnects**

### Application to MarketInsightsAI

For our use case, we need:

| Capability | Manus | MarketInsightsAI (Phase 1) | Future |
|------------|-------|---------------------------|--------|
| Code Execution | Full Python sandbox | No (structured tools only) | Limited sandbox |
| Browser | Full automation | No (API-first approach) | Consider later |
| File System | Full access | Report generation workspace | Expand as needed |
| Network | Web scraping | API calls only (ArcGIS, OpenAI) | Add web search |

---

## 6. UI/UX Patterns

### Manus Three-Panel Interface

```
┌─────────────────┬──────────────────────┬──────────────────────┐
│   LEFT RAIL     │    MAIN PANEL        │  MANUS'S COMPUTER    │
│                 │                      │                      │
│  Task History   │  Chat Interface      │  Real-time view of   │
│  • Task 1       │  (like ChatGPT)      │  agent's screen      │
│  • Task 2       │                      │  • Browser actions   │
│  • Task 3       │  User: "Analyze..."  │  • Terminal commands │
│                 │  Agent: "I'll..."    │  • File operations   │
│  New Task (+)   │                      │  • Screenshot trail  │
└─────────────────┴──────────────────────┴──────────────────────┘
```

### Key UX Elements

1. **Real-Time Progress Tracking**
   - Visible task lists with checkbox status
   - Screenshot timeline of each action
   - Smooth output effects

2. **Session Replay**
   - Watch how AI completed past tasks
   - Useful for debugging and learning
   - Timeline scrubbing

3. **File Management Interface**
   - View generated outputs (PDFs, PPTX, images)
   - Download/export options
   - Organized by task

4. **Mobile Progress Monitoring**
   - Push notifications on completion
   - Check progress while away

### Todo.md UI Pattern

```markdown
# Current Objectives

1. [x] Parse uploaded XLSX file
2. [x] Extract tapestry segments for all stores
3. [ ] Generate demographic insights
4. [ ] Create visualization charts
5. [ ] Compile final PDF report

## Progress: 2/5 complete
```

---

## 7. Slide Generation Workflow

### Manus 3-Step Process

```
INPUT              ─────▶  AI PROCESSING  ─────▶  OUTPUT
Topic/document            • Multi-agent           Complete PPTX
Upload PDF/email          • Web research          • Editable slides
Simple prompt             • Content generation    • Professional design
                          • Layout design         • Generated images
                          • Image creation        • Charts from data
                          • 2-5 minutes           • Export formats
```

### Key Features

1. **Research-Backed**: Actually researches topic during generation
2. **Multi-Agent Collaboration**: One agent researches, another designs, another generates images
3. **Image Integration**: DALL-E 3, stock photos, charts generated automatically
4. **Export Formats**: PPTX, Google Slides, PDF, PNG

### Application to MarketInsightsAI

```python
async def generate_location_presentation(
    locations: List[str],
    purpose: str,  # "investor_pitch" | "franchise_pitch" | "quarterly_review"
    include_research: bool = True
) -> bytes:
    """Generate PPTX for location analysis."""

    # 1. Plan presentation structure
    structure = await planner.plan_presentation(purpose, len(locations))

    # 2. Gather data (parallel)
    tasks = [
        research_agent.gather_market_data(loc) for loc in locations
    ] + [
        tapestry_agent.analyze_demographics(loc) for loc in locations
    ]
    results = await asyncio.gather(*tasks)

    # 3. Generate content for each slide
    slides = []
    for slide_spec in structure.slides:
        content = await content_agent.generate_slide(slide_spec, results)
        slides.append(content)

    # 4. Generate visualizations
    charts = await visualization_agent.create_charts(results)

    # 5. Compile PPTX
    pptx = await slides_agent.compile(slides, charts)

    return pptx
```

---

## 8. Wide Research (Parallel Agents)

### Concept

Spin up 100+ parallel agents to tackle large-scale research tasks simultaneously.

### Key Insight

> "The key to Wide Research isn't just having more agents — it's how they collaborate."

Each subagent is a **fully capable instance**, not a limited specialist.

### Use Cases

- Analyzing Fortune 500 companies
- Comparing MBA programs
- Evaluating 50 potential store locations

### Application to MarketInsightsAI

```python
async def wide_location_analysis(
    locations: List[str],  # Could be 50+ locations
    analysis_depth: str = "standard"
) -> LocationComparisonReport:
    """Parallel analysis of multiple locations."""

    # Spin up parallel workers
    async def analyze_single(location: str) -> LocationAnalysis:
        return await tapestry_agent.full_analysis(location)

    # Execute in parallel with concurrency limit
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent

    async def bounded_analyze(loc: str):
        async with semaphore:
            return await analyze_single(loc)

    results = await asyncio.gather(*[
        bounded_analyze(loc) for loc in locations
    ])

    # Aggregate and rank
    report = await aggregator.compile_comparison(results)

    return report
```

---

## 9. Benchmarks & Performance

### Manus GAIA Results

| Level | Manus | OpenAI Deep Research | Improvement |
|-------|-------|---------------------|-------------|
| Level 1 (basic) | 86.5% | 74.3% | +16% |
| Level 2 (intermediate) | 70.1% | 69.1% | +1% |
| Level 3 (complex) | 57.7% | 47.6% | +21% |

### Known Limitations

- Complex tasks: 15-20 minutes execution time
- Single model dependency (Claude primarily)
- Occasional task failures requiring restarts
- Context overflow on extremely large operations

---

## 10. Multi-Agent Failure Modes

From research paper [arXiv:2503.13657](https://arxiv.org/abs/2503.13657):

### 14 Failure Modes in 3 Categories

1. **System Design Issues**
   - Improper task decomposition
   - Tool selection errors
   - Context window overflow

2. **Inter-Agent Misalignment**
   - Communication breakdowns
   - Conflicting objectives
   - State synchronization failures

3. **Task Verification**
   - Incomplete validation
   - False positives
   - Missing edge cases

### Mitigation Strategies

1. **Clear agent boundaries**: Each agent has well-defined responsibilities
2. **Structured communication**: Standard message formats between agents
3. **Verification at each step**: Don't wait until end to validate
4. **Fallback mechanisms**: Graceful degradation on failures

---

## 11. Security Considerations

From research paper [arXiv:2503.12188](https://arxiv.org/abs/2503.12188):

### Vulnerabilities

- Adversarial content can hijack control
- 58-90% attack success rate on GPT-4o
- Orchestration layer is a security weakness

### Mitigations for MarketInsightsAI

1. **Input validation**: Sanitize all user inputs
2. **Tool restrictions**: Whitelist allowed operations
3. **Sandboxing**: Isolate code execution (if/when added)
4. **Output filtering**: Validate before returning to user
5. **Rate limiting**: Prevent abuse

---

## 12. ArcGIS AI Opportunity

### Current Esri Direction

Esri is building toward autonomous GIS agents:

1. **GeoAI**: ML/DL integrated with spatial analysis
2. **AI Assistants**: Natural language interfaces
3. **AI Agents**: Orchestrate complex geospatial workflows
4. **AI Framework**: Modular, extensible foundation

### Future Trends

- Autonomous agents that plan and execute complete spatial projects
- Multi-modal capabilities (text, imagery, spatial data)
- Natural language → spatial analysis

### MarketInsightsAI Unique Position

We can be the **vertical-specific AI agent for location intelligence**:

- Deep ArcGIS/Tapestry integration (our moat)
- Domain expertise in retail/franchise location decisions
- Autonomous demographic analysis
- Marketing content generation with location context

---

## 13. Key Takeaways for MarketInsightsAI

### Must Implement (Phase 1)

| Technique | Priority | Complexity | Impact |
|-----------|----------|------------|--------|
| Event Stream Architecture | P1 | Medium | Foundation for everything |
| Context Engineering (KV-cache) | P1 | Low | 10x cost reduction |
| File-Based External Memory | P1 | Low | Unlimited context |
| Todo.md Recitation | P1 | Low | Better task completion |
| Error Preservation | P1 | Low | In-session learning |

### Should Implement (Phase 2)

| Technique | Priority | Complexity | Impact |
|-----------|----------|------------|--------|
| Multi-Agent Orchestration | P2 | High | Complex task handling |
| Slide Generation | P1 | Medium | High user value |
| ArcGIS Direct API | P1 | Medium | Real-time capabilities |
| Background Tasks | P2 | Medium | Better UX |

### Consider Later (Phase 3+)

| Technique | Priority | Complexity | Impact |
|-----------|----------|------------|--------|
| Wide Research (Parallel) | P3 | High | Scale capability |
| CodeAct (Code Execution) | P3 | High | Flexibility |
| Transparency UI | P2 | Medium | Trust building |
| Multi-Model Support | P3 | Medium | Resilience |

---

## Related Documents

- [Implementation Tracker](../IMPLEMENTATION_TRACKER.md) - Master progress document
- [Architecture Overview](../architecture/README.md)
- [Feature Roadmap](../roadmap/README.md)
- [Phase 1: Foundation](../roadmap/phase-1-foundation.md)

---

## Changelog

| Date | Changes |
|------|---------|
| Dec 9, 2024 | Major update with comprehensive Manus research |
| Dec 2024 | Initial creation |
