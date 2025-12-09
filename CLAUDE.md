# MarketInsightsAI Backend - CLAUDE.md

You are Claude Code working inside the **MarketInsightsAI Backend** repository.

This is the **FastAPI + Python backend** for MarketInsightsAI. The frontend is in a separate repository.

---

## 1. Project Overview

### What is this?

This is the backend API for **MarketInsightsAI** - an autonomous AI agent platform for location intelligence. It provides:

- AI chat with OpenAI GPT-4o
- Tapestry report generation (PDF)
- Marketing content generation with image creation
- Knowledge base with vector search
- ArcGIS integration for geocoding and demographics
- Google OAuth authentication

### Related Repositories

| Repo | Purpose | URL |
|------|---------|-----|
| **This Repo** | Backend (FastAPI) | marketinsightsai-backend |
| **Frontend** | UI (React) | [marketinsightsai-frontend](https://github.com/patelyakshit/marketinsightsai-frontend) |

### Deployment

- **Backend**: Render (https://marketinsightsai-api.onrender.com)
- **Frontend**: Vercel (https://marketinsightsai.vercel.app)

---

## 2. Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.12+ | Runtime |
| FastAPI | 0.115 | API framework |
| Pydantic | 2.x | Data validation |
| SQLAlchemy | 2.x | Async ORM |
| PostgreSQL | 16+ | Database |
| pgvector | - | Vector search |
| OpenAI | GPT-4o | Chat & embeddings |
| Google Gemini | Imagen 3 | Image generation |
| WeasyPrint | - | PDF generation |

---

## 3. Project Structure

```
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings and configuration
│   ├── api/                    # API routers
│   │   ├── __init__.py
│   │   ├── chat.py             # AI chat endpoints
│   │   ├── reports.py          # Report generation
│   │   ├── kb.py               # Knowledge base
│   │   ├── auth.py             # Authentication
│   │   └── folders.py          # Folder management
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── ai_service.py       # AI chat, marketing, insights
│   │   ├── tapestry_service.py # Report generation
│   │   ├── kb_service.py       # Knowledge base operations
│   │   ├── esri_service.py     # ArcGIS integration
│   │   └── auth_service.py     # Authentication logic
│   ├── db/                     # Database
│   │   ├── __init__.py
│   │   ├── database.py         # Connection and session
│   │   └── models.py           # SQLAlchemy models
│   └── models/                 # Pydantic schemas
│       ├── __init__.py
│       └── schemas.py          # Request/response models
├── docs/                       # Documentation
│   ├── architecture/           # System architecture
│   ├── api/                    # API reference
│   ├── guides/                 # Development guides
│   ├── roadmap/                # Feature roadmap
│   └── research/               # AI agent research notes
├── templates/                  # Jinja2 templates
│   └── reports/
│       └── tapestry/           # Report HTML templates
├── reports/                    # Generated reports output
├── data/                       # Data files (XLSX, images)
├── static/                     # Static files
├── requirements.txt
├── Dockerfile
├── .env.example
└── .env                        # Local config (not committed)
```

---

## 4. Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload

# Run on specific port
uvicorn app.main:app --reload --port 8000
```

---

## 5. Key Files

| Purpose | File |
|---------|------|
| App entry | `app/main.py` |
| Settings | `app/config.py` |
| AI logic | `app/services/ai_service.py` |
| Reports | `app/services/tapestry_service.py` |
| ArcGIS | `app/services/esri_service.py` |
| KB | `app/services/kb_service.py` |
| Chat API | `app/api/chat.py` |
| Reports API | `app/api/reports.py` |
| DB models | `app/db/models.py` |
| Pydantic schemas | `app/models/schemas.py` |

---

## 6. API Endpoints

### Chat

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Basic chat |
| `/api/chat/with-file` | POST | Chat with file upload, report gen |
| `/api/chat/image` | POST | Generate image |
| `/api/chat/stores` | GET | Get uploaded stores |

### Reports

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/tapestry/upload` | POST | Upload XLSX |
| `/api/reports/tapestry/generate` | POST | Generate PDF |
| `/api/reports/{filename}` | GET | Download report |
| `/api/reports/generated_images/{filename}` | GET | Get generated image |

### Knowledge Base

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/kb/documents` | GET | List documents |
| `/api/kb/upload` | POST | Upload document |
| `/api/kb/documents/{id}` | DELETE | Delete document |
| `/api/kb/search` | GET | Semantic search |

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/google` | POST | Google OAuth login |
| `/api/auth/refresh` | POST | Refresh tokens |
| `/api/auth/me` | GET | Get current user |

### Folders

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/folders` | GET | List folders |
| `/api/folders` | POST | Create folder |
| `/api/folders/{id}` | DELETE | Delete folder |
| `/api/folders/{id}/files` | POST | Upload file to folder |

---

## 7. Services Architecture

### ai_service.py

Main AI logic including:

```python
# Key functions
get_chat_response()           # Chat with KB context
generate_image()              # Gemini image gen
generate_marketing_image()    # Marketing post images
generate_business_insights()  # Report insights
detect_report_request()       # Parse report commands
detect_marketing_request()    # Parse marketing commands
detect_map_command()          # Parse map navigation
```

### tapestry_service.py

Report generation:

```python
parse_tapestry_xlsx()         # Parse Esri XLSX
generate_tapestry_report()    # Single store PDF
generate_multi_store_report() # Multi-store PDF
```

### esri_service.py

ArcGIS integration:

```python
geocode_location()            # Address to coordinates
get_segment_profile()         # Get segment details
get_segment_context_for_ai()  # Format for AI context
search_segments_by_name()     # Search segments
```

### kb_service.py

Knowledge base:

```python
search_documents()            # Vector search
add_document()                # Add with embedding
delete_document()             # Remove document
```

---

## 8. Database

### PostgreSQL + pgvector

```python
# Connection (async)
from app.db.database import get_db

async def my_endpoint(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
```

### Models (app/db/models.py)

- `User` - User accounts
- `Document` - KB documents with embeddings
- `Folder` - User folders
- `FolderFile` - Files in folders

---

## 9. Environment Variables

```bash
# Application
APP_NAME=MarketInsightsAI
DEBUG=false
CORS_ORIGINS=http://localhost:5173,https://marketinsightsai.vercel.app

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# Authentication
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Google
GOOGLE_API_KEY=...
GOOGLE_CLIENT_ID=...
GEMINI_IMAGE_MODEL=imagen-3.0-generate-002

# Esri ArcGIS
ARCGIS_DATA_API_KEY=...
ARCGIS_LOCATION_API_KEY=...

# Reports
REPORTS_OUTPUT_PATH=./reports
```

---

## 10. Development Guidelines

### Code Style

- Type hints on all functions
- Async/await for I/O operations
- Pydantic for data validation
- Domain-based module organization

### Adding a New Endpoint

1. Create/update router in `app/api/`
2. Add business logic in `app/services/`
3. Define Pydantic models in `app/models/schemas.py`
4. Register router in `app/main.py`

```python
# app/api/new_feature.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/something")
async def get_something():
    return {"data": "value"}

# app/main.py
from app.api import new_feature
app.include_router(new_feature.router, prefix="/api/new", tags=["New"])
```

### Adding a New Service

```python
# app/services/new_service.py
async def do_something(data: dict) -> dict:
    # Business logic here
    return {"result": "success"}
```

---

## 11. Coordination with Frontend

When making API changes:

1. Update Pydantic schemas in `app/models/schemas.py`
2. Notify frontend team to update types in `src/shared/types/index.ts`
3. Document changes in `docs/api/README.md`

### Field Naming

- Backend: `snake_case` (Python convention)
- API Response: `snake_case` (Pydantic default)
- Frontend: `camelCase` (JavaScript convention)

Frontend handles the transformation.

---

## 12. Documentation

All docs are in the `docs/` folder:

- `docs/architecture/README.md` - System design
- `docs/api/README.md` - API reference
- `docs/guides/development.md` - Dev setup
- `docs/roadmap/README.md` - Feature roadmap
- `docs/research/ai-agent-patterns.md` - Manus AI research

---

## 13. Roadmap

### Phase 1: Foundation (Planned)
- Multi-Agent Architecture
- Context Engineering
- Event Stream System

### Phase 2: Capabilities (Planned)
- Slide Generation (PowerPoint)
- ArcGIS Direct API
- Research Agent
- Background Tasks

### Phase 3: Advanced (Planned)
- Transparency UI
- One-Click Deploy
- Multi-Model Support

See `docs/roadmap/README.md` for details.

---

## 14. Quick Reference

### Common Tasks

| Task | Location |
|------|----------|
| Add endpoint | `app/api/` + `main.py` |
| Add service | `app/services/` |
| Add DB model | `app/db/models.py` |
| Add schema | `app/models/schemas.py` |
| Update docs | `docs/` |

### Debugging

```python
# Add logging
import logging
logging.info("Debug message")

# Print to console
print(f"Debug: {variable}")

# Check request
from fastapi import Request
@router.post("/test")
async def test(request: Request):
    body = await request.json()
    print(body)
```

---

*Last updated: December 2024*
