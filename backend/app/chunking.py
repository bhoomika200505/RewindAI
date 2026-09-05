def chunk_transcript(entries, window_seconds=45, overlap_seconds=10):
    """Group timestamped transcript entries into overlapping fixed-duration windows.

    Each output chunk keeps the start_seconds of its first entry, so a citation
    on that chunk seeks the video to where the covered speech actually begins.

    Windows overlap by `overlap_seconds` so an answer that straddles a window
    boundary still shows up whole in at least one chunk, instead of being split
    in half across two chunks that individually look irrelevant.
    """
    chunks = []
    window = []

    for entry in entries:
        text = entry.get("text", "").strip()
        if not text:
            continue

        start = entry["start"]
        duration = entry.get("duration", 0)
        window.append((text, start, duration))

        window_start = window[0][1]
        window_end = start + duration

        if window_end - window_start >= window_seconds:
            chunks.append({"text": " ".join(t for t, _, _ in window), "start_seconds": int(window_start)})
            cutoff = window_end - overlap_seconds
            window = [e for e in window if e[1] + e[2] > cutoff]

    if window:
        chunks.append({"text": " ".join(t for t, _, _ in window), "start_seconds": int(window[0][1])})

    return chunks
