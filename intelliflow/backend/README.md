# IntelliFlow AI — Backend (Phase 2: RAG)

Backend service that turns plain-English business requirements into SAP CPI iFlow
designs, grounded in a citable knowledge base.

Phase 2 adds a hybrid RAG retriever, citation-producing generation, anti-hallucination
validators, XSD validation, AI Error Fixer, and PDF export. No auth, no frontend.

## Prerequisites

- Python **3.11**
- A local MongoDB running at `mongodb://localhost:27017`
- An OpenAI API key (generator + embeddings)
- An Anthropic API key (query rewriter, optional — falls back to identity)
- Optional: Graphviz `dot` binary on `PATH` for diagram rendering in PDF export

## Install

```bash
cd intelliflow/backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
# Optional: pin the cross-encoder reranker (~280MB on first call)
pip install -e ".[reranker]"
```

## Environment variables

Copy `.env.example` to `.env` and fill in your keys. Key settings:

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
MONGODB_URI=mongodb://localhost:27017
LLM_MODEL=gpt-4-turbo
LLM_FALLBACK_MODEL=claude-sonnet-4-6
LLM_REWRITER_MODEL=claude-haiku-4-5
EMBEDDING_MODEL=text-embedding-3-small
RERANKER_MODEL=BAAI/bge-reranker-base
RAG_GENERATOR_INPUT_TOKEN_CAP=15000
CHROMA_PERSIST_DIR=./.chroma
KB_ROOT=./knowledge_base
```

## Ingest the knowledge base

```bash
make ingest
# or: python -m app.rag.ingest
# or: python -m app.rag.ingest --reset    # drop + reindex
```

This walks `knowledge_base/`, splits each file with a header-aware Markdown splitter
(500-token chunks, 75-token overlap), embeds with `text-embedding-3-small`, and
upserts into both ChromaDB (`./.chroma/`) and MongoDB (`kb_chunks` collection).
Idempotent — keyed on `(source_file, chunk_id)`.

## Run

```bash
make run
# or: uvicorn app.main:app --reload
```

Swagger UI: <http://localhost:8000/docs>

## Tests

```bash
make test
# or: pytest -v
```

All tests stub the OpenAI/Anthropic clients and the Mongo collection; they run offline.

## Eval harness

```bash
make eval
# or: python -m app.rag.eval.eval --out eval_report.json --max-hallucination 0.05
```

Reports `recall@5`, `component_f1`, `hallucination_rate`, `mean_latency_ms` over
`tests/rag/golden_set.jsonl` (20 seeds). Exits non-zero when hallucination_rate
exceeds the threshold — used as a CI gate.

## Endpoints — example curls

All endpoints are mounted under `/api/v1`.

### Generate a flow (RAG + validation)

```bash
curl -X POST http://localhost:8000/api/v1/iflow/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Build a flow that receives orders over HTTPS, validates against an XSD, branches valid/invalid, and pushes valid orders into S/4HANA via OData."}'
```

Every component in the response carries a non-empty `citations[]` resolving to a
real KB chunk. Hallucinated adapter types are rejected with HTTP 422.

### Save / rename / tag

```bash
curl -X POST http://localhost:8000/api/v1/iflow/save \
  -H "Content-Type: application/json" \
  -d '{"flow_id":"<id>","name":"Order Sync v1","tags":["s4hana","prod"]}'
```

### History (paginated)

```bash
curl "http://localhost:8000/api/v1/iflow/history?page=1&limit=20"
```

### Get a flow

```bash
curl http://localhost:8000/api/v1/iflow/<flow_id>
```

### Export JSON or PDF

```bash
curl -OJ "http://localhost:8000/api/v1/iflow/<flow_id>/export?format=json"
curl -OJ "http://localhost:8000/api/v1/iflow/<flow_id>/export?format=pdf"
```

XML export still returns 501.

### Validate XML (3-level cascade)

```bash
XSD_B64=$(base64 -w0 customer.xsd)
curl -X POST http://localhost:8000/api/v1/iflow/validate-xml \
  -H "Content-Type: application/json" \
  -d "{\"xml\":\"<Order><Id>1</Id></Order>\",\"required_fields\":[\"/Order/Customer\"],\"xsd_base64\":\"$XSD_B64\"}"
```

Returns `{valid, errors[{level, message, xpath, line}]}`.

### AI Error Fixer

```bash
curl -X POST http://localhost:8000/api/v1/iflow/fix-xml \
  -H "Content-Type: application/json" \
  -d '{"xml":"<Order><Id>abc</Id></Order>","error_message":"Id is not a valid integer","xsd_base64":"..."}'
```

Returns `{root_cause, corrected_xml, diff, citations, still_invalid, remaining_errors}`.
The service re-runs validation on the corrected payload and honestly flags
`still_invalid: true` rather than silently returning a broken result.

## Notes

- **CORS**: open to `*` for local development.
- **Rate limit**: 10 generations/min/IP, 60 other/min/IP (slowapi, keyed on
  client IP — TODO swap to per-user when auth lands).
- **Tracing**: every retrieval / LLM step emits a structured JSON line with
  `request_id`, `step_name`, `latency_ms`, `token_count`, and `model`.
  Request IDs propagate via `contextvars`; the inbound `X-Request-Id` header
  is honored.
- **Secrets**: `SecretsProvider` interface (`EnvSecretsProvider` by default);
  log records are redacted via a custom `LogRecord` factory so accidental key
  formatting never leaks.
- **Token guardrail**: a single `/iflow/generate` call's prompt is capped at
  15k input tokens (`RAG_GENERATOR_INPUT_TOKEN_CAP`); lowest-ranked chunks
  are dropped with a trace warning.
- **Adapter whitelist**: union of the Phase 1 enum and ChromaDB `adapter_type`
  metadata. Anything else → HTTP 422.
- **Reranker**: lazy-loaded `BAAI/bge-reranker-base` (~280MB on first download
  to `~/.cache/huggingface/`). Falls back to identity ordering when
  `sentence-transformers` is not installed.
- **Diagram**: PDF export tries Graphviz `dot`; if missing, falls back to a
  textual edge list (no error).
- **Out of scope for Phase 2**: auth, frontend, agentic RAG, Graph RAG,
  Neo4j, team collaboration, optimization suggestions.
