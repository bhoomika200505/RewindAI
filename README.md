# RewindAI

A deployed RAG (Retrieval-Augmented Generation) app that answers questions from a YouTube
lecture playlist — with citation chips that jump straight to the timestamp in the video.

## How it works

1. **Ingestion (offline, one-time):** transcripts are pulled from a YouTube playlist, chunked
   into overlapping ~45s windows, and saved to `data/transcripts.json`.
2. **Query (per request):** the FastAPI backend rebuilds a ChromaDB (vector) and BM25
   (keyword) index from that file on startup, fuses both search results, reranks with a
   cross-encoder, filters for diversity (MMR), and streams a grounded answer from Groq —
   with a guardrail that says "I couldn't find that in these lectures" when nothing relevant
   surfaces.

See [`architecture.md`](architecture.md) for the full pipeline diagram and design notes.

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Embeddings | local, `sentence-transformers` (no API key needed) |
| Vector store | ChromaDB (embedded, rebuilt from `data/transcripts.json` on every startup) |
| Keyword search | BM25 (`rank-bm25`), fused with vector search via Reciprocal Rank Fusion |
| Reranking | cross-encoder + MMR diversity filtering |
| LLM | Groq API (fast inference, swappable models) |
| Transcripts | `youtube-transcript-api`, with `yt-dlp` as a fallback for blocked fetches |
| Frontend | Plain HTML/CSS/JS — no framework, no build step |

## Project structure

```
backend/
  app/              # FastAPI app: main.py, rag.py, retrieval.py, vectorstore.py, ingest.py
  requirements.txt
  .env.example
frontend/           # static HTML/CSS/JS chat UI, served by the backend at "/"
data/               # transcripts.json (committed, no secrets/embeddings)
render.yaml         # Render deploy config
architecture.md     # pipeline diagram + design notes
INGEST.md           # guide for ingesting your own playlist / working around YouTube IP-blocks
```

## Running locally

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY
uvicorn app.main:app --reload
```

Open `http://localhost:8000` — the backend serves the frontend directly.

### Using your own playlist

`data/transcripts.json` ships with a default playlist already ingested. To point it at your
own YouTube playlist (or a single video):

```bash
cd backend
python -m app.ingest --playlist "https://www.youtube.com/playlist?list=..."
# or a single video:
python -m app.ingest --video "https://www.youtube.com/watch?v=VIDEO_ID"
```

If YouTube rate-limits the ingest (common on cloud IPs), see [`INGEST.md`](INGEST.md) for the
fix ladder (hotspot → browser cookies → residential proxy). This only affects the one-time
ingest step — the deployed app never calls YouTube at request time.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Your Groq API key |
| `GROQ_MODEL` | No | Defaults to a fast Groq-hosted model |
| `EMBEDDING_MODEL` | No | Defaults to `all-MiniLM-L6-v2` |
| `CHUNK_WINDOW_SECONDS` | No | Transcript chunk size, defaults to 45 |
| `TOP_K` | No | Number of chunks retrieved per query, defaults to 5 |
| `MAX_DISTANCE` | No | Guardrail threshold for the vector search |
| `YTDLP_COOKIES_FROM_BROWSER` | No | Only needed if ingest gets IP-blocked |
| `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD` | No | Last-resort proxy for a hard IP block during ingest |

See `backend/.env.example` for the full list with defaults.

## Deploying

Configured for [Render](https://render.com) out of the box via `render.yaml`:

1. Push this repo to GitHub.
2. On Render, create a new **Blueprint** and point it at this repo — it will read
   `render.yaml` automatically.
3. Set `GROQ_API_KEY` in the Render dashboard (marked `sync: false`, so it isn't stored in
   the repo).
4. Deploy. Render's disk is ephemeral, so the app rebuilds its vector/keyword indexes from
   the committed `data/transcripts.json` on every startup — no persistent volume needed.

See `architecture.md` for why this stateless-rebuild approach was chosen.

## Retrieval quality

`app/evaluate.py` runs a small eval harness against hand-labeled questions, comparing hybrid
(vector + keyword) retrieval against vector-only, reporting hit-rate@k and MRR — used to
calibrate the guardrail threshold rather than guessing it.