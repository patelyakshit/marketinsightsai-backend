# System Architecture

<div align="center">

**MarketInsightsAI Architecture Overview**

</div>

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MARKETINSIGHTSAI                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         FRONTEND (React 19)                          │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ AI Chat  │ │ Reports  │ │Marketing │ │   Map    │ │   KB     │  │   │
│  │  │   Page   │ │  Page    │ │  Studio  │ │  View    │ │ Manager  │  │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │   │
│  │       │            │            │            │            │         │   │
│  │       └────────────┴────────────┴────────────┴────────────┘         │   │
│  │                              │                                       │   │
│  │                     TanStack Query + API Client                      │   │
│  └─────────────────────────────┬───────────────────────────────────────┘   │
│                                │                                            │
│  ┌─────────────────────────────┴───────────────────────────────────────┐   │
│  │                         BACKEND (FastAPI)                            │   │
│  │                                                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │                     API ROUTERS                              │    │   │
│  │  │  /api/chat   /api/reports   /api/kb   /api/auth   /api/folders  │   │
│  │  └─────────────────────────┬───────────────────────────────────┘    │   │
│  │                            │                                         │   │
│  │  ┌─────────────────────────┴───────────────────────────────────┐    │   │
│  │  │                     SERVICES LAYER                           │    │   │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │    │   │
│  │  │  │   AI     │ │ Tapestry │ │   KB     │ │    Esri      │    │    │   │
│  │  │  │ Service  │ │ Service  │ │ Service  │ │   Service    │    │    │   │
│  │  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘    │    │   │
│  │  └───────┼────────────┼───────────┼───────────────┼────────────┘    │   │
│  │          │            │           │               │                  │   │
│  └──────────┼────────────┼───────────┼───────────────┼──────────────────┘   │
│             │            │           │               │                      │
│  ┌──────────┴────────────┴───────────┴───────────────┴──────────────────┐   │
│  │                       EXTERNAL SERVICES                               │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────────┐  │   │
│  │  │ OpenAI   │ │  Google  │ │PostgreSQL│ │        ArcGIS          │  │   │
│  │  │ GPT-4o   │ │  Gemini  │ │+pgvector │ │ Geocoding/GeoEnrich    │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Design Principles

### 1. Domain-Driven Design

The system is organized around core business domains:

| Domain | Responsibility | Key Components |
|--------|---------------|----------------|
| **Chat** | AI conversation management | ai_service, chat router |
| **Reports** | Tapestry report generation | tapestry_service, reports router |
| **Knowledge** | Document management & search | kb_service, embeddings |
| **Location** | Geospatial operations | esri_service, ArcGIS integration |

### 2. Service Layer Pattern

All business logic is encapsulated in service modules:

```python
# backend/app/services/
├── ai_service.py        # Chat, marketing, insights generation
├── tapestry_service.py  # Report generation, XLSX parsing
├── kb_service.py        # Knowledge base operations
├── esri_service.py      # ArcGIS integration, geocoding
└── auth_service.py      # Authentication logic
```

### 3. Async-First Architecture

- All database operations use `async/await`
- External API calls are non-blocking
- FastAPI's async capabilities fully utilized

## Data Flow

### Chat with File Upload

```
User → Frontend → /api/chat/with-file → ai_service
                                           ├── detect_report_request()
                                           ├── detect_marketing_request()
                                           ├── detect_map_command()
                                           └── get_chat_response()
                                                  ├── search_documents() [KB]
                                                  ├── get_segment_context() [Esri]
                                                  └── OpenAI API
```

### Report Generation

```
User selects store → /api/chat/with-file (action=generate_report)
                          │
                          ▼
                   tapestry_service.generate_tapestry_report()
                          │
                          ├── get_segment_profiles() [from Esri data]
                          ├── generate_business_insights() [OpenAI]
                          ├── render HTML template [Jinja2]
                          └── convert to PDF [WeasyPrint or Playwright]
                          │
                          ▼
                   Return report URL → Frontend displays in preview
```

## Technology Decisions

### Frontend Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19 | UI framework with latest features |
| TypeScript | 5.9 | Type safety and developer experience |
| Vite | 7 | Fast builds and HMR |
| Tailwind CSS | 4 | Utility-first styling |
| TanStack Query | 5 | Server state management |
| ArcGIS Maps SDK | 4.34 | Enterprise mapping |

### Backend Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.12+ | Modern Python with async |
| FastAPI | 0.115 | High-performance API |
| Pydantic | 2.x | Data validation |
| SQLAlchemy | 2.x | Async ORM |
| pgvector | - | Vector similarity search |

### AI Services

| Service | Model | Purpose |
|---------|-------|---------|
| OpenAI | GPT-4o | Chat, analysis, insights |
| OpenAI | text-embedding-3-small | Document embeddings |
| Google Gemini | Imagen 3 | Marketing image generation |
| Esri | GeoEnrichment | Tapestry demographics |

## Security Architecture

### Authentication Flow

```
Google OAuth → Frontend → /api/auth/google → JWT tokens
                                                 │
                              ┌──────────────────┴──────────────────┐
                              │                                      │
                         Access Token                          Refresh Token
                         (30 min TTL)                          (7 day TTL)
                              │                                      │
                              └──────────────────┬──────────────────┘
                                                 │
                                       Protected API routes
```

### Data Protection

- JWT tokens for session management
- CORS configured for specific origins
- Environment-based secrets management
- Database connection pooling

## Scalability Considerations

### Current Architecture (Monolith)

- Single FastAPI application
- In-memory session state
- Stateless API design

### Future Architecture (Planned)

See [Multi-Agent Architecture](./multi-agent.md) for planned improvements:

- Separate agent processes
- Redis for session state
- Background task queue (Celery)
- Event-driven communication

## Related Documents

- [Implementation Tracker](../IMPLEMENTATION_TRACKER.md) - Master progress document
- [AI Agent Patterns](../research/ai-agent-patterns.md) - Research on agent architecture
- [Feature Roadmap](../roadmap/README.md) - Development phases
