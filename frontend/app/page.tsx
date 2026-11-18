"use client";

import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const MAX_UPLOAD_BYTES = 25_000_000;

type Status = "verified" | "existence_only" | "unverified" | "rejected";
type Claim = {
  claim_id: string;
  text: string;
  authority_ids: string[];
  clause_quote: string;
  result?: { status: Status; reasons: string[]; authority_quotes: string[] } | null;
};
type Clause = { id: string; heading?: string | null; text: string; page?: number | null; start: number; end: number };
type Authority = {
  id: string;
  key: string;
  kind: string;
  title: string;
  source: string;
  url: string;
  text?: string | null;
  retrieved_at?: string | null;
  status: "resolved" | "existence-only";
};
type Risk = {
  risk_id: string;
  title: string;
  severity: string;
  clause_ids: string[];
  exact_quotes: string[];
  why_non_obvious: string;
  jurisdiction_assumption: string;
  suggested_mitigation_clause: string;
  authority_ids: string[];
  pages: number[];
  contract_evidence: Array<{ clause_id: string; section: string; quote: string }>;
  why_may_matter: string;
  legal_references: Array<{ authority_id: string; status: Status; support_quotes: string[] }>;
  citation_status: Status;
  applicability_note: string;
  citation_check_line: string;
  source_not_loaded: boolean;
};
type LegalSource = { authority_id: string; title: string; source: string; url: string; retrieved_at?: string | null };
type NotAssessed = { name: string; note: string };
type EvidenceGap = { marker: string; clause_ids: string[]; affected_risk_ids: string[]; note: string };
type Memo = {
  title: string;
  document_name: string;
  assessment_line: string;
  legal_sources_in_scope: LegalSource[];
  not_assessed: NotAssessed[];
  executive_summary: string;
  risks: Risk[];
  clauses: Clause[];
  claims: Claim[];
  authority_bank: Authority[];
  coverage_gaps: string[];
  removed_claims: Array<{ claim_id: string; status: Status; reasons: string[] }>;
  evidence_gaps: EvidenceGap[];
  methodology: string;
  notice: string;
  footer: string;
};
type AgentStep = { id: string; label: string; status: "waiting" | "running" | "done" | "failed"; summary?: string };
type CitationProbe = { citation: string; normalized_key?: string | null; result: { status: Status; reasons: string[]; authority_quotes: string[] }; authority?: Authority | null };

const INITIAL_STEPS: AgentStep[] = [
  { id: "ingest", label: "Ingest document", status: "waiting" },
  { id: "segment", label: "Segment clauses", status: "waiting" },
  { id: "detect_jurisdiction", label: "Detect jurisdiction", status: "waiting" },
  { id: "checklist_scan", label: "Checklist risk scan", status: "waiting" },
  { id: "cross_clause_scan", label: "Cross-clause scan", status: "waiting" },
  { id: "research", label: "Research authorities", status: "waiting" },
  { id: "build_bank", label: "Build authority bank", status: "waiting" },
  { id: "draft_memo", label: "Draft memorandum", status: "waiting" },
  { id: "verify", label: "Independent support check", status: "waiting" },
  { id: "finalize", label: "Finalize report", status: "waiting" },
];

const STATUS_LABEL: Record<Status, string> = {
  verified: "Verified",
  existence_only: "Existence-only",
  unverified: "Unverified",
  rejected: "Rejected",
};
const STATUS_STYLE: Record<Status, string> = {
  verified: "border-emerald-300 bg-emerald-50 text-emerald-900",
  existence_only: "border-sky-300 bg-sky-50 text-sky-950",
  unverified: "border-amber-300 bg-amber-50 text-amber-950",
  rejected: "border-rose-300 bg-rose-50 text-rose-950",
};

function formatStatus(status: Status) {
  return STATUS_LABEL[status];
}

