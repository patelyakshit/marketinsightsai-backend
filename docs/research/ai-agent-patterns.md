# AI Agent Patterns

<div align="center">

**Research Notes: Learnings from Manus AI and Industry Leaders**

*Reference material for MarketInsightsAI architecture decisions*

</div>

---

## Overview

This document captures key patterns and techniques from leading AI agent platforms, particularly Manus AI, that inform our architecture decisions for MarketInsightsAI.

## Sources

- [Manus AI Technical Deep Dive - Dev.to](https://dev.to/sayed_ali_alkamel/manus-ai-a-technical-deep-dive-into-chinas-first-autonomous-ai-agent-30d3)
- [Context Engineering for AI Agents - Manus Blog](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Manus AI Overview - AI Stack](https://ai-stack.ai/en/manusai)
- [Inside Manus AI Architecture - LinkedIn](https://www.linkedin.com/pulse/edition-9-inside-manus-ai-architecture-benchmarks-futureagi-vd7ee)
- [Technical Investigation - GitHub Gist](https://gist.github.com/renschni/4fbc70b31bad8dd57f3370239dccd58f)

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

### Key Insights

| Aspect | Manus Approach | Application to MarketInsightsAI |
|--------|---------------|--------------------------------|
| **Task Distribution** | Delegate to specialized agents | Create domain-specific agents (Esri, Reports, Marketing) |
| **Parallelism** | Run independent subtasks simultaneously | Generate insights while rendering reports |
| **Error Handling** | Verifier agent catches and fixes issues | Add validation step before report delivery |

### Implementation Considerations

```python
class AgentOrchestrator:
    """Coordinates specialized agents for complex tasks."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.verifier = VerifierAgent()

    async def process_task(self, task: Task) -> Result:
        # 1. Plan the approach
        plan = await self.planner.create_plan(task)

        # 2. Execute each step
        results = []
        for step in plan.steps:
            result = await self.executor.execute(step)
            results.append(result)

        # 3. Verify outputs
        verified = await self.verifier.validate(results)

        return verified
```

---

## 2. Context Engineering

### The Problem

Large Language Models have limited context windows. Even with 200K tokens, complex multi-step tasks can exceed capacity. The agent must manage what information to keep, compress, or externalize.

### Manus Techniques

#### 2.1 File System as Extended Context

> "The file system as the ultimate context in Manus: unlimited in size, persistent by nature."

Instead of keeping all information in the context window:
- Store large observations (web pages, PDFs) externally
- Keep only references/paths in context
- Retrieve on-demand when needed

```python
# Instead of:
context = f"Web page content: {full_page_content}"  # 50K tokens

# Do this:
workspace["web_page_001.html"] = full_page_content
context = "Retrieved web page saved to web_page_001.html"  # 10 tokens
```

#### 2.2 Todo.md Recitation

Combat the "lost-in-the-middle" phenomenon:

> "By constantly rewriting the todo list, Manus is reciting its objectives into the end of the context. This pushes the global plan into the model's recent attention span."

```python
def build_context(self) -> str:
    """Build context with goals at the end for recency bias."""
    context = []

    # Historical events (oldest first)
    for event in self.event_stream[-20:]:  # Keep recent events
        context.append(format_event(event))

    # Current goals at the END (recency matters!)
    context.append(f"\n## Current Objectives\n{self.todo_md}")

    return "\n".join(context)
```

#### 2.3 KV-Cache Optimization

Critical metric: **KV-cache hit rate**

| Cost | Cached | Uncached |
|------|--------|----------|
| Claude Sonnet | $0.30/MTok | $3.00/MTok |

**Key practices:**
- Keep prompt prefixes stable (no timestamps)
- Make context append-only
- Use deterministic serialization
- Consistent tool name prefixes (`browser_`, `shell_`, `esri_`)

```python
# BAD - timestamp invalidates cache
system_prompt = f"Current time: {datetime.now()}. You are..."

# GOOD - stable prefix
system_prompt = "You are a location analytics assistant..."
# Add dynamic content at the END
```

#### 2.4 Preserve Failure States

> "Keep error traces and stack traces in context so models adapt rather than repeat mistakes."

```python
event_stream.append({
    "type": "observation",
    "status": "error",
    "error": str(e),
    "traceback": traceback.format_exc(),
    "context": "Attempted to call GeoEnrichment API"
})
# Model learns to try alternative approach
```

---

## 3. Tool Orchestration

### Single-Action-Per-Cycle Model

Manus "must await the result of each action before deciding the next step."

```python
while not task_complete:
    # 1. Analyze current state
    context = format_context(event_stream, workspace)

    # 2. Decide next action
    response = await model(context)
    action = extract_action(response)

    # 3. Execute action
    result = await execute_action(action)

    # 4. Record observation
    event_stream.append({
        "type": "observation",
        "action": action,
        "result": result
    })

    # 5. Check completion
    task_complete = check_completion(result)
```

### CodeAct Paradigm

Rather than fixed tool calls, the LLM generates executable Python code:

```python
# Traditional tool calling
{"tool": "search_web", "query": "tapestry segments"}

# CodeAct approach
code = """
results = agent_tools.search_web("tapestry segments")
if len(results) < 5:
    results += agent_tools.search_web("esri tapestry demographics")
return results
"""
```

**Benefits:**
- Flexibility: Code can combine multiple tools
- Conditional logic within single action
- Error handling in-line

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

- gVisor-secured Linux containers
- Python/Node.js interpreters
- Browser automation (Playwright)
- File system access
- Network access (controlled)

### Application to MarketInsightsAI

For our use case, we need:

| Capability | Manus | MarketInsightsAI |
|------------|-------|------------------|
| Code Execution | Full Python | Limited (data analysis only) |
| Browser | Full automation | Not needed (API-first) |
| File System | Full access | Report generation only |
| Network | Web scraping | API calls only |

---

## 6. Benchmarks & Performance

### Manus GAIA Results

| Level | Manus | OpenAI Deep Research | Improvement |
|-------|-------|---------------------|-------------|
| Level 1 | 86.5% | 74.3% | +16% |
| Level 3 | 57.7% | 47.6% | +21% |

### Known Limitations

- Complex tasks: 15-20 minutes execution time
- Single model dependency (Claude only)
- Occasional task failures requiring restarts
- Context overflow on large-scale operations

---

## 7. Key Takeaways for MarketInsightsAI

### Must Implement

1. **Context Engineering** - File-based context extension, goal recitation
2. **Event Stream** - Chronological logging of all actions
3. **Error Preservation** - Keep failures in context for learning
4. **Cache Optimization** - Stable prefixes, append-only context

### Should Implement

1. **Multi-Agent** - Separate planner, executor, verifier
2. **Tool Orchestration** - Dynamic tool selection
3. **Background Execution** - Async task queue

### Consider Later

1. **Full Code Execution** - Sandbox environment
2. **Browser Automation** - Web scraping capabilities
3. **Multi-Model Support** - Fallback providers

---

## Related Documents

- [Architecture Overview](../architecture/README.md)
- [Context Engineering Implementation](./context-engineering.md)
- [Feature Roadmap](../roadmap/README.md)
