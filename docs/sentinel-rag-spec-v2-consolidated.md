# sentinel-rag

Enterprise RAG Governance Gateway

Blueprint v2 Consolidated Specification

## Status

This Markdown spec merges `sentinel-rag-blueprint-v2.docx` with `sentinel-rag-addendum.docx`.

- Blueprint v2 is the primary specification.
- The addendum takes precedence wherever the two documents conflict.
- A few source sections were truncated in the `.docx` extraction. This repo now resolves those gaps with explicit implementation defaults so the specification is actionable.

## 1. Project Overview

`sentinel-rag` is a production-grade AI gateway that centralizes enterprise LLM interactions. It enforces governance policies, logs prompts and responses, evaluates output quality, and exposes a React dashboard for monitoring and analytics.

### TDD Rule

Every feature is preceded by failing tests. No production code is written without a test first. Follow Red-Green-Refactor strictly.

### 1.1 Core Capabilities

- Centralized LLM gateway with provider routing and fallback
- Policy enforcement for prompts and responses
- Hybrid RAG over PostgreSQL + `pgvector`
- Audit logging with redaction, retention, and encryption
- OpenTelemetry tracing and golden-signal metrics
- Async evaluation harness for relevance and faithfulness
- React dashboard for operational analytics

### 1.2 Tech Stack

- Backend: Python, FastAPI, Celery
- Frontend: React
- Database: PostgreSQL with `pgvector`
- Queue / cache: Redis
- LLM abstraction: LiteLLM
- Observability: OpenTelemetry exported to Azure Monitor / Application Insights
- Identity: Azure Entra ID

### 1.3 Stack Rationale (Addendum A1)

The addendum requires an explicit explanation of the Python + React choice so the stack decision reads as deliberate.

- Python is the implementation language because the project is LLM- and RAG-heavy, and the surrounding ecosystem (FastAPI, Pydantic, LiteLLM, embedding and eval tooling, Celery, and PostgreSQL integrations) is strongest there.
- React is used for the operator dashboard because it is well-suited to data-dense internal analytics interfaces, charting, and real-time status views.
- This project demonstrates stack selection for AI-product fit. It should not be read as a statement that `.NET` is unsuitable or deprecated in other contexts.

## 2. Authentication and Authorization (Entra ID)

All endpoints use a single, consistent auth model: Azure Entra ID bearer tokens validated via a FastAPI dependency. Do not mix API key and bearer-token authentication.

### 2.1 Roles

The source doc names the following effective roles / principals:

- `reader`
- `admin`
- `service_account`

### 2.2 Auth Tests to Write First

- `test_unauthenticated_request_returns_401()`
- `test_reader_cannot_delete_document_returns_403()`
- `test_admin_can_delete_document()`
- `test_service_account_cannot_access_logs()`
- `test_tenant_isolation_reader_cannot_see_other_tenant_logs()`
- `test_policy_override_requires_admin_role_and_justification()`
- `test_token_expiry_returns_401_not_500()`

## 3. Folder Structure

The blueprint expects a split backend/frontend structure plus local infra. The initial scaffold in this repo follows that shape.

## 4. Database Schema (v2)

Use PostgreSQL with the `pgvector` extension. All tables use UUID primary keys.

The v2 schema adds:

- `retrieval_runs`
- `retrieval_results`
- `model_invocations`
- retention / encryption fields on persisted records

### 4.1 Critical Indexes

These indexes are explicitly required in migrations:

- `audit_logs (tenant_id, created_at DESC)`
- `audit_logs (app_id, created_at DESC)`
- `audit_logs (trace_id)`
- `document_chunks` HNSW index on `embedding`
- `document_chunks` GIN index on `fts`
- `eval_results (audit_log_id)`

### 4.2 Additional Table From Addendum A5

The addendum requires a tenant quota table for evaluation-budget accounting.

