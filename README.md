# sentinel-rag

`sentinel-rag` is a multi-tenant RAG governance gateway for enterprise AI applications.

It sits between clients and LLM providers, applying policy controls before inference, running hybrid retrieval over tenant documents, persisting an auditable trail of model activity, and executing asynchronous evaluation jobs through a resilient worker pipeline.

## What It Demonstrates

- FastAPI backend with route-level dependency injection and test-first service boundaries
- React dashboard for documents, retrieval runs, eval results, job state, dead letters, and spend
- Gateway routing with provider abstraction, fallback ordering, and circuit-breaker behavior
- Prompt policy enforcement for prompt injection blocking and PII redaction
- Hybrid retrieval using persisted chunk metadata with native Postgres `pgvector` + keyword search
- Audit logging with prompt hashing, redaction, encryption at rest, and response-body TTL retention
- Async eval job orchestration with Celery, retries, requeue, and dead-letter capture
- Tenant quota controls for evaluation spend and monthly LLM budget enforcement

## Screenshots

### Live Dashboard

Real API data — authenticated tenant session, mixed document states, retrieval runs with query text and ranked hits, eval jobs processed by the Celery worker, and a non-zero provider cost breakdown.

![sentinel-rag live dashboard](docs/screenshots/dashboard-live-desktop.png)

The dashboard surfaces six operator panels:

| Panel | What it shows |
|---|---|
| **Tenant Inventory** | Documents with lifecycle status — `ACTIVE`, `PENDING`, `QUARANTINED` |
| **Recent Search Runs** | Retrieval queries, hit counts, and run IDs |
| **Recent Eval Results** | Faithfulness scores and judge version per retrieval run |
| **Eval Job States** | Queue depth with `COMPLETED` / `RETRY` / `FAILED` badges |
| **Dead Letters** | Unrecoverable eval jobs with payload inspect and requeue action |
| **Model Spend** | Per-provider cost breakdown with running total |

### Backend API

Full Swagger UI showing all 16 endpoints across 9 route groups. Lock icons indicate auth-protected routes; method badges show the HTTP verb.

![sentinel-rag backend API docs](docs/screenshots/backend-swagger.png)

Route groups: `health` · `auth` · `audit` · `documents` · `evals` · `metrics` · `policy` · `retrieval` · `gateway`

## Current Status

This repository is a serious working prototype, not a finished production deployment.

What is real today:

- Persistence model for documents, retrieval, audit logs, model invocations, eval jobs, and quotas
- Local infra for Postgres and Redis
- API-backed operator flows for audit, eval queue state, dead letters, and requeue
- Test coverage across the main backend slices

What is intentionally still incomplete:

- Embeddings are still local heuristic vectors, not model-backed production embeddings
- The eval judge still uses a local deterministic simulation behind a prompt-based interface
- Live provider mode exists, but safe local development defaults to stubbed completions unless credentials are configured
- OpenTelemetry instrumentation is not wired yet

## Repository Layout

- `backend/` FastAPI app, core services, Celery tasks, and tests
- `frontend/` React dashboard
- `infra/` local Docker Compose for Postgres and Redis
- `docs/` consolidated spec and implementation checklist

## Key Docs

- `docs/sentinel-rag-spec-v2-consolidated.md`
- `docs/implementation-checklist.md`

## Local Development

### Infrastructure

```bash
docker compose -f infra/docker-compose.yml up -d
```

### Backend

```bash
cd backend
uv run uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend
uv run pytest
```

The default local mode is intentionally safe:

- `GATEWAY_PROVIDER_MODE=stub` — no live LLM credentials required
- `AUTH_VERIFIER_MODE=local` — bearer tokens issued by `POST /api/v1/auth/demo`

## Discussion Topics

This project is well suited for backend and systems-design discussions around:

- multi-tenant service boundaries and per-tenant policy enforcement
- governance and auditability controls for LLM usage
- async worker reliability patterns — retries, dead letters, requeue
- hybrid retrieval: vector similarity + keyword ranking on the same corpus
- circuit-breaker routing across heterogeneous LLM providers
- progressive hardening of an AI platform prototype toward production
