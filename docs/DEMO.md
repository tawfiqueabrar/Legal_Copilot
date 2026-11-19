# Legal Copilot: 3-minute demo

Use [SUBMISSION_BRIEF.md](SUBMISSION_BRIEF.md) for judging-criterion mapping and the complete pitch script.

## Before the demo

Start FastAPI from `backend` and Next.js from `frontend`. Confirm the UI health banner says the API is available. Analysis also needs a server-side Gemini key. Citation lookups may require network access. Do not use a client contract; use only `demo/sample_msa.txt`.

**Accuracy gate:** the recorded live baseline predates the current source-grounded memo-generation change. It recorded six claims; one received Verified. Do not present those values as performance of the latest code. Never promise or stage a Verified badge. If the application displays one during the demo, confirm its backend status and show the exact authority and support quote. The source-identity smoke tests in eval_results.json are not substantive legal conclusions.

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

If you show `backend/eval_results.json`, label it clearly as the earlier live baseline, not the current code. It used `gemini-3.1-flash-lite` (temperature 0 requested; no fallback): strict risk recall 6/8, section-match recall 8/8, cross-clause recall 3/5, quote grounding 50/50, distinct authority IDs found in bank 5/5, claim verification 1/6, and the fabrication test rejected `999 U.S. 999`. Bank membership does not show legal relevance or support. The current memo-generation change has not had a live evaluation. A separate `gemini-3.6-flash` trial was not scoreable because analysis returned HTTP 503 and then HTTP 429 free-tier quota errors. Finish by choosing “Delete session” and show the analysis view clear after the API purge succeeds.

## Fallback path

If Gemini or network access is unavailable, show the health banner and API error state, then show the offline fabrication-test result and the blocked/not-run metrics in `backend/eval_results.json`. Do not claim live analysis or citation verification succeeded. If upload worked but analysis failed, delete the session before leaving the demo.
