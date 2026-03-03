# sentinel-rag Implementation Checklist

## Deliverables Created

- Consolidated spec: `docs/sentinel-rag-spec-v2-consolidated.md`
- Starter scaffold: backend, frontend, infra, and test directories

## Canonical Defaults Locked In

- Circuit breaker opens after `5` failures in `60s`
- Normal cooldown is `30s`; `429` cooldown is `120s`
- Half-open allows `1` probe request
- Local malware scanning uses ClamAV on `localhost:3310`
- Test and CI use a deterministic mock malware scanner
- Default evaluation sample rate is `10%`
- Forced evaluation threshold is retrieval relevance below `0.40`
- Default daily eval budget is `$10.00` per tenant
- Default monthly LLM budget is `$250.00` per tenant
- The baseline route and environment contracts are now captured in the consolidated spec

## Recommended Build Order

### Phase 0: Foundation

- [ ] Review and accept the canonical defaults above
- [ ] Lock Python version and frontend Node version
- [ ] Create a virtual environment and install backend dependencies
- [ ] Install frontend dependencies
- [ ] Bring up PostgreSQL + Redis locally
- [ ] Add baseline linting, formatting, and test commands

### Phase 1: Auth and App Shell

- [ ] Implement FastAPI app factory and route registration
- [ ] Add Entra ID bearer-token validation dependency
- [ ] Define role model: `reader`, `admin`, `service_account`
- [ ] Add tenant isolation primitives to request context

Tests first:

- [ ] `test_unauthenticated_request_returns_401()`
- [ ] `test_reader_cannot_delete_document_returns_403()`
- [ ] `test_admin_can_delete_document()`
- [ ] `test_service_account_cannot_access_logs()`
- [ ] `test_tenant_isolation_reader_cannot_see_other_tenant_logs()`
- [ ] `test_policy_override_requires_admin_role_and_justification()`
- [ ] `test_token_expiry_returns_401_not_500()`

### Phase 2: Gateway Router

- [ ] Add request and response schemas
- [ ] Integrate LiteLLM provider abstraction
- [ ] Add provider config model
- [ ] Implement Redis-backed circuit-breaker state
- [ ] Implement fallback routing and 503 exhaustion handling
- [ ] Add SSE streaming endpoint contract

Tests first:

- [ ] `test_routes_to_azure_openai_by_default()`
- [ ] `test_routes_to_anthropic_when_policy_specifies()`
- [ ] `test_circuit_breaker_opens_after_n_failures()`
- [ ] `test_cooldown_prevents_thrashing_on_failed_provider()`
- [ ] `test_falls_back_to_openai_after_cooldown_expires()`
- [ ] `test_all_providers_fail_raises_503_not_500()`
- [ ] `test_response_includes_provider_and_model_metadata()`
- [ ] `test_trace_id_propagated_to_litellm_call()`
- [ ] `test_breaker_opens_after_5_failures_in_60s_window()`
- [ ] `test_429_response_triggers_longer_cooldown()`
- [ ] `test_4xx_non_429_does_not_increment_failure_counter()`
- [ ] `test_breaker_transitions_to_half_open_after_cooldown()`
- [ ] `test_probe_success_closes_breaker()`
- [ ] `test_probe_failure_reopens_breaker_and_resets_cooldown()`
- [ ] `test_all_providers_open_returns_503_not_500()`
- [ ] `test_circuit_state_stored_in_redis_not_db()`

### Phase 3: Policy Engine

- [ ] Implement `PolicyDecision`
- [ ] Add prompt classification and redaction rules
- [ ] Block injection and jailbreak patterns
- [ ] Add override workflow requiring admin + justification
- [ ] Ensure raw prompt is in-memory only
- [ ] Redact response content before persistence

Tests first:

