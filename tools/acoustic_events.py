import json


def load_events(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_alert(data: dict, top_n: int = 3) -> str:
    events = sorted(data.get("events", []), key=lambda e: e["score"], reverse=True)[:top_n]
    lines = ["Acoustic anomaly detected."]
    for e in events:
        lines.append(f"  - {e['label']} at {e['start_sec']:.1f}s (score {e['score']:.2f})")
    lines.append("Submit report?")
    return "\n".join(lines)


def ask_to_report(data: dict) -> bool:
    """Step 1: priority alert. The human decides whether a report is started."""
    if not data.get("anomaly_detected"):
        print("No acoustic anomaly detected.")
        return False
    print(build_alert(data))
    return input("[y/N] ").strip().lower() == "y"