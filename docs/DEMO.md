# Legal Copilot: 3-minute demo

## Before the demo

Start FastAPI from `backend` and Next.js from `frontend`. Confirm the UI health banner says the API is available. Analysis also needs a server-side Gemini key. Citation lookups may require network access. Do not use a client contract; use only `demo/sample_msa.txt`.

**Current accuracy gate:** the corpus includes text for California B&P § 16600, California Civil Code § 1798.100, and GDPR Article 33. A loaded source does not itself make a claim Verified: use only the exact backend status returned for each claim. The current evaluator run has no executed support-check calls, so it supplies no Verified badge for those checks.

## Run of show

### 0:00–0:30 — Upload and privacy

Open Legal Copilot, drag `demo/sample_msa.txt` into the upload card, and start analysis. Point out the accepted file types, upload size limit, volatile session indicator, and visible API/configuration health state.

### 0:30–1:10 — Agent trace

Show the live trace as document ingestion, clause segmentation, jurisdiction review, risk scans, research/authority-bank construction, independent support check, and memo assembly complete. If a provider key or service is unavailable, use the displayed unavailable message and continue with the checked-in offline evaluation output; do not substitute a mock result.

### 1:10–2:00 — Risks and memorandum

Open risk cards and compare their exact quoted spans with the left document pane. For cross-clause findings, use each clause link to show both referenced locations. Open the Evidence gaps section and point to the `[REDACTED]` marker in the sample agreement. Show mitigation text, then scroll to the memorandum and authority bank. Click an `[A#]` marker to reach its source record. Explain that Verified, Existence-only, Unverified, and Rejected badges reflect backend status only. The not-legal-advice notice and preliminary assessment footer stay visible in the memo.

### 2:00–2:30 — Citation probe

Enter `999 U.S. 999` in “Test a citation.” The closed-set verifier should return Rejected or Unverified when it cannot resolve the source; it must never show Verified. If the legal API is unreachable, show the explicit unavailable state. A citation-only lookup never establishes legal support, even when a source record resolves.

### 2:30–3:00 — Evaluation and purge

Open `backend/eval_results.json` or the recorded evaluation table in the README. The recorded run used `gemini-3.1-flash-lite` and reports 25.0% risk recall, 0.0% cross-clause recall, 100.0% quote grounding, 100.0% citation precision, and 0.0% claim verification. Per-statute support-check rows say not run because the evaluator does not isolate those outcomes. Finish by choosing “Delete session” and show the analysis view clear after the API purge succeeds.

## Fallback path

If Gemini or network access is unavailable, show the health banner and API error state, then show the offline fabrication-test result and the blocked/not-run metrics in `backend/eval_results.json`. Do not claim live analysis or citation verification succeeded. If upload worked but analysis failed, delete the session before leaving the demo.