- [ ] `test_clean_prompt_returns_allow_decision()`
- [ ] `test_email_in_prompt_returns_allow_with_redactions()`
- [ ] `test_phone_in_prompt_returns_allow_with_redactions()`
- [ ] `test_ssn_in_prompt_returns_allow_with_redactions()`
- [ ] `test_injection_attempt_returns_block_decision()`
- [ ] `test_jailbreak_pattern_returns_block_critical_severity()`
- [ ] `test_blocked_decision_never_calls_llm()`
- [ ] `test_all_decisions_write_policy_violations_row()`
- [ ] `test_override_without_admin_role_raises_403()`
- [ ] `test_override_with_admin_role_and_justification_succeeds()`
- [ ] `test_override_creates_policy_overrides_row()`
- [ ] `test_response_pii_redacted_before_persistence()`
- [ ] `test_raw_prompt_sent_to_llm_not_redacted_prompt()`
- [ ] `test_raw_prompt_never_written_to_database()`
- [ ] `test_response_scanned_for_pii_before_persistence()`
- [ ] `test_otel_span_does_not_contain_raw_prompt_text()`
- [ ] `test_otel_span_does_not_contain_response_text()`

### Phase 4: RAG Pipeline

- [ ] Define document upload contract and validation rules
- [ ] Add chunking, embedding, and hybrid retrieval services
- [ ] Persist retrieval runs and retrieval results
- [ ] Add document scan lifecycle states
- [ ] Exclude non-`ACTIVE` documents from indexing and retrieval
- [ ] Add citation formatting in gateway responses

Tests first:

- [ ] `test_chunk_splits_at_correct_size_with_overlap()`
- [ ] `test_embed_returns_1536_dimension_vector()`
- [ ] `test_hybrid_search_returns_semantic_and_keyword_results()`
- [ ] `test_reranker_reorders_results_by_relevance()`
- [ ] `test_retrieval_run_row_created_per_query()`
- [ ] `test_retrieval_results_rows_created_with_rank_and_score()`
- [ ] `test_source_citations_included_in_response()`
- [ ] `test_document_ingest_rejects_oversized_file()`
- [ ] `test_document_ingest_rejects_disallowed_mime_type()`
- [ ] `test_tenant_isolation_retrieval_cannot_cross_tenant()`
- [ ] `test_new_document_starts_in_pending_state()`
- [ ] `test_scan_timeout_sets_status_scan_failed()`
- [ ] `test_scan_failed_document_excluded_from_retrieval()`
- [ ] `test_scan_unknown_treated_same_as_scan_failed()`
- [ ] `test_quarantined_document_never_returned_in_retrieval()`
- [ ] `test_only_active_documents_indexed_by_rag_pipeline()`
- [ ] `test_malware_detected_sets_status_quarantined()`

### Phase 5: Audit Logging and Retention

- [ ] Add audit log persistence model
- [ ] Store hashes for raw-sensitive values instead of plaintext
- [ ] Add envelope encryption for sensitive persisted fields
- [ ] Add model invocation tracking
- [ ] Add retention job and TTL policy

Tests first:

- [ ] `test_audit_log_created_for_every_request()`
- [ ] `test_raw_prompt_never_stored_only_hash_and_redacted()`
- [ ] `test_response_pii_redacted_before_storage()`
- [ ] `test_user_id_and_app_id_stored_in_audit_log()`
- [ ] `test_trace_id_stored_in_audit_log()`
- [ ] `test_ip_stored_as_hash_not_plaintext()`
- [ ] `test_model_invocations_row_created_per_llm_call()`
- [ ] `test_cost_usd_calculated_correctly_from_token_count()`
- [ ] `test_retention_job_deletes_response_logs_after_ttl()`
- [ ] `test_audit_log_query_filtered_by_tenant_id()`
- [ ] `test_audit_log_query_filtered_by_date_range()`

### Phase 6: Observability

- [ ] Add OpenTelemetry tracing bootstrap
- [ ] Generate / propagate `trace_id`
- [ ] Create spans for API, policy, retrieval, provider, and eval
- [ ] Add metrics for latency, errors, and cost
- [ ] Design initial dashboard views

