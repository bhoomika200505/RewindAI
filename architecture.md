# RAG 2.0 — Architecture

```mermaid
flowchart TD
    subgraph ingestion["Ingestion (offline)"]
        playlist["Playlist URL"] --> ytdlp["yt-dlp: list video IDs"]
        ytdlp --> transcriptApi["youtube-transcript-api: fetch transcript"]
        transcriptApi --> captions{"Captions available?"}
        captions -- no --> skip["skip + log video_id"]
        captions -- yes --> chunk["chunk_transcript(): overlapping ~45s windows"]
        chunk --> transcriptsJson[("transcripts.json (committed)")]
    end

    subgraph query["Query pipeline (FastAPI on Render, per request)"]
        browser["Browser: Chat UI"] --> fastapi["POST /api/chat"]
        fastapi --> rewrite["rewrite query with chat history"]
        transcriptsJson -.->|"rebuilt every startup"| startup["rebuild Chroma + BM25"]
        startup -.-> fastapi

        rewrite --> vectorSearch["vector_search(): Chroma"]
        rewrite --> keywordSearch["keyword_search(): BM25"]
        vectorSearch --> rrf["Reciprocal Rank Fusion"]
        keywordSearch --> rrf
        rrf --> rerank["cross-encoder rerank"]
        rerank --> mmr["MMR diversity filter"]
        mmr --> guardrail{"rerank_score >= MIN_RERANK_SCORE?"}

        guardrail -- no --> notFound["'I couldn't find that in these lectures'"]
        guardrail -- yes --> prompt["assemble prompt: context + history"]
        prompt --> groq["Groq: streaming completion"]
        groq --> sse["SSE: citations + tokens"]

        notFound --> render["Browser renders answer, citation chips seek the player"]
        sse --> render
    end

    subgraph evalHarness["Eval harness (calibration, not on the request path)"]
        evalQuestions["eval_questions.json (hand-labeled)"] --> evaluate["app.evaluate"]
        evaluate --> compare["hybrid vs vector-only: hit-rate@k, MRR"]
        compare -.->|"suggests"| guardrail
    end
```

## Why transcripts are rebuilt on startup

Render's free tier disk is ephemeral — wiped on every restart/redeploy. Instead of persisting
a Chroma directory, the app commits a pre-processed `transcripts.json` (chunked text +
timestamp metadata, no embeddings, no secrets) and rebuilds the Chroma + BM25 indexes from it
at container startup. Deploys stay stateless and reproducible.

## Two pipelines, one deployable backend

- **Ingestion** (`app/ingest.py`) runs offline — pulls playlist transcripts from YouTube,
  chunks them by overlapping timestamp windows, writes `transcripts.json`.
- **Query** (`app/rag.py`, `app/retrieval.py`, `app/vectorstore.py`, `app/main.py`) runs
  per-request inside the deployed FastAPI app: hybrid vector+keyword retrieval, cross-encoder
  reranking, MMR diversity filtering, a calibrated guardrail, then Groq streaming over SSE.

## Guardrail calibration

The guardrail's cutoff (`MIN_RERANK_SCORE`) isn't a number to guess — cross-encoder scores
aren't 0-centered in practice. On measured data, genuinely relevant top hits ranged -0.7 to
-8, while irrelevant questions clustered near -11. `app.evaluate` reports the real hit/miss
score gap on your own playlist and suggests a calibrated value from it.