- Add a `tenant_quotas` table with these columns:
- `id UUID PRIMARY KEY`
- `tenant_id UUID UNIQUE NOT NULL`
- `daily_eval_budget_usd NUMERIC(10,2) NOT NULL DEFAULT 10.00`
- `daily_eval_spend_usd NUMERIC(10,2) NOT NULL DEFAULT 0.00`
- `monthly_llm_budget_usd NUMERIC(10,2) NOT NULL DEFAULT 250.00`
- `monthly_llm_spend_usd NUMERIC(10,2) NOT NULL DEFAULT 0.00`
- `eval_sample_pct SMALLINT NOT NULL DEFAULT 10`
- `force_eval_relevance_threshold NUMERIC(3,2) NOT NULL DEFAULT 0.40`
- `last_eval_reset_at TIMESTAMPTZ NOT NULL`
- `month_bucket DATE NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

## 5. TDD Workflow

Follow the blueprint's agent instructions:

- Write failing tests first.
- Do not skip phases.
- Do not combine phases.
- Keep tests green before advancing.
- Commit after each phase once tests are green.

## 6. Feature Specifications

### Feature 1: LLM Gateway Router

Accept a prompt request, apply policy, select a provider, call the LLM via LiteLLM, and return the response with full metadata. Implement a circuit breaker and cooldown.

#### API Contract

`POST /api/v1/gateway/complete`

`POST /api/v1/gateway/stream` (SSE)

```json
{
  "prompt": "string",
  "provider": "auto | azure | anthropic | openai",
  "max_tokens": 1000,
  "context": {
    "tenant_id": "uuid",
    "app_id": "string",
    "trace_id": "uuid"
  }
}
```

#### Provider Routing and Circuit Breaker (Addendum A3)

Each provider has an independent circuit breaker.

- Circuit state is stored in Redis, not the primary database, for low-latency reads.
- `provider_configs` stores configurable thresholds and timeouts.

Failures that count toward breaker state:

- Upstream HTTP `5xx`
- HTTP `429` (also triggers a longer cooldown than a normal failure)
- Request timeout
- Connection error / DNS failure

Failures that do not count:

- HTTP `4xx` other than `429` because they represent bad input, not provider health

Default fallback priority:

1. `azure_openai`
2. `anthropic`
3. `openai`

Behavior when all providers are open:

- Return `503 Service Unavailable`, not `500`

Canonical default breaker configuration:

- Rolling failure window: `60` seconds
- Open threshold: `5` counted failures inside the rolling window
- Normal cooldown after `5xx` / timeout / connection failure: `30` seconds
- Rate-limit cooldown after `429`: `120` seconds
- Half-open probe count: `1` request
- Azure OpenAI timeout: `12000` ms
- Anthropic timeout: `15000` ms
- OpenAI timeout: `12000` ms

Canonical state machine:

- `CLOSED`: provider is routable and failures are counted in the rolling window
- `OPEN`: provider is skipped until the cooldown expires
- `HALF_OPEN`: exactly one probe request is allowed
- Probe success closes the breaker and clears the failure window
- Probe failure re-opens the breaker and applies a fresh cooldown

#### Tests to Write First

- `test_routes_to_azure_openai_by_default()`
- `test_routes_to_anthropic_when_policy_specifies()`
- `test_circuit_breaker_opens_after_n_failures()`
- `test_cooldown_prevents_thrashing_on_failed_provider()`
- `test_falls_back_to_openai_after_cooldown_expires()`
- `test_all_providers_fail_raises_503_not_500()`
- `test_response_includes_provider_and_model_metadata()`
- `test_trace_id_propagated_to_litellm_call()`
- `test_breaker_opens_after_5_failures_in_60s_window()`
- `test_429_response_triggers_longer_cooldown()`
- `test_4xx_non_429_does_not_increment_failure_counter()`
- `test_breaker_transitions_to_half_open_after_cooldown()`
- `test_probe_success_closes_breaker()`
- `test_probe_failure_reopens_breaker_and_resets_cooldown()`
- `test_all_providers_open_returns_503_not_500()`
- `test_circuit_state_stored_in_redis_not_db()`

### Feature 2: Policy Engine

Policy decisions return a structured `PolicyDecision` object and support `allow`, `block`, and `allow_with_redactions`. Overrides require `admin` role plus a justification.

#### PolicyDecision Object

```python
class PolicyDecision(BaseModel):
    decision: Literal["allow", "block", "allow_with_redactions"]
    rule_ids: list[str]
    severity: Literal["low", "medium", "high", "critical"]
    explanations: list[str]
    redacted_prompt: str | None
