# Legal Copilot

Privacy-first legal document analysis starter built with FastAPI, LangGraph, Gemini or optional Groq inference, ephemeral Qdrant, and Next.js.

For the six judging criteria, a truthful three-minute pitch, proposed pilot metrics, and deployment boundaries, see [the submission brief](docs/SUBMISSION_BRIEF.md). The current code has not had a live evaluation after the latest memo-generation change.

## Run locally

1. Create `backend/.env` and set the provider configuration described below.
2. Start the API from `backend`: `python -m venv .venv`, activate it, `pip install -e .`, then `uvicorn app.main:app --reload`.
3. Start the UI from `frontend`: `npm install`, `npm run dev`.

The API defaults to ephemeral in-memory session/document state and Qdrant `:memory:`. No user document is written to disk. The frontend keeps the selected file in browser memory and uploads only for the active analysis session. Use HTTPS and redact session IDs from reverse-proxy access logs before exposing this service. Gemini 2.5 can apply implicit context caching to repeated large prefixes; cache hits and savings depend on provider behavior and are not guaranteed. Explicit remote cache objects are not created because they would complicate purge guarantees.

### Use a local LM Studio model

Gemini remains the default provider. To use a model served by LM Studio, load the model in LM Studio, start its local server in the Developer tab, then set these values in `backend/.env`:

```env
LLM_PROVIDER=lmstudio
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=
LM_STUDIO_TIMEOUT_SECONDS=600
LM_STUDIO_MAX_TOKENS=8192
```

When `LM_STUDIO_MODEL` is blank, the backend selects the first model returned by LM Studio; set it to a model ID from `http://localhost:1234/v1/models` if you have multiple models loaded. Restart the backend after changing the provider. No Gemini API key is needed in LM Studio mode.

### Live pitch and technical docs

The frontend serves the scheduled showcase at `http://localhost:3000/docs`. The admin panel is at `/docs?admin=1`. Set a strong `DOCS_ADMIN_TOKEN` in `backend/.env` before using admin editing; without it, admin access is disabled. Admin login uses an HTTP-only, SameSite=Strict cookie. The default public window is June 10 00:00 through June 14 23:59 Asia/Dhaka, recurring yearly; an administrator can change the schedule or switch visibility off. Content drafts, published copies, and version records are stored in `backend/data/docs.sqlite3` (override with `DOCS_DB_PATH`). Keep this SQLite file on persistent storage in deployments; ephemeral filesystems lose edits on restart. The app remains single-worker while its analysis sessions are process-local.

The public page supports Markdown download and browser print-to-PDF. Live fields come from backend configuration and feature flags; user/event analytics are not collected. Use the admin team editor only for contributor details approved for public display.

## Boundaries

This is a working application scaffold, not a substitute for advice from a licensed lawyer. It deliberately returns jurisdiction and source coverage gaps, does not fabricate statutes, and separates identifier matching from validation of a legal proposition. A CourtListener search result is evidence that a case record exists, not proof that it supports the argument. EUR-Lex's official SOAP web service requires registration; its connector reports unavailable when registered credentials are missing. Sessions are process-local, so run one API worker until an ephemeral session coordinator is added for multi-worker deployments.

External model and search providers receive the minimum text needed for their function. To preserve strict zero retention, use providers and account settings that contractually meet the required data-handling terms, or run an approved local model. Voyage/Cohere/Gemini/Groq/CourtListener are external processing unless configured otherwise. The default provider is Gemini. To explicitly switch to Groq, set `LLM_PROVIDER=groq`, configure `GROQ_API_KEY`, and review Groq's data controls before sending contract text. Groq calls use JSON mode and validate every response against the same local Pydantic schema; the support checker defaults to a separate model configured by `GROQ_SUPPORT_MODEL`.

## Accuracy methodology

Legal citations in generated claims are restricted to IDs in the resolved authority bank. Deterministic extraction maps supported citation forms to normalized keys; unresolved or out-of-bank references cannot become verified claims. The independent support checker is a separate temperature 0 requested for the independent support-check model call, and the verifier accepts its authority quotation only when that exact passage occurs in the resolved source text. Contract risks are retained only when their quotation is found in the uploaded document and their clause IDs exist in the segmenter output. Verification labels are returned by the backend as `verified`, `existence_only`, `unverified`, or `rejected`; the interface displays those labels without upgrading them. Unclear jurisdiction, missing source text, and provider failures remain coverage gaps or unavailable states. Model calls use JSON output schemas that are validated locally against the existing Pydantic models. Configured and actually used model names are recorded as technical metadata without changing the assessment sections.

