# RAG 2.0

Build a deployed RAG app that answers questions from your own lecture YouTube playlist.

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Embeddings | local, `sentence-transformers` (no API key) |
| Vector store | ChromaDB (embedded, rebuilt from `data/transcripts.json` on every startup) |
| LLM | Groq API (fast inference, swappable models) |
| Transcripts | `youtube-transcript-api` (YouTube playlist primary; local video + Whisper as fallback) |
| Frontend | Plain HTML/CSS/JS — no framework, no build step |

## Quickstart (solution/)

One command on a fresh machine,
no Python required. The script installs [`uv`](https://astral.sh/uv) if missing, uv fetches
Python 3.11, then it creates the venv, installs deps, sets up `.env`, and starts the server:

```bash
# macOS / Linux
./setup.sh

# Windows (PowerShell)
.\setup.ps1
```

It prompts only for your `GROQ_API_KEY`.

**To use your own content instead**, 
pass a URL — a **single video or a whole playlist** — which
re-ingests and overwrites `transcripts.json`:

```bash
./setup.sh "https://www.youtube.com/watch?v=VIDEO_ID"        # one video
./setup.sh "https://www.youtube.com/playlist?list=..."       # a playlist
# PowerShell: .\setup.ps1 "<url>"
```

See **[INGEST.md](INGEST.md)** for the full guide — single video vs playlist, and the exact
steps to get past a YouTube IP-block (hotspot → browser cookies → proxy).

> **YouTube may IP-block ingest.** Transcript fetching happens only at ingest time (offline,
> one-time) — the deployed app never calls YouTube, so this never affects the running app. If you
> hit `IpBlocked` / `HTTP 429`, you're on a throttled IP; the fix ladder (hotspot → browser
> cookies → proxy) is in **[INGEST.md](INGEST.md)**. You only need one successful ingest — commit
> the resulting `transcripts.json`.

Flags: `--no-serve`, `--force-ingest` (PowerShell: `-NoServe`, `-ForceIngest`).

Manual equivalent:

```bash
cd solution/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY
# transcripts.json already ships; to use your own playlist:
# python -m app.ingest --playlist "<youtube playlist URL>"
uvicorn app.main:app --reload
```

Open `solution/frontend/index.html` (served by the backend at `/`) and start asking questions.

## Deploying

See `solution/render.yaml` and `architecture.md` for the deploy walkthrough.

## Stretch goals

`solution/` runs a sharper retrieval pipeline than what `starter/` teaches in the core
build — hybrid vector+keyword search, cross-encoder reranking, diversity filtering, and an
evaluation harness for measuring retrieval quality on your own playlist. Not part of the
required Day 2 path; see `architecture.md` and `solution/backend/app/retrieval.py`.