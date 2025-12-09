# MarketInsightsAI Backend

<div align="center">

**FastAPI backend for MarketInsightsAI**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1?logo=postgresql)](https://www.postgresql.org/)

[Frontend Repo](https://github.com/patelyakshit/marketinsightsai-frontend) | [API Docs](./docs/api/README.md) | [Architecture](./docs/architecture/README.md)

</div>

---

## Overview

Backend API for MarketInsightsAI - an autonomous AI agent platform for location intelligence. Provides AI chat, tapestry report generation, knowledge base management, and ArcGIS integration.

## Features

- **AI Chat** - OpenAI-powered chat with knowledge base RAG
- **Tapestry Reports** - Generate PDF reports from Esri data
- **Marketing Studio** - AI-generated social media content with images
- **Knowledge Base** - Document storage with vector search
- **ArcGIS Integration** - Geocoding and GeoEnrichment
- **Authentication** - Google OAuth with JWT tokens

## Tech Stack

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

## Quick Start

### Prerequisites
- Python >= 3.12
- PostgreSQL >= 16 with pgvector extension

### Installation

```bash
# Clone the repo
git clone https://github.com/patelyakshit/marketinsightsai-backend.git
cd marketinsightsai-backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and database URL

# Start the server
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000

### API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app entry
│   ├── config.py             # Settings
│   ├── api/                  # API routers
│   │   ├── chat.py           # Chat endpoints
│   │   ├── reports.py        # Report generation
│   │   ├── kb.py             # Knowledge base
│   │   ├── auth.py           # Authentication
│   │   └── folders.py        # Folder management
│   ├── services/             # Business logic
│   │   ├── ai_service.py     # AI chat & generation
│   │   ├── tapestry_service.py  # Reports
│   │   ├── kb_service.py     # Knowledge base
│   │   ├── esri_service.py   # ArcGIS integration
│   │   └── auth_service.py   # Auth logic
│   ├── db/                   # Database
│   │   ├── database.py       # Connection
│   │   └── models.py         # SQLAlchemy models
│   └── models/               # Pydantic schemas
│       └── schemas.py
├── docs/                     # Documentation
│   ├── architecture/         # System design
│   ├── api/                  # API reference
│   ├── guides/               # Guides
│   ├── roadmap/              # Feature roadmap
│   └── research/             # Research notes
├── templates/                # Jinja2 templates
│   └── reports/              # Report templates
├── reports/                  # Generated reports
├── data/                     # Data files
├── static/                   # Static files
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Environment Variables

```bash
# Application
APP_NAME=MarketInsightsAI
DEBUG=false
CORS_ORIGINS=http://localhost:5173

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/marketinsights

# Authentication
JWT_SECRET=your-secret-key

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# Google
GOOGLE_API_KEY=...
GOOGLE_CLIENT_ID=...

# Esri ArcGIS
ARCGIS_DATA_API_KEY=...
ARCGIS_LOCATION_API_KEY=...
```

## API Endpoints

### Chat
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Basic chat |
| `/api/chat/with-file` | POST | Chat with file upload |
| `/api/chat/image` | POST | Generate image |
| `/api/chat/stores` | GET | Get uploaded stores |

### Reports
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/tapestry/upload` | POST | Upload XLSX |
| `/api/reports/tapestry/generate` | POST | Generate PDF |
| `/api/reports/{file}` | GET | Download report |

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
| `/api/auth/google` | POST | Google OAuth |
| `/api/auth/refresh` | POST | Refresh token |
| `/api/auth/me` | GET | Current user |

See [full API documentation](./docs/api/README.md).

## Deployment

### Render (Recommended)

1. Connect GitHub repo to Render
2. Configure as Web Service:
   - Environment: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Add environment variables

### Docker

```bash
docker build -t marketinsightsai-backend .
docker run -p 8000:8000 --env-file .env marketinsightsai-backend
```

## Documentation

- [Architecture Overview](./docs/architecture/README.md)
- [API Reference](./docs/api/README.md)
- [Development Guide](./docs/guides/development.md)
- [Feature Roadmap](./docs/roadmap/README.md)
- [AI Agent Patterns](./docs/research/ai-agent-patterns.md)

## Related

- **Frontend**: [marketinsightsai-frontend](https://github.com/patelyakshit/marketinsightsai-frontend)

## License

Private - All rights reserved
