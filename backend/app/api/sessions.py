from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from app.api.routes import _session_stream, store, upload
from app.services.memo_export import memo_to_docx, memo_to_pdf

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
async def create_session(file: UploadFile = File(...)):
    return await upload(file)


@router.post("/{session_id}/analyze")
async def analyze_session(session_id: str):
    session = await store.get(session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")
    return await _session_stream(session)


@router.get("/{session_id}/memo")
async def get_memo(session_id: str):
    session = await store.get(session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")
    if session.analysis_error:
        raise HTTPException(424, "Analysis failed; no memo is available.")
    if session.result is None:
        raise HTTPException(409, "Analysis has not completed.")
    return session.result


@router.get("/{session_id}/memo.docx")
async def export_docx(session_id: str):
    session = await store.get(session_id)
    if not session or not session.result:
        raise HTTPException(404, "Session or completed memo not found.")
    return Response(memo_to_docx(session.result), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="legal-memorandum.docx"', "Cache-Control": "no-store"})


@router.get("/{session_id}/memo.pdf")
async def export_pdf(session_id: str):
    session = await store.get(session_id)
    if not session or not session.result:
        raise HTTPException(404, "Session or completed memo not found.")
    return Response(memo_to_pdf(session.result), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="legal-memorandum.pdf"', "Cache-Control": "no-store"})


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    removed = await store.purge(session_id)
    if not removed:
        raise HTTPException(404, "Session not found.")
    return {"purged": True}
