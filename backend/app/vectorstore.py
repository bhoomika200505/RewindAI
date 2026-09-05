import json
import logging
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

from . import config

logger = logging.getLogger(__name__)

# This chromadb pins a posthog whose capture() signature mismatches, so it logs a
# spammy ERROR on every operation ("capture() takes 1 positional argument..."). The
# anonymized_telemetry setting doesn't stop the failing send in this version, so mute
# the telemetry logger directly — it's harmless noise, not an app error.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

_client = None
_collection = None
_bm25 = None
_bm25_ids = []
_chunks_by_id = {}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    return _client


def _embedding_function():
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=config.EMBEDDING_MODEL)


def get_collection(rebuild=False):
    """Get the Chroma collection, rebuilding it (and the BM25 index) from transcripts.json
    if requested. Called with rebuild=True once at app startup — see main.py's lifespan
    hook and docs/deploy.md for why the index isn't just persisted to disk.
    """
    global _collection
    if _collection is not None and not rebuild:
        return _collection

    client = _get_client()
    ef = _embedding_function()

    if rebuild:
        try:
            client.delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass

    collection = client.get_or_create_collection(name=config.COLLECTION_NAME, embedding_function=ef)

    if rebuild:
        _populate_from_transcripts(collection)

    _collection = collection
    return _collection


def _populate_from_transcripts(collection):
    global _bm25, _bm25_ids, _chunks_by_id

    transcripts_path = Path(config.TRANSCRIPTS_PATH)
    if not transcripts_path.exists():
        logger.warning(
            "No transcripts.json found at %s — collection will be empty until `python -m app.ingest` runs",
            transcripts_path,
        )
        _bm25, _bm25_ids, _chunks_by_id = None, [], {}
        return

    chunks = json.loads(transcripts_path.read_text())
    if not chunks:
        logger.warning("transcripts.json is empty — nothing to index")
        _bm25, _bm25_ids, _chunks_by_id = None, [], {}
        return

    ids = [f"{c['video_id']}-{c['start_seconds']}" for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "video_id": c["video_id"],
            "title": c["title"],
            "start_seconds": c["start_seconds"],
            "youtube_url": c["youtube_url"],
        }
        for c in chunks
    ]

    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    # Mirror the same chunks into an in-memory BM25 index so keyword_search() can catch
    # exact-term/acronym queries dense embeddings tend to miss (see retrieval.py).
    _chunks_by_id = {id_: {"text": doc, "metadata": meta} for id_, doc, meta in zip(ids, documents, metadatas)}
    _bm25_ids = ids
    _bm25 = BM25Okapi([_tokenize(doc) for doc in documents])

    logger.info("Indexed %d chunks into Chroma + BM25", len(ids))


def vector_search(question, n):
    collection = get_collection()
    if collection.count() == 0:
        return []
    n = min(n, collection.count())
    results = collection.query(query_texts=[question], n_results=n)
    hits = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for id_, doc, meta, distance in zip(ids, docs, metas, distances):
        hits.append({"id": id_, "text": doc, "metadata": meta, "distance": distance})
    return hits


def keyword_search(question, n):
    if not _bm25:
        return []
    scores = _bm25.get_scores(_tokenize(question))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
    hits = []
    for i in ranked:
        if scores[i] <= 0:
            continue
        id_ = _bm25_ids[i]
        chunk = _chunks_by_id[id_]
        hits.append({"id": id_, "text": chunk["text"], "metadata": chunk["metadata"], "score": float(scores[i])})
    return hits


def get_embeddings(ids):
    collection = get_collection()
    if not ids:
        return {}
    result = collection.get(ids=ids, include=["embeddings"])
    return {id_: emb for id_, emb in zip(result["ids"], result["embeddings"])}


def query(question, top_k=None):
    """Vector-only retrieval — this is the base pipeline (what starter/ builds).
    See retrieval.retrieve() for the hybrid+rerank+MMR pipeline this app actually runs.
    """
    return vector_search(question, top_k or config.TOP_K)
