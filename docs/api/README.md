# API Reference

<div align="center">

**MarketInsightsAI REST API Documentation**

Base URL: `http://localhost:8000/api`

</div>

---

## Overview

The MarketInsightsAI API provides endpoints for:
- AI chat with file upload support
- Tapestry report generation
- Knowledge base management
- Authentication

## Authentication

Most endpoints require authentication via JWT tokens.

### Headers

```
Authorization: Bearer <access_token>
```

### Token Flow

1. **Login**: `POST /api/auth/google` with Google OAuth token
2. **Receive**: Access token (30 min) + Refresh token (7 days)
3. **Refresh**: `POST /api/auth/refresh` to get new access token

---

## Endpoints

### Chat

#### POST /api/chat

Basic chat without file upload.

**Request:**
```json
{
  "message": "Tell me about the Laptops and Lattes segment",
  "use_knowledge_base": true
}
```

**Response:**
```json
{
  "response": "The Laptops and Lattes segment (C5)...",
  "sources": ["Esri Tapestry Segmentation"]
}
```

---

#### POST /api/chat/with-file

Full-featured chat with file upload, report generation, and marketing.

**Request (multipart/form-data):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User message (max 10,000 chars) |
| `file` | file | No | XLSX file for tapestry data |
| `store_id` | string | No | Store ID for report generation |
| `action` | string | No | Action: "generate_report" |
| `goal` | string | No | Report goal: "marketing", "instagram", etc. |
| `stores_json` | string | No | JSON string of stores (for session restore) |
| `folder_id` | string | No | Folder ID for context |

**Response:**
```json
{
  "response": "I've generated the tapestry report for Store A...",
  "sources": ["Esri Tapestry Segmentation"],
  "stores": [
    {
      "id": "store-123",
      "name": "Store A",
      "segments": [...]
    }
  ],
  "report_url": "/api/reports/tapestry/store-123-1234567890.pdf",
  "map_action": null,
  "marketing_action": null
}
```

---

#### POST /api/chat/image

Generate an image from a prompt.

**Request:**
```json
{
  "prompt": "A modern coffee shop with urban professionals"
}
```

**Response:**
```json
{
  "imageUrl": "/api/reports/generated_images/abc123.png",
  "description": "Generated image for: A modern coffee shop..."
}
```

---

#### GET /api/chat/stores

Get all stores uploaded via chat.

**Response:**
```json
{
  "stores": [
    {
      "id": "store-123",
      "name": "Downtown Location",
      "address": "123 Main St",
      "segments": [...]
    }
  ]
}
```

---

### Reports

#### POST /api/reports/tapestry/upload

Upload a tapestry XLSX file.

**Request (multipart/form-data):**

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | XLSX file with tapestry data |

**Response:**
```json
{
  "stores": [
    {
      "id": "store-123",
      "name": "Store Name",
      "segments": [
        {
          "code": "C5",
          "name": "Laptops and Lattes",
          "household_share": 15.2,
          "household_count": 1520
        }
      ]
    }
  ]
}
```

---

#### POST /api/reports/tapestry/generate

Generate a PDF report for a store.

**Request:**
```json
{
  "store_id": "store-123",
  "goal": "marketing"
}
```

**Response:**
```json
{
  "report_url": "/api/reports/tapestry/store-123-1234567890.pdf"
}
```

---

#### GET /api/reports/{filename}

Download a generated report.

**Response:** PDF file

---

### Knowledge Base

#### GET /api/kb/documents

List knowledge base documents.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `type` | string | Filter: "system", "workspace" |
| `workspace_id` | string | Filter by workspace |

**Response:**
```json
{
  "documents": [
    {
      "id": "doc-123",
      "title": "C5 - Laptops and Lattes",
      "type": "system",
      "content_preview": "Young, educated professionals..."
    }
  ]
}
```

---

#### POST /api/kb/upload

Upload a document to the workspace KB.

**Request (multipart/form-data):**

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | Markdown or text file |
| `workspace_id` | string | Target workspace |

---

#### DELETE /api/kb/documents/{id}

Delete a workspace document.

---

#### GET /api/kb/search

Semantic search across documents.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query |
| `limit` | int | Max results (default: 5) |
| `type` | string | Filter: "system", "workspace" |

**Response:**
```json
{
  "results": [
    {
      "id": "doc-123",
      "title": "C5 - Laptops and Lattes",
      "content": "Young, educated professionals...",
      "score": 0.89
    }
  ]
}
```

---

### Authentication

#### POST /api/auth/google

Authenticate with Google OAuth.

**Request:**
```json
{
  "credential": "<google_id_token>"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "user": {
    "id": "user-123",
    "email": "user@example.com",
    "name": "John Doe"
  }
}
```

---

#### POST /api/auth/refresh

Refresh access token.

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ..."
}
```

---

#### GET /api/auth/me

Get current user.

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
  "id": "user-123",
  "email": "user@example.com",
  "name": "John Doe"
}
```

---

### Health

#### GET /api/health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "app": "MarketInsightsAI"
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing/invalid token |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 500 | Internal Server Error |

---

## Rate Limiting

Currently no rate limiting is enforced. This will be added in future versions.

---

## Related Documents

- [Architecture Overview](../architecture/README.md)
- [Development Guide](../guides/development.md)