```

#### Redaction Timing (Addendum A2)

Use a two-stage redaction model.

- Raw prompts may be sent to the LLM for output quality.
- Raw prompts exist only in memory during the request lifecycle.
- Raw prompts must not be persisted to the database, logs, traces, or long-lived storage.
- Anything written to disk must be redacted and encrypted where applicable.
- Responses must be scanned for PII before persistence.

Operational interview summary from the addendum:

- "We send raw prompts to the LLM for quality, but we never persist them. The raw text lives only in memory during the request lifecycle. Everything written to disk is redacted and encrypted."

#### Tests to Write First

- `test_clean_prompt_returns_allow_decision()`
- `test_email_in_prompt_returns_allow_with_redactions()`
- `test_phone_in_prompt_returns_allow_with_redactions()`
- `test_ssn_in_prompt_returns_allow_with_redactions()`
- `test_injection_attempt_returns_block_decision()`
- `test_jailbreak_pattern_returns_block_critical_severity()`
- `test_blocked_decision_never_calls_llm()`
- `test_all_decisions_write_policy_violations_row()`
- `test_override_without_admin_role_raises_403()`
- `test_override_with_admin_role_and_justification_succeeds()`
- `test_override_creates_policy_overrides_row()`
- `test_response_pii_redacted_before_persistence()`
- `test_raw_prompt_sent_to_llm_not_redacted_prompt()`
- `test_raw_prompt_never_written_to_database()`
- `test_response_scanned_for_pii_before_persistence()`
- `test_otel_span_does_not_contain_raw_prompt_text()`
- `test_otel_span_does_not_contain_response_text()`

### Feature 3: RAG Pipeline

Use a single retrieval backend: PostgreSQL + `pgvector`. Hybrid retrieval combines vector similarity with PostgreSQL full-text search. Retrieval context is stored for later evaluation.

#### Document Ingestion Security States (Addendum A4)

Document lifecycle states must support at least:

- `PENDING`
- `ACTIVE`
- `SCAN_FAILED`
- `SCAN_UNKNOWN`
- `QUARANTINED`

Malware-scan handling:

- Scan timeout greater than 30 seconds sets `SCAN_FAILED`
- Scanner error sets `SCAN_FAILED`
- Unknown result sets `SCAN_UNKNOWN`
- Detected malware sets `QUARANTINED`
- Quarantined files are soft-isolated and preserved for forensics, not deleted
- Only `ACTIVE` documents are eligible for retrieval
- All non-`ACTIVE` states are silently excluded from retrieval results

Malware scanner by environment:

- `test`: deterministic mock scanner, configurable to return `clean`, `timeout`, `failed`, `unknown`, or `malware`
- `ci`: deterministic mock scanner plus an EICAR fixture path for regression tests
- `local`: ClamAV daemon over TCP at `MALWARE_SCANNER_HOST:MALWARE_SCANNER_PORT`, default `localhost:3310`
- `staging`: ClamAV-compatible network scanner over TCP
- `production`: ClamAV-compatible network scanner over TCP with fail-closed behavior

#### Tests to Write First

- `test_chunk_splits_at_correct_size_with_overlap()`
- `test_embed_returns_1536_dimension_vector()`
- `test_hybrid_search_returns_semantic_and_keyword_results()`
- `test_reranker_reorders_results_by_relevance()`
- `test_retrieval_run_row_created_per_query()`
- `test_retrieval_results_rows_created_with_rank_and_score()`
- `test_source_citations_included_in_response()`
- `test_document_ingest_rejects_oversized_file()`
- `test_document_ingest_rejects_disallowed_mime_type()`
- `test_tenant_isolation_retrieval_cannot_cross_tenant()`
- `test_new_document_starts_in_pending_state()`
- `test_scan_timeout_sets_status_scan_failed()`
- `test_scan_failed_document_excluded_from_retrieval()`
- `test_scan_unknown_treated_same_as_scan_failed()`
- `test_quarantined_document_never_returned_in_retrieval()`
- `test_only_active_documents_indexed_by_rag_pipeline()`
- `test_malware_detected_sets_status_quarantined()`

### Feature 4: Audit Logging, Redaction, and Retention

PII is redacted from both prompt and response before persistence. Sensitive columns use envelope encryption with a Key Vault-managed key. A Celery beat job enforces retention TTL.

#### Tests to Write First

- `test_audit_log_created_for_every_request()`
- `test_raw_prompt_never_stored_only_hash_and_redacted()`
- `test_response_pii_redacted_before_storage()`
- `test_user_id_and_app_id_stored_in_audit_log()`
- `test_trace_id_stored_in_audit_log()`
- `test_ip_stored_as_hash_not_plaintext()`
- `test_model_invocations_row_created_per_llm_call()`
- `test_cost_usd_calculated_correctly_from_token_count()`
- `test_retention_job_deletes_response_logs_after_ttl()`
- `test_audit_log_query_filtered_by_tenant_id()`
- `test_audit_log_query_filtered_by_date_range()`

### Feature 5: OpenTelemetry Observability

Every request carries a `trace_id`. Create spans for API entry, policy check, retrieval, LLM call, and the eval job. Export traces and metrics to Azure Monitor / Application Insights.

#### Golden Signals Dashboard

- P50 / P95 / P99 gateway latency
- Error rate by provider
- Token cost per `app_id` (daily + monthly)
- Eval score trend over time
- Policy violation rate by `rule_id`

#### Tests to Write First

- `test_trace_id_generated_if_not_provided()`
- `test_trace_id_propagated_through_all_service_calls()`
- `test_span_created_for_policy_engine_check()`
- `test_span_created_for_retrieval_run()`
- `test_span_created_for_llm_provider_call()`
- `test_span_includes_provider_and_model_attributes()`
- `test_error_span_set_on_provider_failure()`
- `test_golden_signals_metric_latency_recorded()`
- `test_golden_signals_metric_token_cost_recorded()`

### Feature 6: Evaluation Harness

Faithfulness is measured against stored retrieval context, not just the prompt. Use GPT-4o as the LLM-as-judge. The queue contract is asynchronous: gateway requests enqueue eval work into `eval_jobs`, and the default runtime dispatches Celery tasks over Redis so a worker can consume those jobs out of band. Tests override that worker with an inline executor to keep the suite isolated, but production no longer evaluates in-request. Judge prompts are versioned under `backend/eval/prompts/`.

Operational queue behavior in the scaffold:

- `eval_jobs` move through `PENDING`, `PROCESSING`, `RETRY`, `COMPLETED`, or `FAILED`
- Worker execution failures and broker dispatch failures both write `last_error` on the job row
- Failed jobs use exponential backoff with persisted `next_attempt_at`
- Jobs become `FAILED` after the configured maximum attempt count instead of staying indefinitely retryable
- Admin-triggered backfill only re-queues jobs that are due (`PENDING` or `RETRY` with `next_attempt_at <= now`)
- Unrecoverable task-level failures are copied into `eval_dead_letters` with the task name, serialized payload, retry count, and error text
- Operators can inspect queued and failed jobs through `GET /api/v1/evals/jobs`
- Operators can inspect unrecoverable task failures through `GET /api/v1/evals/dead-letters`
- Failed jobs can be manually replayed through `POST /api/v1/evals/jobs/{job_id}/requeue`

#### Cost Control and Sampling (Addendum A5)

The addendum adds cost guardrails so the eval system does not run on 100 percent of traffic.

Required behavior:

- Sampling must be configurable per tenant or globally
- Budget checks run before invoking the judge model
- Policy violations must still trigger evaluation regardless of budget
- Low relevance or risky responses must still trigger evaluation regardless of budget
- Daily evaluation spend is tracked and reset at midnight UTC
- The gateway returns `429` when tenant monthly budget limits are exceeded

Default evaluation controls:

- Default sample rate: `10%` of eligible requests
- Forced evaluation threshold: run eval when top retrieval relevance is less than `0.40`
- Default daily eval budget per tenant: `$10.00`
- Default monthly LLM budget per tenant: `$250.00`
- Sampled-out requests must log the reason as `sampled_out`
- Budget-skipped evals must log the reason as `daily_budget_exceeded`

Sampling decision logic:

1. If `monthly_llm_spend_usd >= monthly_llm_budget_usd`, reject the gateway request with `429`
2. If the policy engine returns anything other than `allow`, enqueue eval
3. If the top retrieval relevance score is less than `0.40`, enqueue eval
4. If `daily_eval_spend_usd >= daily_eval_budget_usd`, skip eval and log `daily_budget_exceeded`
5. Otherwise sample by `eval_sample_pct`
6. If selected, run the judge and increment `daily_eval_spend_usd`
7. Reset `daily_eval_spend_usd` to `0.00` at midnight UTC

Current scaffold behavior:

- Gateway requests now return `429 Too Many Requests` when tenant monthly spend is already at or above the configured monthly budget
- Monthly spend is incremented after each successful model invocation using the same provider/model pricing table used for `model_invocations`
- Daily eval spend resets lazily on the first quota read after a UTC date rollover via `last_eval_reset_at`

#### Judge Prompt Versioning

Judge prompts live in `backend/eval/prompts/`. Each file is named by version, for example `faithfulness_v1.txt`. The version is stored in `eval_results.judge_version`. Any prompt change requires a new version file and a schema-compatible rollout.

#### Tests to Write First

- `test_relevance_scorer_returns_float_0_to_1()`
- `test_faithfulness_uses_retrieval_context_not_prompt()`
- `test_faithfulness_detects_claim_not_in_retrieved_chunks()`
- `test_hallucination_flag_set_when_faithfulness_below_threshold()`
- `test_judge_prompt_version_stored_with_eval_result()`
- `test_eval_result_linked_to_retrieval_run_id()`
- `test_eval_job_does_not_block_gateway_response()`
- `test_eval_cost_tracked_in_model_invocations()`
- `test_eval_skipped_when_budget_exceeded()`
- `test_eval_always_runs_on_policy_violation_regardless_of_budget()`
- `test_eval_always_runs_on_low_relevance_score()`
- `test_eval_skipped_when_sampled_out_reason_logged()`
- `test_eval_spend_incremented_after_judge_call()`
- `test_eval_spend_reset_to_zero_at_midnight_utc()`
- `test_gateway_429_when_tenant_monthly_budget_exceeded()`

### Feature 7: Security and Regression Test Suite

Create an explicit security test area covering multi-tenancy, prompt injection, cost guardrails, streaming, and document security.

#### Multi-Tenancy Isolation

- `test_tenant_a_logs_not_visible_to_tenant_b()`
- `test_tenant_a_documents_not_retrievable_by_tenant_b()`
- `test_shared_document_requires_explicit_grant()`

#### Prompt Injection Regression Corpus

Maintain `tests/security/injection_corpus.json`. Every pattern in the corpus must be blocked on every run.

- `test_injection_corpus_all_patterns_blocked()`
- `test_new_injection_pattern_added_to_corpus_and_blocked()`

#### Cost Guardrails

- `test_request_exceeding_max_tokens_rejected()`
- `test_app_id_over_monthly_budget_rejected_with_429()`
- `test_expensive_model_blocked_by_policy_for_service_account()`

#### Streaming (SSE)

- `test_stream_returns_partial_chunks_in_order()`
- `test_stream_cancellation_closes_provider_connection()`
- `test_stream_policy_check_runs_before_first_chunk()`

#### Document Ingestion Security

- `test_file_size_limit_enforced()`
- `test_disallowed_mime_type_rejected()`
- `test_malware_scan_hook_called_on_upload()`

## 7. Full API Route Reference

The source `.docx` lists this section heading but the extracted content does not include the complete route table. This repo defines the baseline route set below.

- `POST /api/v1/gateway/complete`
- `POST /api/v1/gateway/stream`
- `GET /api/v1/health`
- `POST /api/v1/auth/demo` (local mode only)
- `GET /api/v1/auth/me`
- `GET /api/v1/audit/logs`
- `GET /api/v1/documents`
- `POST /api/v1/documents`
- `POST /api/v1/documents/{document_id}/scan-result`
- `DELETE /api/v1/documents/{document_id}`
- `GET /api/v1/evals`
- `GET /api/v1/evals/dead-letters`
- `GET /api/v1/evals/jobs`
- `POST /api/v1/evals/jobs/{job_id}/requeue`
- `POST /api/v1/evals/process`
- `GET /api/v1/metrics/costs`
- `POST /api/v1/retrieval/search`
- `GET /api/v1/retrieval/runs`
- `POST /api/v1/policy/overrides`

Future build phases will add document upload, retrieval, analytics, and admin endpoints without changing the auth model.

## 8. Agent Build Order

Each phase must have green tests before proceeding to the next phase. Do not skip phases.

Recommended implementation sequence:

1. Auth foundation and app shell
2. Gateway router
3. Policy engine
4. RAG ingestion and retrieval
5. Audit logging and retention
6. Observability
7. Evaluation harness
8. Security and regression suite
9. Dashboard completion
10. CI/CD hardening

## 9. CI/CD Pipeline

PRs run tests only. Container images are not pushed on pull requests. Image push and deployment happen only after merge to `main`.

## 10. Local Development

### 10.1 Docker Compose (infra only)

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: sentinel_rag
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: localdev
    ports:
      - "5433:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
```

