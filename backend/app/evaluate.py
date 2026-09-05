import argparse
import json
import logging
from pathlib import Path

from . import config
from .retrieval import retrieve
from .vectorstore import get_collection
from .vectorstore import query as vector_only_query

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _load_eval_set(path):
    data = json.loads(Path(path).read_text())
    if not data:
        raise ValueError(f"{path} has no eval questions")
    return data


def _rank_of_expected(hits, expected_video_id):
    for i, hit in enumerate(hits):
        if hit["metadata"]["video_id"] == expected_video_id:
            return i + 1  # 1-indexed
    return None


def evaluate(eval_set, top_k, pipeline):
    """Report hit-rate@k and MRR: for each labeled question, did the expected video
    show up in the top_k retrieved chunks, and how high did it rank?

    hit-rate@k answers "does the right source show up at all"; MRR rewards it showing
    up near the top, not just somewhere in the list. Run with --pipeline vector-only
    vs the default hybrid to see the v2 retrieval upgrade's actual effect on your
    own playlist, not just in theory.

    Also reports the top-hit rerank_score for hits vs misses (hybrid pipeline only) —
    this is what config.MIN_RERANK_SCORE should actually be calibrated from, not guessed.
    """
    hits_at_k = 0
    reciprocal_ranks = []
    hit_top_scores = []
    miss_top_scores = []

    for item in eval_set:
        question = item["question"]
        expected_video_id = item["expected_video_id"]

        results = pipeline(question, top_k)
        rank = _rank_of_expected(results, expected_video_id)
        top_score = results[0].get("rerank_score") if results else None

        if rank is not None:
            hits_at_k += 1
            reciprocal_ranks.append(1 / rank)
            if top_score is not None:
                hit_top_scores.append(top_score)
        else:
            reciprocal_ranks.append(0.0)
            if top_score is not None:
                miss_top_scores.append(top_score)

        status = f"rank {rank}" if rank else "MISS"
        score_note = f", top rerank_score={top_score:.2f}" if top_score is not None else ""
        logger.info('"%s" -> expected %s: %s%s', question, expected_video_id, status, score_note)

    n = len(eval_set)
    result = {"n": n, "hit_rate_at_k": hits_at_k / n, "mrr": sum(reciprocal_ranks) / n, "top_k": top_k}

    if hit_top_scores and miss_top_scores:
        suggested = (min(hit_top_scores) + max(miss_top_scores)) / 2
        result["suggested_min_rerank_score"] = suggested
        logger.info(
            "hit top-scores range [%.2f, %.2f], miss top-scores range [%.2f, %.2f] "
            "-> try MIN_RERANK_SCORE=%.2f",
            min(hit_top_scores),
            max(hit_top_scores),
            min(miss_top_scores),
            max(miss_top_scores),
            suggested,
        )

    return result


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality against a labeled question set")
    parser.add_argument("--eval-set", default=str(config.DATA_DIR / "eval_questions.json"))
    parser.add_argument("--top-k", type=int, default=config.TOP_K)
    parser.add_argument(
        "--pipeline",
        choices=["hybrid", "vector-only"],
        default="hybrid",
        help="hybrid = retrieval.retrieve() (what the deployed app runs); "
        "vector-only = vectorstore.query() baseline, for comparison",
    )
    args = parser.parse_args()

    logger.info("Building index from transcripts.json...")
    get_collection(rebuild=True)

    eval_set = _load_eval_set(args.eval_set)
    pipeline = retrieve if args.pipeline == "hybrid" else vector_only_query

    results = evaluate(eval_set, args.top_k, pipeline)
    logger.info(
        "hit_rate@%d = %.2f, MRR = %.3f, over %d questions (pipeline=%s)",
        results["top_k"],
        results["hit_rate_at_k"],
        results["mrr"],
        results["n"],
        args.pipeline,
    )


if __name__ == "__main__":
    main()
