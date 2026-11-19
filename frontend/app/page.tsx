"use client";

import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";

const CONFIGURED_API = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
const API = process.env.NODE_ENV === "development"
  ? (CONFIGURED_API || "http://localhost:8000")
  : CONFIGURED_API ? "/backend" : "";
const MAX_UPLOAD_BYTES = 25_000_000;

type Risk = {
  risk_id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  clause_refs: Array<{ id: string; section: string; page?: number | null }>;
  exact_quotes: string[];
  why_non_obvious: string;
  suggested_action: string;
};
type RiskReview = {
  document_name: string;
  risks: Risk[];
  warnings: string[];
  notice: string;
};

function messageFrom(payload: unknown, fallback: string) {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (payload && typeof payload === "object") {
    const data = payload as { detail?: unknown; message?: unknown; category?: unknown; http_status?: unknown };
    const detail = data.detail && typeof data.detail === "object" ? data.detail as typeof data : data;
    if (typeof detail.message === "string" && detail.message.trim()) {
      const category = typeof detail.category === "string" ? `${detail.category}: ` : "";
      const status = typeof detail.http_status === "number" ? ` (HTTP ${detail.http_status})` : "";
      return `${category}${detail.message}${status}`;
    }
    if (typeof data.detail === "string") return data.detail;
  }
  return fallback;
}

function StatusPill({ status }: { status: Risk["severity"] }) {
  const styles: Record<Risk["severity"], string> = {
    critical: "border-red-300 bg-red-50 text-red-900",
    high: "border-orange-300 bg-orange-50 text-orange-900",
    medium: "border-amber-300 bg-amber-50 text-amber-900",
    low: "border-slate-300 bg-slate-50 text-slate-700",
  };
  return <span className={`rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wide ${styles[status]}`}>{status}</span>;
}

