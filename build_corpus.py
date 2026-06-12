#!/usr/bin/env python3
"""
build_corpus.py — Humunculous public agent, corpus pipeline (W3).

Idempotent. Reads rag_manifest.md as the GATE (never the folder), validates that every
file it ingests is marked IN in manifest §2, aborts if corpus/ holds an unlisted file,
chunks each source by semantic section, embeds with OpenAI, and persists to ChromaDB.

The manifest is the authority. Privacy-critical specifics:
  - corpus/voice_profile.md is the SYSTEM-PROMPT voice layer (§5-bis), NOT corpus — skipped.
  - corpus/dreams_v1_draft.md is a private working draft — skipped.
  - episodes_v1_draft.md: ONLY the SAFE section is ingested. The SAFE count is asserted
    == 12 (manifest §2 #7). If the SAFE section ever drifts from 12, the build ABORTS.

Run:  python build_corpus.py        (rebuilds the collection from scratch)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Windows consoles default to cp1252; our output uses →·…—. Force UTF-8 so prints don't die.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# --- paths -------------------------------------------------------------------
HERE = Path(__file__).resolve().parent          # repo root
CORPUS_DIR = HERE / "corpus"
MANIFEST = HERE / "rag_manifest.md"
CHROMA_DIR = HERE / "chroma_store"
REPO_ROOT = HERE.parents[1]                      # for optional .env inheritance

EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "humunculous_v1"

# Files present in corpus/ that are deliberately NOT corpus (expected-but-excluded).
KNOWN_OUT = {"voice_profile.md", "dreams_v1_draft.md"}

# Per-source ingestion config. `split` is the markdown header level that marks one
# semantic unit; None means the whole body is a single chunk.
SOURCES = {
    "site_copy.md":         {"doc_type": "site_copy", "split": "##"},
    "a_spec_sheet.md":      {"doc_type": "essay",     "split": None},
    "cv_en.md":             {"doc_type": "cv",        "split": "##"},
    "facts.md":             {"doc_type": "facts",     "split": "##"},
    "dreams_v2_public.md":  {"doc_type": "dream",     "split": "##"},
    "episodes_v1_draft.md": {"doc_type": "episode",   "split": "###",
                             "safe_only": True, "expected": 12},
}

# Episode titles to hold out of the SAFE block even if present (curated in the private
# master). Empty in this public snapshot: its SAFE block already excludes held-out titles.
EXCLUDE_EPISODE_TITLES: set[str] = set()


def die(msg: str) -> None:
    print(f"\n  ABORT: {msg}\n", file=sys.stderr)
    sys.exit(1)


# --- manifest gate -----------------------------------------------------------
def manifest_in_allowlist() -> set[str]:
    """Parse rag_manifest.md §2 (CORPUS — IN) and return the set of `corpus/<file>.md`
    basenames marked IN. Only the §2 block is scanned, so §3 (OUT) and §5-bis
    (voice_profile) are never mistaken for IN."""
    if not MANIFEST.exists():
        die(f"manifest not found at {MANIFEST}")
    text = MANIFEST.read_text(encoding="utf-8")
    m = re.search(r"^##\s*2\.\s*CORPUS\s*—\s*IN\b(.*?)^##\s*3\.", text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        die("could not locate the '## 2. CORPUS — IN' block in the manifest")
    in_block = m.group(1)
    allow = set(re.findall(r"corpus/([A-Za-z0-9_]+\.md)", in_block))
    if not allow:
        die("manifest §2 listed no `corpus/*.md` files — refusing to build")
    return allow


# --- markdown helpers --------------------------------------------------------
_ITALIC = re.compile(r"^\*[^*].*\*$")      # a line that is wholly *italic* (not **bold**)
_BOLD = re.compile(r"^\*\*.*\*\*$")        # a line that is wholly **bold**


def _strip_meta_lines(lines: list[str]) -> list[str]:
    """Drop horizontal rules and lines that are entirely italic or entirely bold —
    these are edit/decision/status notes, never body content."""
    out = []
    for ln in lines:
        s = ln.strip()
        if s == "---" or _ITALIC.match(s) or _BOLD.match(s):
            continue
        out.append(ln)
    return out


def _heading_text(line: str) -> str:
    return line.lstrip("#").strip()


def chunk_by_header(body: str, level: str) -> list[tuple[str, str]]:
    """Split on lines beginning with `level + ' '`. Everything before the first such
    header (the # title + any meta preamble) is discarded. Returns (title, text)."""
    prefix = level + " "
    chunks: list[tuple[str, str]] = []
    cur_title: str | None = None
    cur: list[str] = []
    for ln in body.splitlines():
        if ln.startswith(prefix):
            if cur_title is not None:
                chunks.append((cur_title, "\n".join(_strip_meta_lines(cur)).strip()))
            cur_title = _heading_text(ln)
            cur = []
        elif cur_title is not None:
            cur.append(ln)
    if cur_title is not None:
        chunks.append((cur_title, "\n".join(_strip_meta_lines(cur)).strip()))
    return [(t, b) for t, b in chunks if b]


def chunk_whole_essay(body: str) -> list[tuple[str, str]]:
    """a_spec_sheet.md: one chunk. Drop the '# Title' and the 'Essay by …' descriptor."""
    lines = body.splitlines()
    title = _heading_text(lines[0]) if lines and lines[0].startswith("# ") else "A Spec Sheet"
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    if rest and rest[0].lstrip().startswith("Essay by"):
        rest.pop(0)
    text = "\n".join(_strip_meta_lines(rest)).strip()
    return [(title, text)] if text else []


def chunk_safe_episodes(body: str) -> list[tuple[str, str]]:
    """episodes_v1_draft.md: only the SAFE block; one chunk per ### episode; drop any
    held-out title(s); assert the count matches the manifest."""
    m = re.search(r"^##\s*SAFE EPISODES.*?$(.*?)^##\s", body,
                  re.DOTALL | re.MULTILINE)
    if not m:
        die("episodes_v1_draft.md: could not isolate the SAFE block (## SAFE EPISODES … next ##)")
    safe = m.group(1)
    raw = chunk_by_header(safe, "###")
    kept = [(t, b) for t, b in raw if t not in EXCLUDE_EPISODE_TITLES]
    dropped = [t for t, _ in raw if t in EXCLUDE_EPISODE_TITLES]
    for t in dropped:
        print(f"    · held out: {t}")
    return kept


# --- embeddings + store ------------------------------------------------------
def load_env() -> None:
    from dotenv import load_dotenv
    # New backend secrets first, then inherit OPENAI_API_KEY from the existing root .env.
    load_dotenv(HERE / "backend" / ".env")
    load_dotenv(HERE / ".env", override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)


def embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        die("OPENAI_API_KEY not set (backend/.env or repo-root .env)")
    client = OpenAI(api_key=key)
    out: list[list[float]] = []
    for i in range(0, len(texts), 100):                     # batch to stay under limits
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts[i:i + 100])
        out.extend(d.embedding for d in resp.data)
    return out


