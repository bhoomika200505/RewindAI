import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHUNK_WINDOW_SECONDS = int(os.environ.get("CHUNK_WINDOW_SECONDS", "45"))
CHUNK_OVERLAP_SECONDS = int(os.environ.get("CHUNK_OVERLAP_SECONDS", "10"))
TOP_K = int(os.environ.get("TOP_K", "5"))

# v2 retrieval: how many candidates to pull before reranking/MMR narrow it down to TOP_K.
RETRIEVE_CANDIDATES = int(os.environ.get("RETRIEVE_CANDIDATES", "15"))
RERANK_MODEL = os.environ.get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
MMR_LAMBDA = float(os.environ.get("MMR_LAMBDA", "0.7"))

# v2 guardrail threshold, replacing the raw vector MAX_DISTANCE cutoff above. Cross-encoder
# scores are NOT 0-centered in practice — on a small test corpus, genuinely relevant top
# hits scored anywhere from -0.7 to -8, while irrelevant questions clustered near -11. This
# default is deliberately permissive (biased toward answering, since the system prompt's
# "say you don't know" instruction is the real backstop against hallucination). Don't guess
# a tighter number — run `python -m app.evaluate` against your own playlist, which reports
# the actual score gap between hits and misses and suggests a calibrated value.
MIN_RERANK_SCORE = float(os.environ.get("MIN_RERANK_SCORE", "-8.0"))

# Chroma uses L2 distance over MiniLM's normalized embeddings (~0-2 range).
# Retrieved chunks above this are treated as "not actually relevant" for the guardrail.
# Tune against your own playlist if the guardrail fires too often or not enough.
MAX_DISTANCE = float(os.environ.get("MAX_DISTANCE", "1.2"))

# Ingest-only escape hatch: if YouTube IP-blocks transcript fetching (common on cloud IPs,
# or a home IP rate-limited after many requests), set these to route requests through a
# Webshare residential proxy (https://www.webshare.io — pick "Residential"). Left blank,
# ingest fetches directly. Not needed at runtime — the deployed app never calls YouTube.
WEBSHARE_PROXY_USERNAME = os.environ.get("WEBSHARE_PROXY_USERNAME", "")
WEBSHARE_PROXY_PASSWORD = os.environ.get("WEBSHARE_PROXY_PASSWORD", "")

# Ingest fallback: when youtube-transcript-api is blocked, ingest retries via yt-dlp, which
# emulates YouTube clients and can read your browser's cookies — often clears a soft-blocked
# home IP. Set to a browser name (chrome | firefox | edge | safari | brave) to use its cookies;
# leave blank to run the yt-dlp fallback without cookies.
YTDLP_COOKIES_FROM_BROWSER = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "")

BACKEND_DIR = Path(__file__).resolve().parent.parent
SOLUTION_DIR = BACKEND_DIR.parent
DATA_DIR = SOLUTION_DIR / "data"
TRANSCRIPTS_PATH = Path(os.environ.get("TRANSCRIPTS_PATH", str(DATA_DIR / "transcripts.json")))
CHROMA_DIR = str(DATA_DIR / "chroma_db")
COLLECTION_NAME = "lecture_chunks"
