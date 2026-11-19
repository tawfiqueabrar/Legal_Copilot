# Legal Copilot — judging brief

## One-line pitch

Legal Copilot turns a contract into a reviewable, privacy-conscious risk assessment: every reported risk points to contract language, every legal source is drawn from a closed authority bank, and unsupported propositions are withheld instead of guessed.

## The problem and the product

Small legal and operations teams often have to spot obligations across long agreements before they can send them to counsel. A generic chatbot can summarize quickly, but its legal citations and clause references are hard to audit. Legal Copilot is a first-pass review workspace that surfaces clause interactions, shows the evidence, checks source support, and leaves legal decisions to qualified people.

## Evidence for the six judging categories

| Criterion | What to show | Honest current evidence / boundary |
|---|---|---|
| Innovation (20%) | Cross-clause risk review plus closed-set, quote-grounded legal statements | The pipeline segments clauses, scans individual and interacting clauses, retrieves source chunks, and passes claims to an independent verifier. Claims without suitable loaded text are omitted with a coverage gap. |
| Technical execution (20%) | Upload → agent trace → risk evidence → authority panel → purge | FastAPI + LangGraph + Next.js implementation. Backend tests and frontend production build passed in the latest local check (114 backend tests; `npm run build`). The latest memo-generation change has not had a live evaluation. |
| Business model + global readiness (20%) | A clear buyer and a staged market path | Customer and pricing are hypotheses, not validated market research. Initial buyer hypothesis: small in-house legal / procurement teams that need a documented first-pass review before counsel. Start with supported source/jurisdiction coverage; expand only after local counsel and source validation. |
| Real-world impact + ethical AI compliance (20%) | Evidence, uncertainty, privacy limits, and human control | Exact contract quotes, backend-only verification labels, abstention, not-assessed gaps, and a purge action are visible. A pilot should measure review time, quote grounding, false-positive review cost, citation support accuracy, and user correction rates before claiming impact. |
| Scalability + NRB collaboration (10%) | A credible operational path and a collaboration role | Current sessions are process-local and intended for a single API worker. Scale only after adding a privacy-reviewed ephemeral session coordinator and deployment controls. NRB / global legal collaborators can help prioritize jurisdiction coverage and review localized workflows; no collaboration is claimed as already secured. |
| Presentation (10%) | A short, evidence-led story with fallback | Use the run of show in `docs/DEMO.md`. Show real backend statuses and a successful purge. Keep a screen recording or screenshots as fallback if providers are unavailable. |

## Three-minute presentation script

**0:00–0:25 — The problem.** “A long agreement can hide risk in the interaction between clauses. A chatbot summary is not enough if a reviewer cannot trace the finding or trust the citation.”

**0:25–0:45 — The product.** “Legal Copilot turns an uploaded document into a preliminary, evidence-linked assessment. It is a first-pass workflow for a human reviewer, not an automated legal opinion.”

**0:45–1:35 — Show the workflow.** Upload `demo/sample_msa.txt`. Point to the live agent trace, then show one single-clause risk and one cross-clause risk. Open the source text at the exact quoted contract span. Do not claim a risk is legally established from contract wording alone.

**1:35–2:10 — Show trust controls.** Open an authority marker. Explain that claims can cite only authority IDs in the bank and that a separate support check must return a verbatim source quote. Show the backend-provided badge. Run `999 U.S. 999`; show Rejected or Unverified, or the explicit unavailable state if lookup cannot run. Never imply a citation lookup alone proves legal support.

**2:10–2:35 — Show responsible handling.** Point out jurisdiction/source gaps and the not-legal-advice notice. Click Delete session and confirm the API purge succeeded. State that providers may process the text needed for their function; this prototype does not claim zero retention by external providers.

**2:35–3:00 — Close with impact and scale.** “Our next validation is a counsel-reviewed pilot measuring review time, quote grounding, false positives, and supported-jurisdiction coverage. Today the app is a tested prototype; before broader deployment we need a live benchmark of the latest memo path and a privacy-reviewed session coordinator.”

## Business model hypothesis — validate before claiming

A plausible starting model is a team subscription for organizations that need repeatable first-pass review, with usage tiers based on document volume and jurisdiction/source coverage. The value proposition to test is reduced time to assemble an evidence-linked issue list for counsel, not replacement of legal review. Validate willingness to pay, acceptable provider/data terms, and review-time savings through interviews and a controlled pilot before publishing prices or ROI claims.

## Pilot scorecard to collect

These are proposed measures, not current results:

- Median time from upload to reviewer-ready issue list, compared with the team's existing first-pass process.
- Quote-grounding rate, checked against source documents by human review.
- Citation support rate, counting only claims that the independent verifier marks Verified and a qualified reviewer confirms.
- Risk precision and recall against a counsel-labeled set, with cross-clause findings reported separately.
- Abstention quality: whether missing jurisdiction/source coverage is surfaced instead of guessed.
- Purge success and document-retention audit results under the selected deployment configuration.

## Deployment and global-readiness path

1. Keep the current single-worker, process-local prototype for the demo; do not imply horizontal scaling today.
2. Before a pilot, document provider data terms, retention settings, secrets handling, TLS, access controls, request-size limits, abuse controls, and operational logging that excludes document contents.
3. Add a privacy-reviewed ephemeral session coordinator with TTL and explicit purge semantics before multiple workers or replicas.
4. Add jurisdictions only with authoritative sources, retrieval metadata, section-level tests, and jurisdiction-specific human review. An English party alone does not establish that EU law applies.
5. Run a counsel-labeled regression set for each supported jurisdiction and publish per-jurisdiction coverage and abstention rates.

## What not to claim in judging

- Do not call the system “hallucination-free”; describe the closed-set and quote-verification controls and their measured limits.
- Do not call the whole product zero-knowledge or promise provider-side zero retention. The app avoids writing client documents to persistent local storage, but configured external providers receive processing inputs.
- Do not present the earlier `backend/eval_results.json` baseline as a result for the latest memo-generation code. A fresh live evaluation is pending.
- Do not say the product establishes compliance, identifies actual violations, replaces counsel, or supports jurisdictions absent from its loaded source library.