Tests first:

- [ ] `test_trace_id_generated_if_not_provided()`
- [ ] `test_trace_id_propagated_through_all_service_calls()`
- [ ] `test_span_created_for_policy_engine_check()`
- [ ] `test_span_created_for_retrieval_run()`
- [ ] `test_span_created_for_llm_provider_call()`
- [ ] `test_span_includes_provider_and_model_attributes()`
- [ ] `test_error_span_set_on_provider_failure()`
- [ ] `test_golden_signals_metric_latency_recorded()`
- [ ] `test_golden_signals_metric_token_cost_recorded()`

### Phase 7: Evaluation Harness

- [x] Add async Celery evaluation task
- [x] Persist relevance and faithfulness results
- [x] Store retrieval context linkage for faithfulness
- [x] Add judge prompt versioning
- [x] Implement sampling and budget guards
- [x] Add eval job retry/backoff and explicit failed state
- [x] Add eval job read API for operator visibility
- [x] Add task dead-letter persistence for unrecoverable worker failures
- [x] Add dead-letter read API and failed-job requeue path
- [x] Reset daily spend at midnight UTC

Tests first:

- [ ] `test_relevance_scorer_returns_float_0_to_1()`
- [ ] `test_faithfulness_uses_retrieval_context_not_prompt()`
- [ ] `test_faithfulness_detects_claim_not_in_retrieved_chunks()`
- [ ] `test_hallucination_flag_set_when_faithfulness_below_threshold()`
- [ ] `test_judge_prompt_version_stored_with_eval_result()`
- [ ] `test_eval_result_linked_to_retrieval_run_id()`
- [ ] `test_eval_job_does_not_block_gateway_response()`
- [ ] `test_eval_cost_tracked_in_model_invocations()`
- [ ] `test_eval_skipped_when_budget_exceeded()`
- [ ] `test_eval_always_runs_on_policy_violation_regardless_of_budget()`
- [ ] `test_eval_always_runs_on_low_relevance_score()`
- [ ] `test_eval_skipped_when_sampled_out_reason_logged()`
- [ ] `test_eval_spend_incremented_after_judge_call()`
- [ ] `test_eval_spend_reset_to_zero_at_midnight_utc()`
- [ ] `test_gateway_429_when_tenant_monthly_budget_exceeded()`

### Phase 8: Security and Regression

- [ ] Add injection corpus JSON
- [ ] Add multi-tenant security regression tests
- [ ] Add streaming safety tests
- [ ] Add document-ingestion security tests
- [ ] Add cost-guardrail regressions

Tests first:

- [ ] `test_tenant_a_logs_not_visible_to_tenant_b()`
- [ ] `test_tenant_a_documents_not_retrievable_by_tenant_b()`
- [ ] `test_shared_document_requires_explicit_grant()`
- [ ] `test_injection_corpus_all_patterns_blocked()`
- [ ] `test_new_injection_pattern_added_to_corpus_and_blocked()`
- [ ] `test_request_exceeding_max_tokens_rejected()`
- [ ] `test_app_id_over_monthly_budget_rejected_with_429()`
- [ ] `test_expensive_model_blocked_by_policy_for_service_account()`
- [ ] `test_stream_returns_partial_chunks_in_order()`
- [ ] `test_stream_cancellation_closes_provider_connection()`
- [ ] `test_stream_policy_check_runs_before_first_chunk()`
- [ ] `test_file_size_limit_enforced()`
- [ ] `test_disallowed_mime_type_rejected()`
- [ ] `test_malware_scan_hook_called_on_upload()`

## Definition of Done for the Scaffold

- [ ] Backend app starts locally
- [ ] Frontend dev server starts locally
- [ ] Docker Compose launches PostgreSQL and Redis
- [ ] Baseline smoke tests pass
- [ ] The missing spec gaps are resolved before deeper feature work
