import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .rag import answer_stream
from .vectorstore import get_collection

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rebuilding Chroma index from transcripts.json...")
    get_collection(rebuild=True)
    logger.info("Index ready.")
    yield


app = FastAPI(title="RAG 2.0", lifespan=lifespan)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatTurn] = []


def _sse_event(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = [turn.model_dump() for turn in req.history]

    def stream():
        token_gen, citations = answer_stream(req.question, history=history)
        yield _sse_event("citations", {"citations": citations})
        for token in token_gen:
            yield _sse_event("token", {"text": token})
        yield _sse_event("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
