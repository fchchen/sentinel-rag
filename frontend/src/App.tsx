import { startTransition, useEffect, useState } from "react";

const metrics = [
  { label: "Gateway P95", value: "142 ms" },
  { label: "Policy Violations", value: "12" },
  { label: "Eval Spend", value: "$4.72" },
  { label: "Quarantined Docs", value: "3" },
];

const demoTokenKey = "sentinel-rag-demo-token";

type Viewer = {
  user_id: string;
  tenant_id: string;
  roles: string[];
};

type AuthState = {
  mode: "loading" | "authenticated" | "fallback";
  viewer: Viewer | null;
};

type DocumentItem = {
  id: string;
  tenant_id: string;
  filename: string;
  status: string;
};

type RetrievalRunItem = {
  id: string;
  app_id: string;
  query_text: string;
  result_count: number;
};

type EvalItem = {
  id: number;
  retrieval_run_id: string;
  judge_version: string;
  relevance_score: number;
  faithfulness_score: number;
  hallucination_flag: boolean;
  status: string;
  skip_reason: string | null;
};

type EvalJobItem = {
  id: number;
  retrieval_run_id: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  last_error: string | null;
  next_attempt_at: string | null;
};

type EvalDeadLetterItem = {
  id: number;
  job_id: number | null;
  task_name: string;
  payload_json: string;
  error_message: string;
  retry_count: number;
  created_at: string;
};

type CostProvider = {
  provider: string;
  cost_usd: number;
};

type CostSummary = {
  total_cost_usd: number;
  providers: CostProvider[];
};

const fallbackDocuments: DocumentItem[] = [
  { id: "doc-1", tenant_id: "tenant-a", filename: "guide.pdf", status: "ACTIVE" },
  { id: "doc-2", tenant_id: "tenant-a", filename: "invoice.pdf", status: "QUARANTINED" },
];

const fallbackRuns: RetrievalRunItem[] = [
  { id: "run-1", app_id: "console", query_text: "show me the guide", result_count: 1 },
  { id: "run-2", app_id: "console", query_text: "billing invoice", result_count: 2 },
];

const fallbackEvals: EvalItem[] = [
  {
    id: 1,
    retrieval_run_id: "run-1",
    judge_version: "heuristic_v1",
    relevance_score: 0.91,
    faithfulness_score: 0.82,
    hallucination_flag: false,
    status: "COMPLETED",
    skip_reason: null,
  },
  {
    id: 2,
    retrieval_run_id: "run-2",
    judge_version: "heuristic_v1",
    relevance_score: 0.44,
    faithfulness_score: 0.0,
    hallucination_flag: false,
    status: "SKIPPED",
    skip_reason: "sampled_out",
  },
];

const fallbackCosts: CostSummary = {
  total_cost_usd: 0.0048,
  providers: [
    { provider: "azure_openai", cost_usd: 0.0031 },
    { provider: "anthropic", cost_usd: 0.0017 },
  ],
};

const fallbackEvalJobs: EvalJobItem[] = [
  {
    id: 11,
    retrieval_run_id: "run-2",
    status: "RETRY",
    attempt_count: 1,
    max_attempts: 3,
    last_error: "redis down",
    next_attempt_at: "2026-03-03T18:00:00Z",
  },
  {
    id: 10,
    retrieval_run_id: "run-1",
    status: "COMPLETED",
    attempt_count: 0,
    max_attempts: 3,
    last_error: null,
    next_attempt_at: null,
  },
];

const fallbackDeadLetters: EvalDeadLetterItem[] = [
  {
    id: 1,
    job_id: 11,
    task_name: "sentinel_rag.process_eval_job",
    payload_json: "{\"job_id\":11,\"args\":[11],\"kwargs\":{}}",
    error_message: "worker crashed",
    retry_count: 2,
    created_at: "2026-03-03T18:02:00Z",
  },
];

