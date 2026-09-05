# data/

`transcripts.json` is the pre-processed, chunked, timestamped transcript output the app rebuilds
its Chroma index from on startup (see root README, "Why transcripts are rebuilt on startup"). A
ready-made demo set (3Blue1Brown "Essence of calculus") **ships here already**, so the app runs
out of the box and deploys with data.

To use your own playlist, regenerate it (overwrites the demo). Run this once from a **residential
IP** — YouTube IP-blocks cloud IPs and rate-limits over-eager home IPs — then commit the result:

```bash
cd solution/backend
python -m app.ingest --playlist "<youtube playlist URL>"
# IpBlocked? ingest auto-falls back to yt-dlp. Also try a phone hotspot, or set
# YTDLP_COOKIES_FROM_BROWSER / WEBSHARE_PROXY_* in .env (see .env.example)
```

It contains chunked lecture text + timestamps + video IDs — no embeddings, no secrets — so it's
safe to commit.

## eval_questions.json

A demo `eval_questions.json` (matching the shipped 3Blue1Brown transcripts) is included, so the
harness runs immediately. For your own playlist, replace it with 5-10 hand-labeled
question/expected-video pairs (see `eval_questions.example.json` for the format). Then run:

```bash
python -m app.evaluate --pipeline hybrid       # what the deployed app actually runs
python -m app.evaluate --pipeline vector-only  # baseline, for comparison
```

Reports hit-rate@k and MRR — see `docs/architecture/v2-retrieval.md` for what these mean and
why they're worth showing live in the Day 1 architecture walkthrough.