function downloadRiskReport(review: RiskReview) {
  const sections = review.risks.map((risk, index) => [
    `${index + 1}. ${risk.title}`,
    `Severity: ${risk.severity.toUpperCase()}`,
    `Sections: ${risk.clause_refs.map((item) => `${item.section} (${item.id})${item.page ? `, page ${item.page}` : ""}`).join("; ") || "Not identified"}`,
    "Contract evidence:",
    ...risk.exact_quotes.map((quote) => `  “${quote}”`),
    `Why it may matter: ${risk.why_non_obvious}`,
    `Suggested action: ${risk.suggested_action}`,
  ].join("\n")).join("\n\n");
  const report = [
    "LEGAL COPILOT",
    "PRELIMINARY CONTRACT RISK ASSESSMENT",
    "=".repeat(42),
    `Document: ${review.document_name}`,
    `Assessment: ${review.risks.length} potential risk${review.risks.length === 1 ? "" : "s"} identified; no legal violation established.`,
    "",
    "RISK FINDINGS",
    "-".repeat(42),
    sections || "No quote-grounded risks were identified in the reviewed text.",
    review.warnings.length ? `\n\nREVIEW NOTES\n${review.warnings.map((warning) => `- ${warning}`).join("\n")}` : "",
    "",
    "This report does not establish an actual violation or provide a final legal opinion.",
    review.notice,
  ].filter(Boolean).join("\n");
  const blob = new Blob([report], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeName = review.document_name.replace(/[^a-z0-9._-]+/gi, "_").replace(/^_+|_+$/g, "") || "document";
  link.href = url;
  link.download = `${safeName}-risk-assessment.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [review, setReview] = useState<RiskReview | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<"checking" | "ready" | "unavailable" | "unconfigured">("checking");
  const [healthText, setHealthText] = useState("Checking analysis service…");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("Ready for a document");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const checkHealth = useCallback(async () => {
    if (!API) {
      setHealth("unavailable");
      setHealthText("Backend URL is not configured for this deployment.");
      return;
    }
    try {
      const response = await fetch(`${API}/health`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Backend returned HTTP ${response.status}`);
      const body = await response.json() as { analysis_configured?: boolean };
      if (body.analysis_configured === false) {
        setHealth("unconfigured");
        setHealthText("Backend is online, but its model API key is not configured.");
      } else {
        setHealth("ready");
        setHealthText("Analysis service is ready.");
      }
    } catch (reason) {
      setHealth("unavailable");
      setHealthText(reason instanceof Error ? reason.message : "Could not connect to the backend.");
    }
  }, []);

  useEffect(() => { void checkHealth(); }, [checkHealth]);

  useEffect(() => {
    if (!sessionId) return;
    const purgeOnClose = () => {
      void fetch(`${API}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE", keepalive: true }).catch(() => undefined);
    };
    window.addEventListener("pagehide", purgeOnClose);
    return () => window.removeEventListener("pagehide", purgeOnClose);
  }, [sessionId]);

  const chooseFile = (candidate?: File) => {
    setError("");
    setReview(null);
    if (!candidate) return;
    const extension = candidate.name.toLowerCase().split(".").pop();
    if (!extension || !["txt", "pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff"].includes(extension)) {
      setFile(null);
      setError("Choose a PDF, DOCX, TXT, PNG, JPEG, or TIFF file.");
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setFile(null);
      setError("The file exceeds the 25 MB upload limit.");
      return;
    }
    setFile(candidate);
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0]);
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0]);
  };

  const purgePrevious = async () => {
    if (!sessionId) return;
    const response = await fetch(`${API}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE", cache: "no-store" });
    if (!response.ok && response.status !== 404) throw new Error(`Could not clear the previous session (HTTP ${response.status}).`);
    setSessionId("");
  };

  const startReview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setReview(null);
    setProgress("Uploading document");
    try {
      await purgePrevious();
      const form = new FormData();
      form.append("file", file, file.name);
      const created = await fetch(`${API}/sessions`, { method: "POST", body: form, cache: "no-store" });
      if (!created.ok) {
        let body: unknown;
        try { body = await created.json(); } catch { body = null; }
        throw new Error(messageFrom(body, `Upload failed (HTTP ${created.status}).`));
      }
      const createdBody = await created.json() as { session_id?: string };
      if (!createdBody.session_id) throw new Error("The backend did not return a session ID.");
      const id = createdBody.session_id;
      setSessionId(id);
      setProgress("Reading document and checking risks");
      const response = await fetch(`${API}/sessions/${encodeURIComponent(id)}/analyze?mode=risks`, { method: "POST", cache: "no-store" });
      if (!response.ok || !response.body) {
        let body: unknown;
        try { body = await response.json(); } catch { body = null; }
        throw new Error(messageFrom(body, `Analysis could not start (HTTP ${response.status}).`));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed: RiskReview | null = null;
      const consume = (frame: string) => {
        let eventName = "message";
        const data: string[] = [];
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).trim());
        }
        if (!data.length) return;
        let body: any;
        try { body = JSON.parse(data.join("\n")); } catch { throw new Error("The analysis service returned an unreadable response."); }
        if (eventName === "progress") {
          setProgress(String(body.summary || body.message || "Checking the document"));
        } else if (eventName === "result") {
          completed = body as RiskReview;
        } else if (eventName === "error") {
          throw new Error(messageFrom(body, "Risk review could not be completed."));
        }
      };
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) consume(frame);
        if (chunk.done) break;
      }
      if (buffer.trim()) consume(buffer);
      if (!completed) throw new Error("The analysis stream ended without a risk result.");
      setReview(completed);
      setProgress("Risk review complete");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Risk review is unavailable.");
      setProgress("Could not complete the review");
    } finally {
      setBusy(false);
    }
  };

  const deleteSession = async () => {
    try {
      await purgePrevious();
      setReview(null);
      setError("");
      setProgress("Session deleted");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the session.");
    }
  };

  return <main className="min-h-screen bg-[#f5f8f6] text-slate-900">
    <header className="sticky top-0 z-10 flex h-[68px] items-center justify-between border-b border-emerald-950/10 bg-white px-5 sm:px-8">
      <a href="#home" className="flex items-center gap-3" aria-label="Legal Copilot home">
        <Image src="/legal-copilot-logo.webp" alt="" width={48} height={48} priority className="h-11 w-11 object-contain" />
        <span><strong className="block text-base">Legal Copilot</strong><span className="text-xs text-slate-500">Contract risk review</span></span>
      </a>
      <div className="flex items-center gap-3">
        <span className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${health === "ready" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{health === "ready" ? "● Service ready" : health === "checking" ? "Checking service" : "Service unavailable"}</span>
        {sessionId && <button type="button" onClick={() => void deleteSession()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold hover:bg-slate-50">Delete session</button>}
      </div>
    </header>

    {(health !== "ready" || error) && <div role={error ? "alert" : "status"} className={`border-b px-5 py-3 text-sm sm:px-8 ${error || health === "unavailable" || health === "unconfigured" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      <div className="mx-auto flex max-w-4xl items-center justify-between gap-4"><span>{error || healthText}</span>{error && <button type="button" onClick={() => void checkHealth()} className="shrink-0 font-semibold underline">Check service</button>}</div>
    </div>}

    <div id="home" className="mx-auto grid max-w-5xl gap-8 px-5 py-10 sm:px-8 sm:py-14">
      <section className="max-w-2xl">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-800">Document review</p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Find the contract terms worth a closer look.</h1>
        <p className="mt-4 text-sm leading-6 text-slate-600">Upload a contract to identify up to three potential risks, each linked to exact wording in the document.</p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
        <form onSubmit={startReview}>
          <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
            className={`flex min-h-48 flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 text-center transition ${dragging ? "border-emerald-600 bg-emerald-50" : "border-slate-300 bg-slate-50"}`}>
            <span className="grid h-11 w-11 place-items-center rounded-full bg-white text-xl text-emerald-800 shadow-sm" aria-hidden="true">↑</span>
            <p className="mt-3 font-semibold">{file ? file.name : "Drop a document here"}</p>
            <p className="mt-1 text-xs text-slate-500">PDF, DOCX, TXT, or scanned image · maximum 25 MB</p>
            {file && <p className="mt-1 text-xs text-slate-500">{(file.size / 1_000_000).toFixed(2)} MB</p>}
            <input ref={inputRef} type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg,image/tiff" onChange={onFileChange} className="sr-only" />
            <button type="button" onClick={() => inputRef.current?.click()} className="mt-4 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-100">Choose file</button>
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-xl text-xs leading-5 text-slate-500">Potential issues only. Do not upload confidential documents unless your model provider’s data terms allow it.</p>
            <button type="submit" disabled={!file || busy || health !== "ready"} className="rounded-lg bg-emerald-900 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-45">{busy ? "Reviewing…" : "Find risks"}</button>
          </div>
        </form>
        {busy && <p role="status" className="mt-4 flex items-center gap-2 text-sm font-medium text-emerald-900"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-600" />{progress}</p>}
      </section>

      {review && <section id="risk-report" aria-live="polite" className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-4"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-800">Preliminary contract risk assessment</p><h2 className="mt-1 text-2xl font-bold">{review.risks.length} potential risk{review.risks.length === 1 ? "" : "s"} identified</h2><p className="mt-1 text-sm text-slate-600">Potential risks found; no legal violation established.</p><p className="mt-2 max-w-xl break-words text-sm text-slate-500">Document: {review.document_name}</p></div><div className="screen-only flex flex-wrap gap-2"><button type="button" onClick={() => downloadRiskReport(review)} className="rounded-lg bg-emerald-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-800">Download report</button><button type="button" onClick={() => window.print()} className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold hover:bg-slate-50">Print / save PDF</button></div></div>
        {review.risks.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-700">No risks passed the exact-quote checks. The system has not added unsupported findings.</p>}
        {review.risks.map((risk) => <article key={risk.risk_id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><h3 className="max-w-3xl text-lg font-bold">{risk.title}</h3><StatusPill status={risk.severity} /></div>
          <p className="mt-3 text-sm leading-6 text-slate-700"><strong>Sections:</strong> {risk.clause_refs.map((item) => `${item.section} (${item.id})${item.page ? `, page ${item.page}` : ""}`).join("; ")}</p>
          <div className="mt-3 space-y-2">{risk.exact_quotes.map((quote, index) => <blockquote key={index} className="border-l-2 border-emerald-700 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-800">“{quote}”</blockquote>)}</div>
          <p className="mt-4 text-sm leading-6 text-slate-700"><strong>Why it may matter:</strong> {risk.why_non_obvious}</p>
          <p className="mt-3 text-sm leading-6 text-slate-700"><strong>Suggested action:</strong> {risk.suggested_action}</p>
        </article>)}
        {review.warnings.map((warning, index) => <p key={index} className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">{warning}</p>)}
        <div className="border-t border-slate-200 pt-4 text-xs leading-5 text-slate-500"><p>This report does not establish an actual violation or provide a final legal opinion.</p><p className="mt-1">{review.notice}</p></div>
      </section>}

      {!review && !busy && <p className="text-xs leading-5 text-slate-500">Findings are based on the document text and may depend on facts or jurisdiction. Review important terms with qualified counsel.</p>}
    </div>
  </main>;
}
