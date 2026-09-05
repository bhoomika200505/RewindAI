import logging

from groq import Groq

from . import config
from .retrieval import retrieve

logger = logging.getLogger(__name__)

_client = None

SYSTEM_PROMPT = """You are a teaching assistant answering questions from a set of lecture \
transcript excerpts provided below as context. Each excerpt is labeled with a source number.

How to answer:
- Explain the concept fully and clearly in your own words, synthesizing across the excerpts into \
one coherent answer — aim for a substantive paragraph, not a one-line summary.
- Use ONLY the provided context; do not add outside facts. If the context genuinely doesn't \
cover the question, say exactly: "I couldn't find that in these lectures." Don't guess.
- Don't narrate the sources ("Source 2 says…"). Explain the idea directly and cite by appending \
the source number in parentheses after the claim it supports, e.g. "…how much a function is \
changing at each point (Source 1)."
- Be specific: include the concrete details, examples, and intuition the excerpts give. Teach the \
concept rather than describing what the excerpts contain."""


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _format_timestamp(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _format_context(hits):
    lines = []
    for i, hit in enumerate(hits, start=1):
        meta = hit["metadata"]
        timestamp = _format_timestamp(meta["start_seconds"])
        lines.append(f'[Source {i} — "{meta["title"]}" @ {timestamp}]\n{hit["text"]}')
    return "\n\n".join(lines)


def _rewrite_query(question, history):
    if not history:
        return question
    recent = history[-4:]
    convo = "\n".join(f"{turn['role']}: {turn['content']}" for turn in recent)
    return f"{convo}\nuser: {question}"


def _relevant_hits(hits):
    return [h for h in hits if h.get("rerank_score", 0.0) >= config.MIN_RERANK_SCORE]


def _citations_from_hits(hits):
    return [
        {
            "index": i + 1,
            "title": h["metadata"]["title"],
            "video_id": h["metadata"]["video_id"],
            "start_seconds": h["metadata"]["start_seconds"],
            "youtube_url": h["metadata"]["youtube_url"],
            "timestamp": _format_timestamp(h["metadata"]["start_seconds"]),
        }
        for i, h in enumerate(hits)
    ]


def _empty_stream():
    yield "I couldn't find that in these lectures."


def answer_stream(question, history=None):
    """Retrieve relevant chunks and return (token_generator, citations) for the question.

    Returns immediately with citations (retrieval already happened) so the caller
    can send them ahead of the token stream.
    """
    history = history or []
    search_query = _rewrite_query(question, history)
    hits = retrieve(search_query, top_k=config.TOP_K)
    relevant = _relevant_hits(hits)

    if not relevant:
        return _empty_stream(), []

    citations = _citations_from_hits(relevant)
    context = _format_context(relevant)

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\nContext:\n" + context}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    client = _get_client()

    def token_gen():
        try:
            stream = client.chat.completions.create(model=config.GROQ_MODEL, messages=messages, stream=True)
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except GeneratorExit:
            # Client disconnected mid-stream — let Groq's connection close, don't retry/swallow.
            raise
        except Exception as exc:
            logger.exception("Groq streaming failed")
            yield f"\n\n[Error: could not reach the model — {exc}]"

    return token_gen(), citations