def main() -> None:
    print(f"build_corpus.py — manifest gate @ {MANIFEST.name}")
    load_env()

    in_allow = manifest_in_allowlist()
    print(f"  manifest §2 IN: {sorted(in_allow)}")

    # GATE: every .md in corpus/ must be IN or KNOWN_OUT; otherwise abort.
    present = {p.name for p in CORPUS_DIR.glob("*.md")}
    for name in sorted(present):
        if name not in in_allow and name not in KNOWN_OUT:
            die(f"unlisted file in corpus/: {name} — not in manifest §2 IN, not in KNOWN_OUT. "
                f"Add it to the manifest or remove it before building.")
    missing = [n for n in in_allow if n not in present]
    if missing:
        die(f"manifest lists {missing} but the file(s) are absent from corpus/")

    # Build chunks per source.
    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []
    per_file: dict[str, int] = {}

    for name in sorted(in_allow):
        cfg = SOURCES.get(name)
        if cfg is None:
            die(f"{name} is IN per the manifest but has no ingestion config in SOURCES")
        body = (CORPUS_DIR / name).read_text(encoding="utf-8")

        if cfg.get("safe_only"):
            chunks = chunk_safe_episodes(body)
            expected = cfg.get("expected")
            if expected is not None and len(chunks) != expected:
                die(f"{name}: SAFE section yielded {len(chunks)} episodes, manifest declares "
                    f"{expected}. The curatorial count drifted — fix the file or the manifest, "
                    f"then rebuild.")
        elif cfg["split"] is None:
            chunks = chunk_whole_essay(body)
        else:
            chunks = chunk_by_header(body, cfg["split"])

        if not chunks:
            die(f"{name}: produced zero chunks — check the source structure")

        for i, (title, text) in enumerate(chunks):
            ids.append(f"{name}::{i:02d}")
            documents.append(text)
            metadatas.append({"source": name, "section_title": title,
                              "doc_type": cfg["doc_type"]})
        per_file[name] = len(chunks)

    print("  chunks per source:")
    for name in sorted(per_file):
        print(f"    {name:24s} {per_file[name]:>3d}")
    print(f"  TOTAL chunks: {len(documents)}")

    # Embed + persist (idempotent: recreate the collection each run).
    print(f"  embedding {len(documents)} chunks with {EMBEDDING_MODEL} …")
    embeddings = embed(documents)

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"embedding_model": EMBEDDING_MODEL, "hnsw:space": "cosine"},
    )
    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    print(f"  persisted {collection.count()} chunks → {CHROMA_DIR}  (collection '{COLLECTION_NAME}')")
    print("  GATE PASSED. Corpus build complete.\n")


if __name__ == "__main__":
    main()
