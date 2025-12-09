# Development Guide

<div align="center">

**Setting up and developing MarketInsightsAI**

</div>

---

## Prerequisites

### Required Software

| Software | Version | Installation |
|----------|---------|--------------|
| Node.js | 22.x+ | [nodejs.org](https://nodejs.org/) |
| Python | 3.12+ | [python.org](https://www.python.org/) |
| PostgreSQL | 16+ | [postgresql.org](https://www.postgresql.org/) |
| Git | Latest | [git-scm.com](https://git-scm.com/) |

### Required API Keys

| Service | Purpose | Get it at |
|---------|---------|-----------|
| OpenAI | Chat, embeddings | [platform.openai.com](https://platform.openai.com/) |
| Google Cloud | Gemini image gen, OAuth | [console.cloud.google.com](https://console.cloud.google.com/) |
| Esri ArcGIS | Geocoding, demographics | [developers.arcgis.com](https://developers.arcgis.com/) |

---

## Initial Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/marketinsightsai.git
cd marketinsightsai
```

### 2. Set Up PostgreSQL

```bash
# Create database
createdb marketinsights

# Enable pgvector extension
psql -d marketinsights -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and database URL

# Start the server
uvicorn app.main:app --reload
```

### 4. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### 5. Verify Installation

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## Development Workflow

### Starting Development

```bash
# Terminal 1: Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

### Code Quality

```bash
# Frontend linting
cd frontend && npm run lint

# Frontend type checking
cd frontend && npx tsc --noEmit

# Backend type checking (optional)
cd backend && mypy app/
```

### Building for Production

```bash
# Frontend
cd frontend && npm run build

# Preview production build
cd frontend && npm run preview
```

---

## Project Structure

### Backend (`backend/`)

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings and configuration
│   ├── api/                 # API routers
│   │   ├── __init__.py
│   │   ├── chat.py          # Chat endpoints
│   │   ├── reports.py       # Report generation
│   │   ├── kb.py            # Knowledge base
│   │   ├── auth.py          # Authentication
│   │   └── folders.py       # Folder management
│   ├── services/            # Business logic
│   │   ├── __init__.py
│   │   ├── ai_service.py    # AI chat and generation
│   │   ├── tapestry_service.py  # Report generation
│   │   ├── kb_service.py    # Knowledge base
│   │   ├── esri_service.py  # ArcGIS integration
│   │   └── auth_service.py  # Authentication
│   ├── db/                  # Database
│   │   ├── __init__.py
│   │   ├── database.py      # Connection setup
│   │   └── models.py        # SQLAlchemy models
│   └── models/              # Pydantic schemas
│       ├── __init__.py
│       └── schemas.py       # Request/response models
├── templates/               # Jinja2 templates for reports
│   └── reports/
│       └── tapestry/
├── reports/                 # Generated reports output
├── requirements.txt
├── .env.example
└── .env                     # Local config (not committed)
```

### Frontend (`frontend/`)

```
frontend/
├── src/
│   ├── app/                 # Application code
│   │   ├── layout/          # Layout components
│   │   │   ├── AppLayout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── Header.tsx
│   │   └── routes/          # Page components
│   │       ├── AiChat/
│   │       ├── TapestryReport/
│   │       └── KnowledgeBase/
│   ├── shared/              # Shared code
│   │   ├── components/      # Reusable UI components
│   │   │   └── ui/          # Base UI components
│   │   ├── hooks/           # Custom React hooks
│   │   ├── types/           # TypeScript types
│   │   ├── utils/           # Utility functions
│   │   └── contexts/        # React contexts
│   ├── App.tsx              # Root component
│   ├── main.tsx             # Entry point
│   └── index.css            # Global styles
├── public/                  # Static assets
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

---

## Adding New Features

### Adding a New API Endpoint

1. Create or update router in `backend/app/api/`
2. Add service logic in `backend/app/services/`
3. Define Pydantic models in `backend/app/models/schemas.py`
4. Register router in `backend/app/main.py`

```python
# backend/app/api/new_feature.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/something")
async def get_something():
    return {"data": "value"}

# backend/app/main.py
from app.api import new_feature
app.include_router(new_feature.router, prefix="/api/new", tags=["New Feature"])
```

### Adding a New React Page

1. Create page component in `frontend/src/app/routes/`
2. Add route in `frontend/src/App.tsx`
3. Add navigation link in Sidebar

```tsx
// frontend/src/app/routes/NewFeature/NewFeaturePage.tsx
export function NewFeaturePage() {
  return <div>New Feature</div>
}

// frontend/src/App.tsx
<Route path="/new-feature" element={<NewFeaturePage />} />
```

### Adding a New Service

1. Create service file in `backend/app/services/`
2. Import and use in API routers

```python
# backend/app/services/new_service.py
async def do_something(data: dict) -> dict:
    # Business logic here
    return {"result": "success"}
```

---

## Environment Variables

### Backend (.env)

```bash
# Application
APP_NAME=MarketInsightsAI
DEBUG=false

# CORS
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/marketinsights

# Authentication
JWT_SECRET=your-secret-key-change-in-production

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

### Frontend

Environment variables in frontend are handled at build time via Vite. Currently, the API URL is auto-detected based on the current host.

---

## Testing

### Manual Testing

1. Start both servers
2. Open http://localhost:5173
3. Test features through the UI

### API Testing

Use the built-in Swagger docs at http://localhost:8000/docs

---

## Debugging

### Backend

```python
# Add print statements or use debugger
import pdb; pdb.set_trace()

# Or use logging
import logging
logging.info("Debug message")
```

### Frontend

```tsx
// Use browser DevTools console
console.log('Debug:', data)

// Or React DevTools for component inspection
```

### Common Issues

| Issue | Solution |
|-------|----------|
| CORS errors | Check `CORS_ORIGINS` in backend .env |
| Database connection | Verify `DATABASE_URL` and PostgreSQL is running |
| API key errors | Ensure all required API keys are set |
| Port conflicts | Change ports in configs or kill existing processes |

---

## Code Style

### TypeScript/React

- Functional components with hooks
- Strict TypeScript (minimal `any`)
- Named exports for components
- PascalCase for components, camelCase for functions

### Python

- Type hints on all functions
- Async/await for I/O operations
- Domain-based module organization
- Pydantic for data validation

### Tailwind CSS

- Utility-first approach
- Custom components in `ui/` folder
- Dark mode support via `dark:` prefix

---

## Related Documents

- [Architecture Overview](../architecture/README.md)
- [API Reference](../api/README.md)
- [Feature Roadmap](../roadmap/README.md)