function StatusBadge({ status }: { status: Status }) {
  const symbols: Record<Status, string> = { verified: "✓", existence_only: "i", unverified: "?", rejected: "×" };
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_STYLE[status]}`}><span aria-hidden="true" className="font-bold">{symbols[status]}</span>{formatStatus(status)}</span>;
}

function apiError(detail: unknown, fallback: string) {
  if (typeof detail === "string" && detail.trim()) return detail;
  const payload = detail && typeof detail === "object" && "detail" in detail
    ? (detail as { detail?: unknown }).detail
    : detail;
  if (payload && typeof payload === "object") {
    const error = payload as { category?: unknown; exception_class?: unknown; http_status?: unknown; message?: unknown };
    const labels: Record<string, string> = {
      key_invalid: "Gemini key invalid",
      key_invalid_or_access_denied: "Gemini key invalid or access denied",
      model_not_found: "Gemini model not found",
      overloaded: "Gemini overloaded",
      rate_limited: "Gemini rate limited",
      timeout: "Gemini request timed out",
      provider_error: "Gemini unavailable",
    };
    if (typeof error.category === "string") {
      const label = labels[error.category] || `Gemini unavailable (${error.category})`;
      const exceptionClass = typeof error.exception_class === "string" ? error.exception_class : "UnknownException";
      const status = typeof error.http_status === "number" ? `HTTP ${error.http_status}` : "HTTP status unavailable";
      const message = typeof error.message === "string" && error.message.trim() ? error.message : "No provider message was supplied.";
      return `${label} · ${exceptionClass} · ${status} · ${message}`;
    }
    if (typeof error.message === "string" && error.message.trim()) return error.message;
  }
  return fallback;
}

function safeHttpsUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function renderAuthorityMarkers(text: string, authorities: Authority[]) {
  const known = new Set(authorities.map((authority) => authority.id));
  return text.split(/(\[A[1-9][0-9]*\])/g).map((part, index) => {
    const match = /^\[(A[1-9][0-9]*)\]$/.exec(part);
    if (!match || !known.has(match[1])) return <span key={index}>{part}</span>;
    return <a className="font-semibold text-emerald-800 underline decoration-emerald-300 underline-offset-2" href={`#authority-${match[1]}`} key={index}>{part}</a>;
  });
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-slate-500">{children}</h2>;
}