export default function App() {
  const [authState, setAuthState] = useState<AuthState>({ mode: "loading", viewer: null });
  const [documents, setDocuments] = useState<DocumentItem[]>(fallbackDocuments);
  const [runs, setRuns] = useState<RetrievalRunItem[]>(fallbackRuns);
  const [evals, setEvals] = useState<EvalItem[]>(fallbackEvals);
  const [evalJobs, setEvalJobs] = useState<EvalJobItem[]>(fallbackEvalJobs);
  const [deadLetters, setDeadLetters] = useState<EvalDeadLetterItem[]>(fallbackDeadLetters);
  const [costs, setCosts] = useState<CostSummary>(fallbackCosts);
  const [expandedDeadLetterId, setExpandedDeadLetterId] = useState<number | null>(null);
  const [requeueingJobId, setRequeueingJobId] = useState<number | null>(null);
  const [operatorMessage, setOperatorMessage] = useState<string | null>(null);

  useEffect(() => {
    void loadDashboard();
  }, []);

  async function loadDashboard() {
    const token = await getOrCreateDemoToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    const viewer = token ? await fetchViewer(headers) : null;

    const [documentResponse, retrievalResponse, evalResponse, evalJobsResponse, deadLetterResponse, costResponse] = token
      ? await Promise.allSettled([
          fetch("/api/v1/documents", { headers }),
          fetch("/api/v1/retrieval/runs", { headers }),
          fetch("/api/v1/evals", { headers }),
          fetch("/api/v1/evals/jobs", { headers }),
          fetch("/api/v1/evals/dead-letters", { headers }),
          fetch("/api/v1/metrics/costs", { headers }),
        ])
      : await Promise.allSettled([
          Promise.resolve(null),
          Promise.resolve(null),
          Promise.resolve(null),
          Promise.resolve(null),
          Promise.resolve(null),
          Promise.resolve(null),
        ]);

    const nextDocuments =
      documentResponse.status === "fulfilled" &&
      documentResponse.value &&
      documentResponse.value.ok
        ? ((await documentResponse.value.json()) as { items: DocumentItem[] }).items
        : null;
    const nextRuns =
      retrievalResponse.status === "fulfilled" &&
      retrievalResponse.value &&
      retrievalResponse.value.ok
        ? ((await retrievalResponse.value.json()) as { items: RetrievalRunItem[] }).items
        : null;
    const nextEvals =
      evalResponse.status === "fulfilled" &&
      evalResponse.value &&
      evalResponse.value.ok
        ? ((await evalResponse.value.json()) as { items: EvalItem[] }).items
        : null;
    const nextEvalJobs =
      evalJobsResponse.status === "fulfilled" &&
      evalJobsResponse.value &&
      evalJobsResponse.value.ok
        ? ((await evalJobsResponse.value.json()) as { items: EvalJobItem[] }).items
        : null;
    const nextDeadLetters =
      deadLetterResponse.status === "fulfilled" &&
      deadLetterResponse.value &&
      deadLetterResponse.value.ok
        ? ((await deadLetterResponse.value.json()) as { items: EvalDeadLetterItem[] }).items
        : null;
    const nextCosts =
      costResponse.status === "fulfilled" &&
      costResponse.value &&
      costResponse.value.ok
        ? ((await costResponse.value.json()) as CostSummary)
        : null;

    startTransition(() => {
      setAuthState({
        mode: viewer ? "authenticated" : "fallback",
        viewer,
      });
      if (nextDocuments) {
        setDocuments(nextDocuments);
      }
      if (nextRuns) {
        setRuns(nextRuns);
      }
      if (nextEvals) {
        setEvals(nextEvals);
      }
      if (nextEvalJobs) {
        setEvalJobs(nextEvalJobs);
      }
      if (nextDeadLetters) {
        setDeadLetters(nextDeadLetters);
      }
      if (nextCosts) {
        setCosts(nextCosts);
      }
    });
  }

  async function getOrCreateDemoToken(): Promise<string | null> {
    const cached = window.localStorage.getItem(demoTokenKey);
    if (cached) {
      const viewer = await fetchViewer({ Authorization: `Bearer ${cached}` });
      if (viewer) {
        return cached;
      }
      window.localStorage.removeItem(demoTokenKey);
    }

    const response = await fetch("/api/v1/auth/demo", { method: "POST" });
    if (!response.ok) {
      return null;
    }

    const payload = (await response.json()) as { access_token: string };
    window.localStorage.setItem(demoTokenKey, payload.access_token);
    return payload.access_token;
  }

  async function fetchViewer(headers: HeadersInit): Promise<Viewer | null> {
    const response = await fetch("/api/v1/auth/me", { headers });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as Viewer;
  }

  async function requeueDeadLetter(item: EvalDeadLetterItem): Promise<void> {
    if (!item.job_id) {
      setOperatorMessage("Dead letter has no linked job to requeue.");
      return;
    }

    setRequeueingJobId(item.job_id);
    setOperatorMessage(null);

    try {
      const token = await getOrCreateDemoToken();
      if (!token) {
        setOperatorMessage("Authentication unavailable for requeue.");
        return;
      }

      const response = await fetch(`/api/v1/evals/jobs/${item.job_id}/requeue`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) {
        setOperatorMessage(`Requeue failed (${response.status}).`);
        return;
      }

      const payload = (await response.json()) as { accepted: boolean; queued: boolean };
      if (!payload.accepted) {
        setOperatorMessage(`Job ${item.job_id} was not eligible for requeue.`);
        return;
      }

      setOperatorMessage(
        payload.queued
          ? `Job ${item.job_id} requeued and dispatched.`
          : `Job ${item.job_id} requeued for inline processing.`,
      );
      await loadDashboard();
    } finally {
      setRequeueingJobId(null);
    }
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div className="hero-strip">
          <div>
            <p className="eyebrow">sentinel-rag</p>
            <h1>Enterprise RAG governance starts here.</h1>
          </div>
          <div className={`auth-pill auth-${authState.mode}`}>
            {authState.mode === "authenticated"
              ? `${authState.viewer?.user_id} / ${authState.viewer?.tenant_id}`
              : authState.mode === "loading"
                ? "Connecting..."
                : "Fallback preview"}
          </div>
        </div>
        <p className="lede">
          This scaffold ships a minimal operator dashboard shell while the
          gateway, policy engine, and eval pipeline are built out test-first.
        </p>
      </section>
      <section className="metrics-grid" aria-label="Operational metrics">
        {metrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <p className="metric-label">{metric.label}</p>
            <p className="metric-value">{metric.value}</p>
          </article>
        ))}
      </section>
      <section className="data-panels" aria-label="Stored documents and retrieval runs">
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Documents</p>
            <h2>Tenant Inventory</h2>
          </div>
          <div className="list-shell">
            {documents.map((document) => (
              <div className="list-row" key={document.id}>
                <div>
                  <p className="list-title">{document.filename}</p>
                  <p className="list-meta">{document.tenant_id}</p>
                </div>
                <span className={`status-pill status-${document.status.toLowerCase()}`}>
                  {document.status}
                </span>
              </div>
            ))}
          </div>
        </article>
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Retrieval</p>
            <h2>Recent Search Runs</h2>
          </div>
          <div className="list-shell">
            {runs.map((run) => (
              <div className="list-row" key={run.id}>
                <div>
                  <p className="list-title">{run.query_text}</p>
                  <p className="list-meta">{run.app_id}</p>
                </div>
                <span className="result-count">{run.result_count} hits</span>
              </div>
            ))}
          </div>
        </article>
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Evaluation</p>
            <h2>Recent Eval Results</h2>
          </div>
          <div className="list-shell">
            {evals.map((item) => (
              <div className="list-row" key={item.id}>
                <div>
                  <p className="list-title">{item.judge_version}</p>
                  <p className="list-meta">
                    {item.retrieval_run_id}
                    {item.skip_reason ? ` · ${item.skip_reason}` : ""}
                  </p>
                </div>
                <span className={`status-pill ${evalStatusClass(item)}`}>
                  {item.status === "SKIPPED"
                    ? item.status
                    : `F ${item.faithfulness_score.toFixed(2)}`}
                </span>
              </div>
            ))}
          </div>
        </article>
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Queue</p>
            <h2>Eval Job States</h2>
          </div>
          <div className="list-shell">
            {evalJobs.map((job) => (
              <div className="list-row" key={job.id}>
                <div>
                  <p className="list-title">Job {job.id}</p>
                  <p className="list-meta">
                    {job.retrieval_run_id}
                    {job.last_error ? ` · ${job.last_error}` : ""}
                  </p>
                </div>
                <span className={`status-pill ${evalJobStatusClass(job.status)}`}>
                  {job.status} {job.attempt_count}/{job.max_attempts}
                </span>
              </div>
            ))}
          </div>
        </article>
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Failures</p>
            <h2>Dead Letters</h2>
          </div>
          {operatorMessage ? <p className="panel-message">{operatorMessage}</p> : null}
          <div className="list-shell">
            {deadLetters.map((item) => (
              <div className="list-row dead-letter-row" key={item.id}>
                <div className="dead-letter-copy">
                  <div>
                    <p className="list-title">{item.task_name}</p>
                    <p className="list-meta">
                      Job {item.job_id ?? "n/a"} · {item.error_message}
                    </p>
                    <p className="list-meta">{new Date(item.created_at).toLocaleString()}</p>
                  </div>
                  {expandedDeadLetterId === item.id ? (
                    <pre className="payload-preview">{formatPayload(item.payload_json)}</pre>
                  ) : null}
                </div>
                <div className="row-actions">
                  <button
                    type="button"
                    className="action-button"
                    onClick={() =>
                      setExpandedDeadLetterId((current) => (current === item.id ? null : item.id))
                    }
                  >
                    {expandedDeadLetterId === item.id ? "Hide payload" : "Review payload"}
                  </button>
                  <button
                    type="button"
                    className="action-button action-button-primary"
                    disabled={!item.job_id || requeueingJobId === item.job_id}
                    onClick={() => {
                      void requeueDeadLetter(item);
                    }}
                  >
                    {requeueingJobId === item.job_id ? "Requeueing..." : "Requeue"}
                  </button>
                  <span className="result-count">retry {item.retry_count}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
        <article className="data-card">
          <div className="panel-header">
            <p className="panel-eyebrow">Cost</p>
            <h2>Model Spend</h2>
          </div>
          <div className="cost-total">${costs.total_cost_usd.toFixed(4)}</div>
          <div className="list-shell">
            {costs.providers.map((provider) => (
              <div className="list-row" key={provider.provider}>
                <div>
                  <p className="list-title">{provider.provider}</p>
                  <p className="list-meta">Accumulated provider spend</p>
                </div>
                <span className="result-count">${provider.cost_usd.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}

function evalStatusClass(item: EvalItem): string {
  if (item.status === "SKIPPED") {
    return "status-pending";
  }
  return item.hallucination_flag ? "status-quarantined" : "status-active";
}

function evalJobStatusClass(status: string): string {
  if (status === "COMPLETED") {
    return "status-active";
  }
  if (status === "FAILED") {
    return "status-quarantined";
  }
  return "status-pending";
}

function formatPayload(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
