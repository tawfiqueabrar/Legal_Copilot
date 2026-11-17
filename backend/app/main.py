from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import router, workflow
from app.api.sessions import router as sessions_router
from app.api.verify import router as verify_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close = getattr(workflow.resolver, "close", None)
    if close:
        await close()


app = FastAPI(title="Legal Copilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"])
app.include_router(router)
app.include_router(sessions_router)
app.include_router(verify_router)


@app.get("/health")
async def health():
    return {"status": "ok", "analysis_configured": bool(settings.gemini_api_key)}
