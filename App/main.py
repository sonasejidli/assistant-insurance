import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from App.settings import MIN_SCORE
from App.system import NOT_FOUND, answer_question
from App.text_search import TextRetriever

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.retriever = TextRetriever()
    yield


app = FastAPI(title="Insurance Assistant", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "chunks": len(request.app.state.retriever.chunks)}


@app.post("/ask")
def ask(question: Question, request: Request):
    text = question.question.strip()
    if len(text) < 3:
        raise HTTPException(422, "Please enter a question of at least 3 characters.")
    hits, score = request.app.state.retriever.search(text)
    if not hits or score < MIN_SCORE:
        return {"answer": NOT_FOUND, "sources": []}
    try:
        answer = answer_question(text, hits)
    except Exception:
        log.exception("Answer generation failed")
        raise HTTPException(503, "The answer service is temporarily unavailable. Please try again.")
    sources = list(dict.fromkeys(hit["doc"] for hit in hits))
    return {"answer": answer, "sources": [{"doc": source} for source in sources]}
