import asyncio, json
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from app.config import settings
from app.services.sessions import SessionStore
from app.ingestion import ingest_document
from app.agents.workflow import LegalWorkflow

router = APIRouter(prefix="/api")
store = SessionStore(settings.session_ttl_seconds)
workflow = LegalWorkflow()


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    allowed = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/png", "image/jpeg", "image/tiff", "text/plain"}
    if file.content_type not in allowed:
        raise HTTPException(415, "Upload a PDF, PNG, JPEG, TIFF, or text file.")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Document exceeds configured upload limit.")
    if not data:
        raise HTTPException(400, "Uploaded document is empty.")
    session = await store.create(file.filename or "document", data, file.content_type)
    return {"session_id": session.id, "filename": session.filename, "expires_in_seconds": settings.session_ttl_seconds}


async def _run(session):
    try:
        parsed = await asyncio.to_thread(ingest_document, session.content, session.content_type, session.filename)
        await session.events.put({"event": "progress", "data": {"stage": "extract", "message": "Document received in volatile session memory"}})
        result = await workflow.run({"session_id": session.id, "filename": session.filename, "mime_type": session.content_type, "document_text": parsed.text, "page_texts": parsed.page_texts, "parsed_document": parsed.model_dump(), "document_bytes": session.content, "event_queue": session.events, "progress": [], "errors": []})
        session.result = result.get("memo")
        await session.events.put({"event": "result", "data": session.result or {"error": "Memo generation failed", "errors": result.get("errors", [])}})
    except Exception as exc:
        await session.events.put({"event": "error", "data": {"message": "Analysis failed. Check service configuration and retry."}})
    finally:
        session.running = False
        session.content = b""
        await session.events.put(None)


@router.get("/analyze/{session_id}")
async def analyze(session_id: str):
    session = await store.get(session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")
    if not session.running and session.result is None:
        session.running = True
        session.task = asyncio.create_task(_run(session))

    async def stream():
        if session.result is not None:
            yield f"event: result\ndata: {json.dumps(session.result)}\n\n"
            return
        while True:
            try:
                item = await asyncio.wait_for(session.events.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/analyze")
async def analyze_query(session_id: str):
    return await analyze(session_id)


@router.delete("/purge/{session_id}")
async def purge(session_id: str):
    removed = await store.purge(session_id)
    if not removed:
        raise HTTPException(404, "Session not found.")
    return {"purged": True}


@router.delete("/purge")
async def purge_query(session_id: str):
    return await purge(session_id)
