#!/usr/bin/env python3
"""
app.py — Humunculous public agent backend (W3). FastAPI + ChromaDB + Claude.

Isolated from the live v0 service (main.py / freddy-backend-v10h). Runs LOCAL on :8011.
Embeddings: OpenAI (matches the corpus build). Generation: Claude Sonnet 4.6, streamed.

Endpoints:
  GET  /health     — readiness + corpus size
  POST /api/chat   — {session_id, message} → SSE stream of the answer

Born hardened: 1500-char input cap, max_tokens cap, per-IP rate limit, ~20-turn cap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from system_prompt import build_system_prompt

# --- config ------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
CHATBOT_RAG = HERE.parent
REPO_ROOT = CHATBOT_RAG.parents[1]

load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env", override=False)        # inherit existing OPENAI_API_KEY

CHROMA_DIR = CHATBOT_RAG / "chroma_store"
COLLECTION_NAME = "humunculous_v1"
GENERATION_MODEL = "claude-sonnet-4-6"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

MAX_INPUT_CHARS = 1500
MAX_OUTPUT_TOKENS = 800
MAX_TURNS = 20                                          # user turns per session
TOP_K = 6
RATE_LIMIT = os.environ.get("AGENT_RATE_LIMIT", "20/10 minutes")  # per-IP; raise locally for QA

ALLOWED_ORIGINS = [
    # local dev (Astro)
    "http://localhost:4321", "http://127.0.0.1:4321",
    "http://localhost:4322", "http://127.0.0.1:4322",
    # production site (live only after the Stage-2 domain swap; harmless before)
    "https://freddymanuel.com", "https://www.freddymanuel.com",
]
# Extra exact origins via env, comma-separated. SITE_ORIGIN kept for back-compat.
for _env in ("SITE_ORIGIN", "EXTRA_ALLOWED_ORIGINS"):
    for _origin in (os.environ.get(_env) or "").split(","):
        _origin = _origin.strip()
        if _origin and _origin not in ALLOWED_ORIGINS:
            ALLOWED_ORIGINS.append(_origin)

# Cloudflare Pages preview: the project URL and every per-deploy <hash> subdomain.
# Overridable via env if the project is ever renamed.
ALLOWED_ORIGIN_REGEX = os.environ.get(
    "ALLOWED_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)?freddymanuel-rebuild\.pages\.dev",
)

# --- clients (lazy globals, set on startup) ----------------------------------
SYSTEM_PROMPT = build_system_prompt()
_sessions: dict[str, list[dict]] = {}
_collection = None
_embedding_model = DEFAULT_EMBEDDING_MODEL
_openai = None
_anthropic = None

def client_ip(request: Request) -> str:
    """Rate-limit key = the real client IP. Behind Render's proxy the socket peer is
    the router, so prefer the left-most X-Forwarded-For hop; fall back to the peer for
    local runs. (Render also runs uvicorn with --proxy-headers; this works either way.)"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)
app = FastAPI(title="Humunculous agent (rebuild)", version="1.0.0")
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "The window is busy. Give it a minute and come back."},
    )


@app.on_event("startup")
def _startup() -> None:
    """Open the persistent collection only. API clients init lazily on first use, so the
    server (and /health) come up even before the Anthropic key exists."""
    global _collection, _embedding_model
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = client.get_collection(COLLECTION_NAME)
    meta = _collection.metadata or {}
    _embedding_model = meta.get("embedding_model", DEFAULT_EMBEDDING_MODEL)


def get_openai():
    global _openai
    if _openai is None:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set (embeddings)")
        _openai = OpenAI(api_key=key)
    return _openai


def get_anthropic():
    global _anthropic
    if _anthropic is None:
        from anthropic import Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (generation)")
        _anthropic = Anthropic(api_key=key)
    return _anthropic


# --- request model -----------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1)


# --- retrieval ---------------------------------------------------------------
def retrieve(query: str) -> str:
    """Embed the query, pull the top-K corpus chunks, format them as an evidence block."""
    emb = get_openai().embeddings.create(model=_embedding_model, input=[query]).data[0].embedding
    res = _collection.query(query_embeddings=[emb], n_results=TOP_K)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    if not docs:
        return ""
    blocks = []
    for doc, meta in zip(docs, metas):
        title = (meta or {}).get("section_title", "")
        blocks.append(f"[{title}]\n{doc}" if title else doc)
    joined = "\n\n---\n\n".join(blocks)
    return (
        "Material from your corpus that may bear on the visitor's message. Speak only "
        "from this and from what you have already said. If it does not cover the "
        "question, say the window does not hold that part.\n\n"
        f"{joined}"
    )


# --- chat --------------------------------------------------------------------
@app.get("/health")
def health():
    count = _collection.count() if _collection is not None else 0
    return {"status": "ok", "model": GENERATION_MODEL,
            "embedding_model": _embedding_model, "corpus_chunks": count}


@app.post("/api/chat")
@limiter.limit(RATE_LIMIT)
async def chat(request: Request, body: ChatRequest):
    message = body.message.strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "Empty message."})
    if len(message) > MAX_INPUT_CHARS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Keep it under {MAX_INPUT_CHARS} characters."},
        )

    history = _sessions.setdefault(body.session_id, [])
    user_turns = sum(1 for m in history if m["role"] == "user")
    if user_turns >= MAX_TURNS:
        def _closed():
            msg = ("This window has said its piece for now. Refresh to open a new one. "
                   "For anything direct, write to info@freddymanuel.com.")
            yield _sse({"text": msg})
            yield _sse({"done": True})
        return StreamingResponse(_closed(), media_type="text/event-stream")

    history.append({"role": "user", "content": message})

    context = retrieve(message)
    api_messages = [dict(m) for m in history]
    if context:
        api_messages[-1]["content"] = f"{context}\n\n---\n\nVisitor: {message}"

    def _generate():
        full = []
        try:
            with get_anthropic().messages.stream(
                model=GENERATION_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=api_messages,
            ) as stream:
                for delta in stream.text_stream:
                    full.append(delta)
                    yield _sse({"text": delta})
        except Exception as exc:                       # surface, never swallow silently
            yield _sse({"error": f"The window faltered: {type(exc).__name__}."})
            print(f"[chat] generation error: {exc!r}")
            return
        history.append({"role": "assistant", "content": "".join(full)})
        yield _sse({"done": True})

    return StreamingResponse(_generate(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=int(os.environ.get("PORT", 8011)))
