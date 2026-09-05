import logging
import math

import numpy as np
from sentence_transformers import CrossEncoder

from . import config, vectorstore

logger = logging.getLogger(__name__)

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(config.RERANK_MODEL)
    return _reranker


def reciprocal_rank_fusion(vector_hits, keyword_hits, k=60):
    """Merge two ranked hit lists into one, by id, using Reciprocal Rank Fusion.

    RRF only needs each list's rank order (not raw scores), which sidesteps the fact
    that Chroma's L2 distance and BM25's score live on completely different scales.
    """
    scores = {}
    info = {}
    for rank, hit in enumerate(vector_hits):
        scores[hit["id"]] = scores.get(hit["id"], 0.0) + 1.0 / (k + rank + 1)
        info.setdefault(hit["id"], hit)
    for rank, hit in enumerate(keyword_hits):
        scores[hit["id"]] = scores.get(hit["id"], 0.0) + 1.0 / (k + rank + 1)
        info.setdefault(hit["id"], hit)

    fused_ids = sorted(scores, key=lambda id_: scores[id_], reverse=True)
    return [info[id_] for id_ in fused_ids]


def rerank(question, candidates):
    """Score each (question, chunk) pair with a cross-encoder and sort by relevance.

    Vector/keyword search only look at the chunk in isolation; a cross-encoder looks at
    the question and chunk together, which is slower (why it only runs over ~15
    candidates, not the whole corpus) but meaningfully more precise.
    """
    if not candidates:
        return []
    reranker = _get_reranker()
    pairs = [(question, c["text"]) for c in candidates]
    scores = reranker.predict(pairs)
    for c, score in zip(candidates, scores):
        c["rerank_score"] = float(score)
    return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)


def _cosine(a, b):
    a, b = np.array(a), np.array(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)


def mmr_filter(candidates, top_k, lambda_=None):
    """Pick a diverse top_k from reranked `candidates` via Maximal Marginal Relevance.

    Without this, two near-duplicate chunks (the same point recapped in two lectures)
    can both score well and crowd out a third, genuinely different, relevant chunk.
    MMR trades a bit of raw relevance for coverage — `lambda_` controls how much.
    """
    lambda_ = config.MMR_LAMBDA if lambda_ is None else lambda_
    if len(candidates) <= top_k:
        return candidates

    embeddings = vectorstore.get_embeddings([c["id"] for c in candidates])
    if not embeddings:
        return candidates[:top_k]

    # Sigmoid the raw cross-encoder logit into (0, 1) rather than min-max normalizing
    # across just this candidate batch — min-max always drives the batch's weakest
    # candidate's relevance to exactly 0, so it can never win on diversity alone even
    # when its absolute score is perfectly good. Sigmoid keeps relevance tied to the
    # score's own meaning instead of wherever it happens to rank within this batch.
    def relevance(c):
        return 1.0 / (1.0 + math.exp(-c["rerank_score"]))

    selected = []
    remaining = list(candidates)

    while remaining and len(selected) < top_k:
        best, best_score = None, float("-inf")
        for c in remaining:
            emb = embeddings.get(c["id"])
            diversity = 0.0
            if emb is not None and selected:
                sims = [_cosine(emb, embeddings[s["id"]]) for s in selected if embeddings.get(s["id"]) is not None]
                diversity = max(sims, default=0.0)
            mmr_score = lambda_ * relevance(c) - (1 - lambda_) * diversity
            if mmr_score > best_score:
                best, best_score = c, mmr_score
        selected.append(best)
        remaining.remove(best)

    return selected


def retrieve(question, top_k=None):
    """Hybrid retrieval: vector + keyword fusion -> cross-encoder rerank -> MMR diversity.

    This is the pipeline this app actually runs. See vectorstore.query() for the
    vector-only base pipeline that starter/ builds during the core workshop hours.
    """
    top_k = top_k or config.TOP_K
    n = config.RETRIEVE_CANDIDATES

    vector_hits = vectorstore.vector_search(question, n)
    keyword_hits = vectorstore.keyword_search(question, n)
    if not vector_hits and not keyword_hits:
        return []

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits)[:n]
    reranked = rerank(question, fused)
    return mmr_filter(reranked, top_k)
