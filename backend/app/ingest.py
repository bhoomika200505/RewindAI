import argparse
import json
import logging
from pathlib import Path

import yt_dlp
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

from . import config
from .chunking import chunk_transcript

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _make_yt_api():
    # If Webshare proxy creds are set, route transcript fetches through them — the escape
    # hatch for when YouTube IP-blocks you. Otherwise fetch directly.
    if config.WEBSHARE_PROXY_USERNAME and config.WEBSHARE_PROXY_PASSWORD:
        logger.info("Fetching transcripts through Webshare proxy")
        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=config.WEBSHARE_PROXY_USERNAME,
                proxy_password=config.WEBSHARE_PROXY_PASSWORD,
            )
        )
    return YouTubeTranscriptApi()


_yt_api = _make_yt_api()


def get_playlist_videos(playlist_url):
    # Accepts a playlist URL or a single-video URL. yt-dlp returns "entries" for a playlist;
    # for one video there's no "entries", so treat the info dict itself as the single entry.
    ydl_opts = {"extract_flat": True, "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    if not info:
        return []
    entries = info.get("entries")
    if entries is None:
        entries = [info]
    return [{"video_id": e["id"], "title": e.get("title") or e["id"]} for e in entries if e.get("id")]


def _pick_json3_url(tracks):
    """From a yt-dlp subtitles/automatic_captions dict, return the English json3 caption URL."""
    for lang in ("en", "en-US", "en-GB", "en-orig"):
        for fmt in tracks.get(lang, []):
            if fmt.get("ext") == "json3":
                return fmt.get("url")
    return None


def _fetch_transcript_ytdlp(video_id):
    """Fallback transcript fetch via yt-dlp. More block-resistant than youtube-transcript-api
    (it emulates YouTube clients and can use browser cookies). Resolves the video's caption
    tracks, then fetches the English json3 track directly — returns the same
    [{text, start, duration}] shape chunking expects, or None if there are no captions.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        # We only want captions; don't abort when no downloadable video format is offered
        # (that path raises "Requested format is not available").
        "ignore_no_formats_error": True,
    }
    if config.YTDLP_COOKIES_FROM_BROWSER:
        ydl_opts["cookiesfrombrowser"] = (config.YTDLP_COOKIES_FROM_BROWSER,)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        sub_url = _pick_json3_url(info.get("subtitles") or {}) or _pick_json3_url(
            info.get("automatic_captions") or {}
        )
        if not sub_url:
            return None
        raw = ydl.urlopen(sub_url).read().decode("utf-8", "replace")

    return _parse_json3(json.loads(raw)) or None


def _parse_json3(data):
    """Turn YouTube's json3 caption payload into [{text, start, duration}] (seconds)."""
    entries = []
    for event in data.get("events", []):
        segs = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text:
            continue
        entries.append(
            {
                "text": text,
                "start": event.get("tStartMs", 0) / 1000.0,
                "duration": event.get("dDurationMs", 0) / 1000.0,
            }
        )
    return entries


def fetch_transcript(video_id):
    # Primary: youtube-transcript-api 1.x (.fetch().to_raw_data() -> [{text, start, duration}]).
    # On a block/error, fall back to yt-dlp — it emulates YouTube clients and can use browser
    # cookies (set YTDLP_COOKIES_FROM_BROWSER), which often clears a soft-blocked home IP.
    try:
        return _yt_api.fetch(video_id).to_raw_data()
    except (TranscriptsDisabled, NoTranscriptFound):
        logger.warning("No captions for video %s — skipping", video_id)
        return None
    except Exception as exc:
        logger.warning("youtube-transcript-api failed for %s (%s) — trying yt-dlp fallback", video_id, exc)

    try:
        entries = _fetch_transcript_ytdlp(video_id)
        if entries:
            logger.info("Fetched transcript for %s via yt-dlp fallback", video_id)
            return entries
        logger.warning("yt-dlp fallback found no captions for %s — skipping", video_id)
    except Exception as exc:
        logger.warning("yt-dlp fallback failed for %s: %s — skipping", video_id, exc)
    return None


def build_transcripts_json(playlist_url, output_path, window_seconds, overlap_seconds=None):
    videos = get_playlist_videos(playlist_url)
    logger.info("Found %d videos in playlist", len(videos))

    overlap_seconds = config.CHUNK_OVERLAP_SECONDS if overlap_seconds is None else overlap_seconds
    all_chunks = []
    indexed_count = 0
    skipped_count = 0

    for video in videos:
        video_id = video["video_id"]
        title = video["title"]
        entries = fetch_transcript(video_id)
        if not entries:
            skipped_count += 1
            continue

        chunks = chunk_transcript(entries, window_seconds=window_seconds, overlap_seconds=overlap_seconds)
        for chunk in chunks:
            all_chunks.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "text": chunk["text"],
                    "start_seconds": chunk["start_seconds"],
                    "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        indexed_count += 1
        logger.info("Chunked %s (%s) into %d chunks", video_id, title, len(chunks))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(all_chunks, indent=2))
    logger.info(
        "Wrote %d chunks from %d videos to %s (%d skipped: no captions)",
        len(all_chunks),
        indexed_count,
        output_path,
        skipped_count,
    )


def main():
    parser = argparse.ArgumentParser(description="Ingest a YouTube playlist into transcripts.json")
    parser.add_argument("--playlist", required=True, help="YouTube playlist URL")
    parser.add_argument("--output", default=str(config.TRANSCRIPTS_PATH))
    parser.add_argument("--window-seconds", type=int, default=config.CHUNK_WINDOW_SECONDS)
    parser.add_argument("--overlap-seconds", type=int, default=config.CHUNK_OVERLAP_SECONDS)
    args = parser.parse_args()
    build_transcripts_json(args.playlist, args.output, args.window_seconds, args.overlap_seconds)


if __name__ == "__main__":
    main()
