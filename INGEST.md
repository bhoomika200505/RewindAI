# Ingesting your own videos & playlists

The app answers from whatever transcripts are in `data/transcripts.json`. The repo ships a
ready-made one so the app runs immediately — this guide is for **swapping in your own** content.

Ingestion is **offline and one-time**. It runs on your laptop, writes `data/transcripts.json`,
and you commit that file. The deployed app **never calls YouTube** — it just rebuilds its index
from that JSON on startup. So you only ever need *one* successful ingest.

---

## TL;DR

```bash
cd solution/backend && source .venv/bin/activate

# one video …
python -m app.ingest --playlist "https://www.youtube.com/watch?v=VIDEO_ID"
# … or a whole playlist
python -m app.ingest --playlist "https://www.youtube.com/playlist?list=PLAYLIST_ID"

# then confirm and (for deploy) commit it
python -c "import json;print(len(json.load(open('../data/transcripts.json'))),'chunks')"
git add solution/data/transcripts.json && git commit -m "data: my playlist"
```

`--playlist` accepts **either a single-video URL or a playlist URL** — ingest detects which.

Default demo shipped in the repo: 3Blue1Brown *Essence of calculus*. Recommended teaching
example (video about LLMs — on-topic for a RAG workshop):
`https://www.youtube.com/watch?v=wjZofJX0v4M` (“Transformers, the tech behind LLMs”).

---

## The one thing that goes wrong: YouTube IP-blocks you

Ingest is the **only** step that touches YouTube, and YouTube rate-limits/blocks IPs. You'll see
`IpBlocked` or `HTTP 429`. This is not a bug in the app — it's YouTube throttling your network.
No library bypasses it (youtube-transcript-api and yt-dlp both request from *your* IP). Two facts
make it manageable:

- You need only **one** successful ingest, ever. Commit the JSON and you're done.
- The deployed app is unaffected — it never calls YouTube.

### The ladder — try in order, stop when one works

1. **Use a residential IP.** Home wifi, or — if that's flagged from earlier attempts — your
   **phone hotspot** (a different IP usually clears it instantly). Never a cloud VM / Codespaces /
   corporate VPN: those IP ranges are blanket-blocked.

2. **Let ingest use your browser cookies.** Ingest auto-falls back to yt-dlp; pointing it at a
   browser you're logged into YouTube with makes that fallback authenticated and far more likely
   to succeed. In `solution/backend/.env`:
   ```
   YTDLP_COOKIES_FROM_BROWSER=chrome        # or firefox | edge | safari | brave
   ```
   (macOS Safari cookies need Full Disk Access for your terminal; Chrome/Firefox are easiest.)

3. **Slow down.** If you just hammered YouTube (many quick retries), the IP is temporarily
   throttled. Wait ~30–60 min, or switch networks (step 1). Don't retry in a tight loop — it
   deepens the block.

4. **Residential proxy (last resort, works from anywhere).** Sign up at
   [webshare.io](https://www.webshare.io) (Residential), then in `.env`:
   ```
   WEBSHARE_PROXY_USERNAME=...
   WEBSHARE_PROXY_PASSWORD=...
   ```

### Optional: a JS runtime for yt-dlp

Recent yt-dlp warns *“No supported JavaScript runtime … some formats may be missing.”* Captions
usually come through without it, but installing one makes yt-dlp more robust:
```bash
brew install deno        # macOS/Linux (Homebrew); see https://docs.deno.com for others
```

---

## How ingest works (so the errors make sense)

```
playlist/video URL
      │  yt-dlp lists video IDs  (single video → treated as a one-item list)
      ▼
  for each video: fetch_transcript()
      │  1) youtube-transcript-api   ── blocked? ─┐
      │  2) yt-dlp fallback  (client emulation + optional cookies, json3 captions)
      ▼
  chunk_transcript()  → overlapping ~45s windows, each keeping its start timestamp
      ▼
  data/transcripts.json   (chunked text + timestamps + video IDs; no embeddings, no secrets)
      ▼
  commit it → deploy rebuilds the Chroma + BM25 index from it on startup
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `IpBlocked` / `HTTP 429` | YouTube throttling your IP | The ladder above — hotspot, cookies, wait, or proxy |
| `Found 0 videos` | Stale yt-dlp, or a private/region-locked playlist | `uv pip install -U yt-dlp`; check the URL is public |
| `Wrote 0 chunks (N skipped: no captions)` | Videos have no captions | Pick videos/playlists that have captions |
| `Requested format is not available` | Old code path (fixed); or partial block | Update to current `ingest.py`; if it persists, it's a block → the ladder |
| Answers are “I couldn't find that…” a lot | You're asking outside the ingested content | Ask about what's actually in your videos, or ingest the right playlist |

Once `data/transcripts.json` has chunks, run the app (`uvicorn app.main:app --reload`), open `/`,
and ask away. Commit the JSON to ship it. See `docs/deploy.md` for Render deploy.
