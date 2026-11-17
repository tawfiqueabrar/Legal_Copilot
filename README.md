# Legal Copilot

Privacy-first legal document analysis starter built with FastAPI, LangGraph, Gemini, ephemeral Qdrant, and Next.js.

## Run locally

1. Copy `backend/.env.example` to `backend/.env` and set provider keys as needed.
2. Start the API from `backend`: `python -m venv .venv`, activate it, `pip install -e .`, then `uvicorn app.main:app --reload`.
3. Start the UI from `frontend`: `npm install`, `npm run dev`.

The API defaults to ephemeral in-memory session/document state and Qdrant `:memory:`. No user document is written to disk. The frontend keeps the selected file in browser memory and uploads only for the active analysis session. Use HTTPS and redact session IDs from reverse-proxy access logs before exposing this service. Gemini 2.5 can apply implicit context caching to repeated large prefixes; cache hits and savings depend on provider behavior and are not guaranteed. Explicit remote cache objects are not created because they would complicate purge guarantees.

## Boundaries

This is a working application scaffold, not a substitute for advice from a licensed lawyer. It deliberately returns jurisdiction and source coverage gaps, does not fabricate statutes, and separates identifier matching from validation of a legal proposition. A CourtListener search result is evidence that a case record exists, not proof that it supports the argument. EUR-Lex's official SOAP web service requires registration; its connector reports unavailable when registered credentials are missing. Sessions are process-local, so run one API worker until an ephemeral session coordinator is added for multi-worker deployments.

External model and search providers receive the minimum text needed for their function. To preserve strict zero retention, use providers and account settings that contractually meet the required data-handling terms, or run an approved local model. Voyage/Cohere/Gemini/CourtListener are external processing unless configured otherwise.

## Layout

`backend/app/api` routes, `backend/app/agents` LangGraph nodes and schemas, `backend/app/services` extraction/search/model integrations, `frontend/app` Next.js interface.