Redis is both the Celery broker and the result backend. The scaffold uses host ports `5433` and `6380` to avoid collisions with other local stacks already using the default ports.

### 10.2 Startup Sequence

```bash
docker compose up -d
cd backend && pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
celery -A core.celery_app worker --loglevel=info
cd frontend && npm install && npm run dev
cd backend && pytest --cov
```

## 11. Environment Variables

Use this baseline environment contract:

- `POSTGRES_DSN`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `APP_ENV`
- `AUTH_VERIFIER_MODE`
- `ENTRA_TENANT_ID`
- `ENTRA_AUDIENCE`
- `ENTRA_JWT_ISSUER`
- `ENTRA_JWT_SIGNING_KEY`
- `ENTRA_JWT_ALGORITHM`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GATEWAY_DEFAULT_TIMEOUT_MS`
- `GATEWAY_FAILURE_COOLDOWN_SECONDS`
- `GATEWAY_RATE_LIMIT_COOLDOWN_SECONDS`
- `MALWARE_SCANNER_MODE`
- `MALWARE_SCANNER_HOST`
- `MALWARE_SCANNER_PORT`
- `EVAL_SAMPLE_PCT`
- `EVAL_DAILY_BUDGET_USD`
- `TENANT_MONTHLY_BUDGET_USD`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `BOOTSTRAP_SCHEMA_ON_STARTUP`

## Ready-to-Build Prompt

Build `sentinel-rag` exactly as specified here. Follow TDD strictly: write failing tests first, then implement. Build in the phase order from Section 8. Do not skip phases or combine them.
