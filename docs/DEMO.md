# Legal Copilot: 3-minute demo

## Before the demo

Start FastAPI from `backend` and Next.js from `frontend`. Confirm the UI health banner says the API is available. Analysis also needs a server-side Gemini key. Citation lookups may require network access. Do not use a client contract; use only `demo/sample_msa.txt`.

**Current accuracy gate:** the statute corpus does not contain text for the California B&P section or California Civil Code privacy section. Their support check is currently **BLOCKED: statute text not loaded**. Do not present a Verified badge for either authority. If the corpus is populated later from an allowed source, show the label returned by the backend; if the backend returns Existence-only or Unverified, show that actual label.

## Run of show

### 0:00–0:30 — Upload and privacy

Open Legal Copilot, drag `demo/sample_msa.txt` into the upload card, and start analysis. Point out the accepted file types, upload size limit, volatile session indicator, and visible API/configuration health state.

### 0:30–1:10 — Agent trace

Show the live trace as document ingestion, clause segmentation, jurisdiction review, risk scans, research/authority-bank construction, independent support check, and memo assembly complete. If a provider key or service is unavailable, use the displayed unavailable message and continue with the checked-in offline evaluation output; do not substitute a mock result.

### 1:10–2:00 — Risks and memorandum

Open risk cards and compare their exact quoted spans with the left document pane. For cross-clause findings, use each clause link to show both referenced locations. Show mitigation text, then scroll to the memorandum and authority bank. Click an `[A#]` marker to reach its source record. Explain that Verified, Existence-only, Unverified, and Rejected badges reflect backend status only. The not-legal-advice notice stays visible in the memo.

### 2:00–2:30 — Citation probe

Enter `999 U.S. 999` in “Test a citation.” The closed-set verifier should return Rejected or Unverified when it cannot resolve the source; it must never show Verified. If the legal API is unreachable, show the explicit unavailable state. A citation-only lookup never establishes legal support, even when a source record resolves.

### 2:30–3:00 — Evaluation and purge

Open `backend/eval_results.json` or the recorded evaluation table in the README. Current live pipeline metrics are marked not run when provider keys are absent; statute-text-dependent checks are marked **BLOCKED: statute text not loaded**. Finish by choosing “Delete session” and show the analysis view clear after the API purge succeeds.

## Fallback path

If Gemini or network access is unavailable, show the health banner and API error state, then show the offline fabrication-test result and the blocked/not-run metrics in `backend/eval_results.json`. Do not claim live analysis or citation verification succeeded. If upload worked but analysis failed, delete the session before leaving the demo.
