# IntelliFlow AI — Backend (Phase 1 MVP)

Backend service that turns plain-English business requirements into SAP CPI iFlow
designs via a direct LLM call.

Phase 1 is intentionally small: **no auth, no frontend, no Docker, no RAG**. A
client can generate a flow, save it, list saved flows, fetch a single flow, and
export it as JSON.

## Prerequisites

- Python **3.11**
- A local MongoDB running at `mongodb://localhost:27017`
- An OpenAI API key

## Install

```bash
cd intelliflow/backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Environment variables

Copy `.env.example` to `.env` and fill in your key:

```
OPENAI_API_KEY=sk-...
MONGODB_URI=mongodb://localhost:27017
LLM_MODEL=gpt-4-turbo
```

## Run

From inside `intelliflow/backend/`:

```bash
uvicorn app.main:app --reload
```

Swagger UI: <http://localhost:8000/docs>

## Tests

```bash
pytest
```

All tests stub the OpenAI client and the Mongo collection, so they run offline.

## Endpoints — example curls

All endpoints are mounted under `/api/v1`.

### 1. Generate a flow

```bash
curl -X POST http://localhost:8000/api/v1/iflow/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Build a flow that receives a customer payload over HTTPS, maps it to the Salesforce schema, and pushes it to Salesforce via SOAP."}'
```

Response includes `flow_id` (also auto-saved) and the full `flow` document.

### 2. Save / rename a flow

```bash
curl -X POST http://localhost:8000/api/v1/iflow/save \
  -H "Content-Type: application/json" \
  -d '{"flow_id":"<id-from-generate>","name":"Customer Sync v1","tags":["sales","prod"]}'
```

### 3. List saved flows (paginated)

```bash
curl "http://localhost:8000/api/v1/iflow/history?page=1&limit=20"
```

### 4. Get a single flow

```bash
curl http://localhost:8000/api/v1/iflow/<flow_id>
```

### 5. Export a flow as JSON

```bash
curl -OJ "http://localhost:8000/api/v1/iflow/<flow_id>/export?format=json"
```

`format=pdf` and `format=xml` return HTTP 501 (Phase 2).

## Notes

- CORS is open to `*` for local development.
- Rate limit: **10 generations per minute per client IP** (in-memory token bucket).
- Structured JSON logs are emitted for every LLM call (model, latency, tokens).
- A descending index on `created_at` is created at startup for history pagination.
