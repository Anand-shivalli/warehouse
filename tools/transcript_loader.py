import json


def load_transcript(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_transcript(data: dict) -> str:
    """One line per segment: [start-end seconds] SPEAKER_xx: text"""
    return "\n".join(
        f"[{s['start']:.1f}s-{s['end']:.1f}s] {s.get('speaker', 'UNKNOWN')}: {s['text']}"
        for s in data.get("segments", [])
    )


def slice_span(data: dict, start: float, end: float, pad: float = 10.0) -> dict:
    lo, hi = max(0.0, start - pad), end + pad
    segs = [s for s in data.get("segments", []) if s["end"] >= lo and s["start"] <= hi]
    return {**data, "segments": segs}


def build_incident_text(data: dict, triage: dict, pad: float = 10.0) -> str:
    """Flagged span (plus padding) and the speaker roles triage inferred.
    Falls back to the full transcript if the span is unusable."""
    start = float(triage.get("start_sec") or 0.0)
    end = float(triage.get("end_sec") or 0.0)

    span = data
    if end > start:
        sliced = slice_span(data, start, end, pad)
        if sliced["segments"]:
            span = sliced

    header = []
    if triage.get("reporter_speaker"):
        header.append(f"Main speaker describing the incident: {triage['reporter_speaker']}")
    if triage.get("involved_speakers"):
        header.append("Other speakers involved: " + ", ".join(triage["involved_speakers"]))
    prefix = ("\n".join(header) + "\n\n") if header else ""
    return prefix + format_transcript(span)