function CitationCheckPanel({ value, setValue, onSubmit, loading, error, probe }: {
  value: string;
  setValue: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  loading: boolean;
  error: string;
  probe: CitationProbe | null;
}) {
  return <section>
    <SectionLabel>Test a citation</SectionLabel>
    <p className="mt-1 text-xs leading-5 text-slate-500">This checks whether a source record resolves. A lookup alone cannot verify a legal proposition.</p>
    <form className="mt-3 flex flex-wrap gap-2" onSubmit={onSubmit}>
      <input className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100" onChange={(event) => setValue(event.target.value)} placeholder="Paste one citation" value={value} />
      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={!value.trim() || loading} type="submit">{loading ? "Checking…" : "Check citation"}</button>
    </form>
    {error && <p role="alert" className="mt-2 text-sm text-rose-800">Citation check unavailable: {error}</p>}
    {probe && <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-sm">{probe.citation}</span><StatusBadge status={probe.result.status} /></div><p className="mt-1 text-xs text-slate-600">{probe.normalized_key || "No supported citation key"}</p>{probe.result.reasons.map((reason, index) => <p className="mt-2 text-xs leading-5 text-slate-700" key={index}>{reason}</p>)}</div>}
  </section>;
}

export default function Home() {
  const [health, setHealth] = useState<"checking" | "ok" | "unavailable" | "unconfigured">("checking");
  const [healthMessage, setHealthMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [textPreview, setTextPreview] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [memo, setMemo] = useState<Memo | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>(INITIAL_STEPS);
  const [working, setWorking] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [verifyInput, setVerifyInput] = useState("");
  const [probe, setProbe] = useState<CitationProbe | null>(null);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyError, setVerifyError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [selectedClause, setSelectedClause] = useState("");
  const dropRef = useRef<HTMLDivElement>(null);
  const clauseRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const authorities = memo?.authority_bank ?? [];
  const clauses = memo?.clauses ?? [];
  const authorityById = useMemo(() => new Map(authorities.map((item) => [item.id, item])), [authorities]);

  useEffect(() => {
    let mounted = true;
    fetch(`${API}/health`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Health check returned ${response.status}`);
        return response.json() as Promise<{ status?: string; analysis_configured?: boolean }>;
      })
      .then((data) => {
        if (!mounted) return;
        if (data.analysis_configured === false) {
          setHealth("unconfigured");
          setHealthMessage("Analysis is unavailable: the server has no configured Gemini key.");
        } else {
          setHealth("ok");
          setHealthMessage("");
        }
      })
      .catch((reason: unknown) => {
        if (!mounted) return;
        setHealth("unavailable");
        setHealthMessage(reason instanceof Error ? reason.message : "The API health check failed.");
      });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!file) {
      setFileUrl("");
      setTextPreview("");
      return;
    }
    const url = URL.createObjectURL(file);
    setFileUrl(url);
    if (file.name.toLowerCase().endsWith(".txt")) {
      file.text().then(setTextPreview).catch(() => setTextPreview("Could not preview this text file in the browser."));
    } else setTextPreview("");
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!sessionId) return;
    const purgeOnClose = () => {
      void fetch(`${API}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE", keepalive: true }).catch(() => undefined);
    };
    window.addEventListener("pagehide", purgeOnClose);
    return () => window.removeEventListener("pagehide", purgeOnClose);
  }, [sessionId]);

  const chooseFile = useCallback((candidate?: File) => {
    setError("");
    if (!candidate) return;
    const extension = candidate.name.toLowerCase().split(".").pop();
    if (!extension || !["txt", "pdf", "docx"].includes(extension)) {
      setError("Choose a .txt, .pdf, or .docx document.");
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setError("This file exceeds the configured 25 MB upload limit.");
      return;
    }
    setFile(candidate);
  }, []);

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0]);
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0]);
  };

  const setStepProgress = (node: string, summary: string) => {
    setSteps((previous) => {
      const currentIndex = previous.findIndex((item) => item.id === node);
      if (currentIndex < 0) return previous;
      return previous.map((item, index) => ({
        ...item,
        status: index < currentIndex ? "done" : index === currentIndex ? "running" : item.status,
        summary: index === currentIndex ? summary : item.summary,
      }));
    });
  };

  const handleSse = async (response: Response) => {
    if (!response.ok) {
      let payload: unknown;
      try { payload = await response.json(); } catch { payload = null; }
      throw new Error(apiError(payload, `Analysis request failed (${response.status}).`));
    }
    if (!response.body) throw new Error("The API returned no analysis event stream.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let gotResult = false;
    const consumeFrame = async (frame: string) => {
      let event = "message";
      const data: string[] = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (!data.length) return;
      let payload: any;
      try { payload = JSON.parse(data.join("\n")); } catch { throw new Error("The API sent an invalid analysis event."); }
      if (event === "progress") {
        const node = String(payload.node || payload.stage || "");
        setStepProgress(node, String(payload.summary || payload.message || "Working"));
      } else if (event === "result") {
        gotResult = true;
      } else if (event === "error") {
        throw new Error(apiError(payload, "Analysis failed. Check the API configuration and try again."));
      }
    };
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";
      for (const frame of frames) await consumeFrame(frame);
      if (done) break;
    }
    if (buffer.trim()) await consumeFrame(buffer);
    if (!gotResult) throw new Error("The analysis stream ended without a memo result.");
  };

  const startAnalysis = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || working) return;
    setWorking(true);
    setError("");
    setMemo(null);
    setProbe(null);
    setSteps(INITIAL_STEPS);
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      const create = await fetch(`${API}/sessions`, { method: "POST", body, cache: "no-store" });
      if (!create.ok) {
        let payload: unknown;
        try { payload = await create.json(); } catch { payload = null; }
        throw new Error(apiError(payload, `Session creation failed (${create.status}).`));
      }
      const session = await create.json() as { session_id?: string };
      if (!session.session_id) throw new Error("The API did not return a session ID.");
      setSessionId(session.session_id);
      await handleSse(await fetch(`${API}/sessions/${encodeURIComponent(session.session_id)}/analyze`, { method: "POST", cache: "no-store" }));
      const memoResponse = await fetch(`${API}/sessions/${encodeURIComponent(session.session_id)}/memo`, { cache: "no-store" });
      if (!memoResponse.ok) {
        let payload: unknown;
        try { payload = await memoResponse.json(); } catch { payload = null; }
        throw new Error(apiError(payload, `Memo retrieval failed (${memoResponse.status}).`));
      }
      const result = await memoResponse.json() as Memo;
      setMemo(result);
      setSteps((previous) => previous.map((item) => ({ ...item, status: "done" })));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Analysis is unavailable.";
      setError(message);
      setSteps((previous) => {
        const active = previous.findIndex((item) => item.status === "running");
        return previous.map((item, index) => index === active ? { ...item, status: "failed", summary: message } : index < active ? { ...item, status: "done" } : item);
      });
    } finally {
      setWorking(false);
    }
  };

  const purgeSession = async () => {
    if (sessionId) {
      setDeleting(true);
      setError("");
      try {
        const response = await fetch(`${API}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE", cache: "no-store" });
        if (!response.ok && response.status !== 404) throw new Error(`Session deletion failed (${response.status}).`);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not delete the session from the API.");
        setDeleting(false);
        return;
      }
      setDeleting(false);
    }
    setSessionId("");
    setMemo(null);
    setFile(null);
    setSteps(INITIAL_STEPS);
    setProbe(null);
    setVerifyError("");
    setDownloadError("");
    setSelectedClause("");
  };

  const testCitation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!verifyInput.trim() || verifyLoading) return;
    setVerifyLoading(true);
    setVerifyError("");
    setProbe(null);
    try {
      const response = await fetch(`${API}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ citation: verifyInput.trim() }),
        cache: "no-store",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiError(payload, `Citation check failed (${response.status}).`));
      setProbe(payload as CitationProbe);
    } catch (reason) {
      setVerifyError(reason instanceof Error ? reason.message : "Citation verification is unavailable.");
    } finally {
      setVerifyLoading(false);
    }
  };

  const downloadMemo = async (format: "docx" | "pdf") => {
    if (!sessionId) return;
    setDownloadError("");
    try {
      const response = await fetch(`${API}/sessions/${encodeURIComponent(sessionId)}/memo.${format}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Memo export unavailable (${response.status}).`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `legal-memorandum.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setDownloadError(reason instanceof Error ? reason.message : "Memo export is unavailable.");
    }
  };

  const jumpToClause = (id: string) => {
    setSelectedClause(id);
    clauseRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const isPdf = file?.name.toLowerCase().endsWith(".pdf");
  const isDocx = file?.name.toLowerCase().endsWith(".docx");

  return (
    <main className="min-h-screen bg-slate-100 text-slate-900">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3 sm:px-8">
        <div>
          <div className="text-lg font-bold tracking-tight">Legal Copilot</div>
          <div className="text-xs text-slate-500">Private, quote-grounded document review</div>
        </div>
        <div className="flex items-center gap-2">
          {sessionId && <button className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-50" disabled={deleting} onClick={() => void purgeSession()} type="button">{deleting ? "Deleting…" : "Delete session"}</button>}
        </div>
      </header>

      {health !== "ok" && <div role="status" className={`border-b px-5 py-3 text-sm ${health === "checking" ? "border-slate-200 bg-slate-50 text-slate-600" : "border-amber-300 bg-amber-50 text-amber-950"}`}>
        {health === "checking" ? "Checking API availability…" : health === "unconfigured" ? healthMessage : `API unavailable: ${healthMessage || "health check failed"}`}
      </div>}

      {error && <div role="alert" className="mx-4 mt-4 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-950 sm:mx-6">{error}</div>}

      {!sessionId ? (
        <section className="mx-auto max-w-3xl px-5 py-14 sm:px-8">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-9">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-emerald-800">Document review</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Review a legal document</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">Upload a contract for clause-level risk analysis, source resolution, and a structured memorandum. Documents stay in volatile session memory and are purged when you delete or close the analysis.</p>
            <form className="mt-7" onSubmit={startAnalysis}>
              <div
                className={`rounded-xl border-2 border-dashed p-8 text-center transition ${dragging ? "border-emerald-600 bg-emerald-50" : "border-slate-300 bg-slate-50"}`}
                onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
                onDrop={onDrop}
                ref={dropRef}
              >
                <div aria-hidden="true" className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-white text-xl text-emerald-800 shadow-sm">↑</div>
                <p className="mt-4 font-semibold">Drop a document here</p>
                <p className="mt-1 text-sm text-slate-500">PDF, DOCX, or plain text · maximum 25 MB</p>
                <label className="mt-5 inline-flex cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold hover:bg-slate-50">
                  Browse files
                  <input accept=".txt,.pdf,.docx,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="sr-only" onChange={onInputChange} type="file" />
                </label>
                {file && <p className="mt-4 break-all text-sm font-medium text-emerald-900">Selected: {file.name} · {(file.size / (1024 * 1024)).toFixed(2)} MB</p>}
              </div>
              {error && !sessionId && <p className="mt-3 text-sm text-rose-800">{error}</p>}
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs leading-5 text-slate-500">Do not upload documents unless your provider settings permit the required data handling.</p>
                <button className="rounded-lg bg-emerald-800 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-900 disabled:cursor-not-allowed disabled:opacity-40" disabled={!file || working || health !== "ok"} type="submit">{working ? "Starting…" : "Start analysis"}</button>
              </div>
            </form>
          </div>
          <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <CitationCheckPanel value={verifyInput} setValue={setVerifyInput} onSubmit={testCitation} loading={verifyLoading} error={verifyError} probe={probe} />
          </div>
        </section>
      ) : (
        <div className="grid gap-4 p-4 lg:h-[calc(100vh-65px)] lg:grid-cols-[minmax(320px,0.9fr)_minmax(420px,1.1fr)] lg:p-5">
          <section className="flex min-h-[55vh] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white lg:min-h-0">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div><h2 className="font-bold">Document</h2><p className="max-w-[60vw] truncate text-xs text-slate-500">{file?.name || "Uploaded document"}</p></div>
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-900">Volatile session</span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto bg-slate-50 p-3">
              {isPdf && fileUrl ? <iframe aria-label="Uploaded PDF preview" className="h-[70vh] w-full rounded border border-slate-200 bg-white lg:h-full" src={fileUrl} />
                : file?.type.startsWith("image/") && fileUrl ? <img alt="Uploaded legal document preview" className="mx-auto max-h-full max-w-full object-contain" src={fileUrl} />
                  : textPreview ? <pre className="whitespace-pre-wrap break-words rounded-lg bg-white p-4 font-mono text-xs leading-5 text-slate-700">{textPreview}</pre>
                    : memo && clauses.length ? <div className="space-y-3">{clauses.map((clause) => <div key={clause.id} ref={(node) => { clauseRefs.current[clause.id] = node; }} className={`rounded-lg border p-3 text-sm ${selectedClause === clause.id ? "border-amber-400 bg-amber-50" : "border-slate-200 bg-white"}`}><div className="mb-2 flex items-center justify-between gap-2"><span className="font-bold">{clause.heading || clause.id}</span>{clause.page && <span className="text-xs text-slate-500">Page {clause.page}</span>}</div><p className="whitespace-pre-wrap leading-6 text-slate-700">{clause.text}</p></div>)}</div>
                      : <div className="grid h-full min-h-64 place-items-center rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm leading-6 text-slate-600">{isDocx ? "DOCX uploaded. Extracted clauses will appear here when analysis is available." : working ? "Reading document in memory…" : "Document preview is unavailable."}</div>}
            </div>
          </section>

          <section className="flex min-h-[70vh] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white lg:min-h-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div><h2 className="font-bold">Analysis and memorandum</h2><p className="text-xs text-slate-500">Session {sessionId.slice(0, 8)}…</p></div>
              <div className="flex gap-2">
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold hover:bg-slate-50 disabled:opacity-40" disabled={!memo} onClick={() => void downloadMemo("docx")} type="button">Download DOCX</button>
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold hover:bg-slate-50 disabled:opacity-40" disabled={!memo} onClick={() => void downloadMemo("pdf")} type="button">Download PDF</button>
              </div>
            </div>
            {downloadError && <p role="alert" className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-900">{downloadError}</p>}
            <div className="min-h-0 flex-1 space-y-7 overflow-auto p-4 sm:p-6">
              <div>
                <div className="mb-3 flex items-center justify-between"><SectionLabel>Agent trace</SectionLabel>{working && <span className="text-xs font-medium text-emerald-800">Analysis running</span>}</div>
                <ol className="grid gap-2 sm:grid-cols-2">
                  {steps.map((step) => <li key={step.id} className="flex gap-3 rounded-lg border border-slate-200 p-3">
                    <span aria-label={step.status} className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-bold ${step.status === "done" ? "border-emerald-700 bg-emerald-700 text-white" : step.status === "running" ? "border-emerald-700 text-emerald-800" : step.status === "failed" ? "border-rose-700 text-rose-800" : "border-slate-300 text-slate-500"}`}>{step.status === "done" ? "✓" : step.status === "failed" ? "×" : step.status === "running" ? "…" : "·"}</span>
                    <div><p className="text-sm font-semibold">{step.label}</p><p className="mt-0.5 text-xs text-slate-500">{step.summary || (step.status === "waiting" ? "Waiting" : step.status)}</p></div>
                  </li>)}
                </ol>
              </div>

              {memo ? <>
                <section>
                  <SectionLabel>Legal memorandum</SectionLabel>
                  <h1 className="mt-2 text-2xl font-bold">{memo.title}</h1>
                  <p className="mt-1 text-sm text-slate-600">Document name: {memo.document_name || "Unavailable"}</p>
                  <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-950">{memo.assessment_line}</p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{renderAuthorityMarkers(memo.executive_summary, authorities)}</p>
                </section>

                <section>
                  <SectionLabel>Legal sources in scope</SectionLabel>
                  {memo.legal_sources_in_scope.length ? <ul className="mt-2 space-y-2">{memo.legal_sources_in_scope.map((source) => {
                    const href = safeHttpsUrl(source.url);
                    return <li className="rounded-lg border border-slate-200 p-3 text-xs" key={source.authority_id}><p className="font-semibold">[{source.authority_id}] {source.title}</p><p className="mt-1 text-slate-500">{source.source} · Retrieved: {source.retrieved_at || "Unavailable"}</p>{href ? <a className="mt-1 inline-block break-all text-emerald-800 underline" href={href} rel="noreferrer" target="_blank">{source.url}</a> : <p className="mt-1 break-all">{source.url || "Source URL unavailable"}</p>}</li>;
                  })}</ul> : <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">No non-empty authority source text was loaded.</p>}
                </section>

                <section>
                  <SectionLabel>Not assessed</SectionLabel>
                  {memo.not_assessed.length ? <ul className="mt-2 space-y-2">{memo.not_assessed.map((item, index) => <li className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm" key={`${item.name}-${index}`}><p className="font-semibold text-amber-950">{item.name}</p><p className="mt-1 text-xs leading-5 text-amber-900">{item.note}</p></li>)}</ul> : <p className="mt-2 text-sm text-slate-600">No additional unassessed jurisdiction or regime was identified.</p>}
                </section>

                <section>
                  <div className="flex items-center justify-between"><SectionLabel>Risk findings</SectionLabel><span className="text-xs text-slate-500">{memo.risks.length} quote-grounded</span></div>
                  {memo.risks.length ? memo.risks.map((risk) => <article className="mt-3 rounded-xl border border-slate-200 p-4" key={risk.risk_id}>
                    <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-bold">{risk.title}</h3><span className="rounded-full border border-orange-300 bg-orange-50 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-orange-950">{risk.severity}</span></div>
                    {risk.contract_evidence.map((evidence, index) => <div className="mt-3" key={`${risk.risk_id}-evidence-${index}`}><p className="text-xs font-semibold text-slate-600">Section <button className="underline underline-offset-2" onClick={() => jumpToClause(evidence.clause_id)} type="button">{evidence.section}</button></p><blockquote className="mt-1 whitespace-pre-wrap border-l-4 border-emerald-700 bg-emerald-50/70 px-3 py-2 text-sm leading-6 text-slate-800">{evidence.quote}</blockquote></div>)}
                    <div className="mt-3"><p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Why this may matter</p><p className="mt-1 text-sm leading-6 text-slate-700">{risk.why_may_matter}</p></div>
                    <div className="mt-3"><p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Legal reference</p>{risk.source_not_loaded && <p className="mt-1 text-sm font-semibold text-amber-900">Source not loaded. No legal proposition is cited or paraphrased from an unavailable source.</p>}{risk.legal_references.map((reference) => <div className="mt-2 rounded-lg border border-slate-200 p-3" key={reference.authority_id}><p className="text-sm font-semibold"><a className="text-emerald-800 underline" href={`#authority-${reference.authority_id}`}>[{reference.authority_id}]</a> <StatusBadge status={reference.status} /></p>{reference.support_quotes.length ? reference.support_quotes.map((quote, index) => <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-slate-400 pl-3 text-xs leading-5 text-slate-700" key={index}>{quote}</blockquote>) : <p className="mt-2 text-xs text-slate-500">No support-check quote was returned.</p>}</div>)}</div>
                    <div className="mt-3 rounded-lg bg-slate-50 p-3"><p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Suggested action</p><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">{risk.suggested_mitigation_clause}</p></div>
                    <div className="mt-3 flex flex-wrap items-center gap-2"><StatusBadge status={risk.citation_status} /><p className="text-xs font-medium text-slate-600">{risk.citation_check_line}</p></div>
                  </article>) : <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">No quote-grounded risk findings were returned.</p>}
                </section>

                <section>
                  <SectionLabel>Claims and support checks</SectionLabel>
                  {memo.claims.length ? memo.claims.map((claim) => <article className="mt-3 rounded-lg border border-slate-200 p-3" key={claim.claim_id}>
                    <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-bold text-slate-500">{claim.claim_id}</span>{claim.result && <StatusBadge status={claim.result.status} />}</div>
                    <p className="mt-2 text-sm leading-6">{renderAuthorityMarkers(claim.text, authorities)}</p>
                    <button className="mt-2 text-left text-xs text-slate-600 underline underline-offset-2" onClick={() => { const clause = clauses.find((item) => item.text.includes(claim.clause_quote)); if (clause) jumpToClause(clause.id); }} type="button">Open supporting contract span</button>
                    {claim.result?.reasons.map((reason, index) => <p className="mt-2 text-xs leading-5 text-slate-600" key={index}>{reason}</p>)}
                    {claim.authority_ids.map((id) => <a className="mr-2 mt-2 inline-block text-xs font-semibold text-emerald-800 underline" href={`#authority-${id}`} key={id}>[{id}]</a>)}
                  </article>) : <p className="mt-3 text-sm text-slate-600">No verified legal claims were returned. Contract-only risks remain visible above.</p>}
                </section>

                <section>
                  <SectionLabel>Authority bank</SectionLabel>
                  {authorities.length ? authorities.map((authority) => {
                    const href = safeHttpsUrl(authority.url);
                    const checks = memo.claims.filter((claim) => claim.authority_ids.includes(authority.id) && claim.result);
                    return <article className="mt-3 scroll-mt-4 rounded-lg border border-slate-200 p-3" id={`authority-${authority.id}`} key={authority.id}>
                      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold"><span className="mr-2 font-mono text-emerald-800">[{authority.id}]</span>{authority.title}</h3><span className={`rounded-full border px-2 py-1 text-xs font-semibold ${authority.status === "resolved" ? "border-slate-300 bg-slate-50 text-slate-800" : STATUS_STYLE.existence_only}`}>Source: {authority.status}</span></div>
                      <p className="mt-1 break-all text-xs text-slate-500">{authority.source} · {authority.key}</p>
                      {href ? <a className="mt-1 inline-block break-all text-xs text-emerald-800 underline" href={href} rel="noreferrer" target="_blank">{authority.url}</a> : <p className="mt-1 break-all text-xs text-slate-500">{authority.url || "Source URL unavailable"}</p>}
                      <p className="mt-1 text-xs text-slate-500">Retrieved: {authority.retrieved_at || "Unavailable"}</p>
                      {checks.length ? checks.map((claim) => <div className="mt-3 border-t border-slate-100 pt-2" key={claim.claim_id}><div className="flex items-center justify-between gap-2"><span className="text-xs text-slate-600">Support check · {claim.claim_id}</span>{claim.result && <StatusBadge status={claim.result.status} />}</div>{claim.result?.authority_quotes.length ? claim.result.authority_quotes.map((quote, index) => <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-slate-400 pl-3 text-xs leading-5 text-slate-700" key={index}>{quote}</blockquote>) : <p className="mt-2 text-xs text-slate-500">No grounded support-check quote returned.</p>}</div>) : <p className="mt-3 text-xs text-slate-500">No memo claim was verified against this authority.</p>}
                    </article>;
                  }) : <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Authority sources are unavailable. No citation is presented as verified.</p>}
                </section>

                {memo.coverage_gaps.length > 0 && <section><SectionLabel>Coverage gaps</SectionLabel><ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-600">{memo.coverage_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></section>}
                {memo.removed_claims.length > 0 && <section><SectionLabel>Removed for failed verification</SectionLabel><ul className="mt-2 space-y-2">{memo.removed_claims.map((claim) => <li className="flex items-center justify-between gap-3 rounded border border-rose-200 bg-rose-50 p-2 text-sm" key={claim.claim_id}><span>{claim.claim_id}: {claim.reasons.join(" ")}</span><StatusBadge status={claim.status} /></li>)}</ul></section>}
                <section><SectionLabel>Evidence gaps</SectionLabel>{memo.evidence_gaps.length ? <ul className="mt-2 space-y-2">{memo.evidence_gaps.map((gap, index) => <li className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" key={`${gap.marker}-${index}`}><p className="font-semibold">{gap.marker} · {gap.clause_ids.length ? gap.clause_ids.join(", ") : "document-level"}</p><p className="mt-1 text-xs leading-5">{gap.note}</p><p className="mt-1 text-xs">Affected findings: {gap.affected_risk_ids.length ? gap.affected_risk_ids.join(", ") : "not linked to a specific finding"}</p></li>)}</ul> : <p className="mt-2 text-sm text-slate-600">No redaction, missing-content, or truncation markers were detected.</p>}</section>
                <CitationCheckPanel value={verifyInput} setValue={setVerifyInput} onSubmit={testCitation} loading={verifyLoading} error={verifyError} probe={probe} />
                <section className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-950">{memo.notice || "Not legal advice. Consult qualified counsel."}<p className="mt-2 font-normal">{memo.footer}</p></section>
              </> : <div className="grid min-h-60 place-items-center text-center text-sm text-slate-500">{working ? "Waiting for the first agent event…" : "The memorandum is unavailable until analysis completes."}</div>}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