The evaluator matches a planted risk only when a referenced clause overlaps an expected section number and an exact quoted span overlaps the expected quote anchor. Cross-clause recall additionally requires two or more referenced clause IDs. The evaluator uses the real pipeline when configured; otherwise it records unavailable metrics as not run and runs only offline checks. Gemini model names are sourced from `backend/app/config.py` settings (`GEMINI_MODEL`, `SUPPORT_CHECK_MODEL` (defaults to `GEMINI_MODEL`), `GEMINI_FALLBACK_MODEL`, and `GEMINI_SECONDARY_FALLBACK_MODEL`). Gemini requests use a 60-second timeout; quota and overload errors fail over immediately, and a timeout on the first backup stops further fallback attempts. Clause scans process up to 32 clauses per request, while cross-clause scans process up to 8 candidate pairs, to reduce request count while still covering all clauses and selected candidate pairs. Groq can be selected explicitly with `LLM_PROVIDER=groq`; provider errors report category, exception class, HTTP status, attempted model names, and a credential-redacted message.

```mermaid
flowchart TD
    U["User uploads contract<br/>(.txt / .pdf / .docx)"] --> ING["ingest<br/>parse document"]
    ING --> SEG["segment<br/>clauses with section numbers"]
    SEG --> JUR["detect_jurisdiction<br/>abstain if unclear"]
    JUR --> CHK["checklist_scan<br/>quote-grounded risks"]
    CHK --> XC["cross_clause_scan<br/>risks spanning 2+ clauses"]
    XC --> RES["research<br/>find candidate authorities"]

    subgraph SRC["Authority sources"]
        STAT[("statutes.json<br/>static corpus with url + retrieved_at")]
        CL["CourtListener<br/>live case lookup"]
    end
    STAT --> RES
    CL --> RES

    RES --> BANK["build_bank<br/>resolved real sources only<br/>IDs: A1, A2, ..."]
    BANK --> DRAFT["draft_memo<br/>may cite only bank IDs"]
    DRAFT --> VER["verify<br/>existence + independent support check<br/>(temperature 0, verbatim quote required)"]
    VER -->|"Verified / Existence-only / Unverified"| FIN["finalize<br/>status labels + evidence gaps"]
    VER -->|"Rejected: removed from memo"| REM["removed_claims<br/>kept for the audit trail"]
    REM --> FIN
    FIN --> OUT["Preliminary Risk Assessment<br/>DOCX / PDF export<br/>not-legal-advice notice"]

    JUR -.->|"jurisdiction unclear or source not loaded"| GAP["Not assessed / Evidence gap"]
    GAP -.-> FIN
```

## Known limitations

- `backend/data/statutes.json` has no loaded text for California B&P § 16600.5 or California Civil Code § 1798.140. Other statutory coverage is limited to the specific loaded entries; the presence of one section does not establish support for another.
- Live analysis requires a configured key for the selected model provider and available provider capacity; an API health check confirms backend reachability, not successful inference. Citation lookup requires network access and can be unavailable independently. The `/verify` citation-only probe cannot verify a legal proposition: a source match alone is not a support check. Temperature 0 is requested for analytical calls; provider behavior can differ.
- OCR and multimodal extraction can miss text or deadlines. Review the extracted document against the source before relying on findings.
- Sessions are process-local and expire after their configured TTL. Multi-worker deployments need a privacy-reviewed ephemeral session coordinator.
- This hackathon implementation is not legal advice and does not replace jurisdiction-specific review by qualified counsel.

## Recorded evaluation

The table below is copied from the evaluator's actual live run. It reports only checks that ran; unavailable metrics have no numeric value.

<!-- EVAL_TABLE_START -->
Numeric evaluation results are intentionally omitted here pending approval. The recorded live baseline predates the current source-grounded memo-generation change, so it must not be presented as a benchmark of the current code. The full prior run output, including its model metadata and per-claim outcomes, is in [backend/eval_results.json](backend/eval_results.json); rerun the live evaluator on the current code before presenting performance as current. Bank membership measures source resolution only, not legal relevance or support. Known-source probes are source-identity smoke tests, not substantive legal opinions.
<!-- EVAL_TABLE_END -->

Model names and per-claim/per-authority support-check outcomes are recorded in the evaluation JSON; temperature 0 was requested for analytical and support-check calls.

## Layout

`backend/app/api` routes, `backend/app/agents` LangGraph nodes and schemas, `backend/app/services` extraction/search/model integrations, `frontend/app` Next.js interface.
