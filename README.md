# freddymanuel-agent

The public conversational agent behind **freddymanuel.com** — the "Humunculous window".
A retrieval-augmented (RAG) chatbot that answers as Freddy's public voice, strictly from
a curated public-boundary corpus.

- **Retrieval:** ChromaDB (persistent, committed) over the corpus.
- **Embeddings:** OpenAI `text-embedding-3-small`.
- **Generation:** Anthropic Claude **Sonnet 4.6**, streamed (Server-Sent Events).
- **Server:** FastAPI + uvicorn. Hardened: input cap, output cap, per-IP rate limit, per-session turn cap.

This is an isolated service. It does not touch the legacy v0 backend.

## Layout

```
backend/
  app.py             FastAPI app: GET /health, POST /api/chat (SSE)
  system_prompt.py   assembles the system prompt (manifest §4 verbatim + voice profile)
  requirements.txt
  .env.example
corpus/              public-boundary source texts (the IN files of rag_manifest.md)
chroma_store/        COMMITTED prebuilt vector DB — what the service loads at runtime
build_corpus.py      rebuilds chroma_store/ from corpus/ (run locally, not on deploy)
rag_manifest.md      the privacy gate: nothing is ingested unless marked IN here
render.yaml          Render Blueprint
```

## Endpoints

- `GET /health` → `{status, model, embedding_model, corpus_chunks}`
- `POST /api/chat` → body `{session_id, message}` → SSE stream of `{text}` deltas, then `{done:true}`

## Run locally

```bash
python -m venv .venv && . .venv/Scripts/activate      # (Windows: .venv\Scripts\activate)
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env                  # then fill ANTHROPIC_API_KEY + OPENAI_API_KEY
cd backend && python app.py                           # serves on http://localhost:8011
curl http://localhost:8011/health
```

## Rebuild the corpus

`chroma_store/` is committed and deterministic, so a normal deploy does **not** rebuild it.
Rebuild **locally** only when `corpus/` changes, then commit the regenerated `chroma_store/`:

```bash
python build_corpus.py        # validates against rag_manifest.md, re-embeds, rewrites chroma_store/
```

`build_corpus.py` refuses to run if `corpus/` contains a file not marked **IN** in
`rag_manifest.md` (§2). The manifest is the gate; the folder is never trusted directly.

## Deploy (Render)

1. Render dashboard → **New + → Blueprint** → connect this repo (it reads `render.yaml`).
2. In the service's **Environment** tab, paste `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
   (they are `sync:false` — never stored in the repo).
3. Render builds, then health-checks `/health`. The service URL becomes the site's
   `PUBLIC_AGENT_API_URL`.

> Build note: `chromadb` pulls a moderately heavy dependency tree. The first build may take
> several minutes. The app passes precomputed embeddings to Chroma, so no embedding model
> runs inside the service at query time.

## Privacy

The corpus is the public ceiling, curated per `rag_manifest.md`. Private canon — the novel,
the spec/character bible, the withheld life episodes, private dream drafts — is **not** in this
repository by design. If the corpus is ever extended, run it through the manifest gate first.
