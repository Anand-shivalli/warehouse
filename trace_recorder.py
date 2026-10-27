"""Per-agent run metrics from ADK events (no ADK import, so it can be tested without it).

run_agent() feeds every event to TraceRecorder.add(). summary() then gives one row per agent: status, start, duration,
event count, tool calls and token counts.

How timing is measured (it is an approximation, not a profiler):
  start    = timestamp of the event just before the agent's first event (or the run start)
  duration = timestamp of the agent's last event minus that start
Agents that run in parallel are all started at the run start, so name them in `parallel` (ExtractionAgent, VisionAgent).
Code steps (RetrievalStep, ReportValidator, gates) show their real, tiny durations. Token counts come from the model
response's usage metadata and are exact; they are absent for code steps.
"""
import time
from datetime import datetime, timezone

PARALLEL = ("ExtractionAgent", "VisionAgent")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class TraceRecorder:
    def __init__(self, parallel=PARALLEL):
        self.parallel = set(parallel)
        self.agents = {}
        self.t0 = self.last = time.time()

    def begin(self):
        """Call at the start of each run_agent(); time spent waiting for a human between runs is not charged to an agent."""
        self.t0 = self.last = time.time()

    def add(self, author, ts=None, usage=None, tool_calls=0, error=None, model=None):
        ts = ts or time.time()
        a = self.agents.get(author)
        if a is None:
            start = self.t0 if author in self.parallel else self.last
            a = self.agents[author] = {"agent": author, "start": start, "end": ts, "events": 0, "tool_calls": 0, "input_tokens": 0,
                                       "output_tokens": 0, "total_tokens": 0, "model": None, "error": None, "has_usage": False}
        a["end"] = max(a["end"], ts)
        a["events"] += 1
        a["tool_calls"] += tool_calls or 0
        if usage:
            a["has_usage"] = True
            a["input_tokens"] += getattr(usage, "prompt_token_count", 0) or 0
            a["output_tokens"] += getattr(usage, "candidates_token_count", 0) or 0
            a["total_tokens"] += getattr(usage, "total_token_count", 0) or 0
        if model:
            a["model"] = model
        if error:
            a["error"] = str(error)[:300]
        self.last = max(self.last, ts)

    def summary(self):
        rows = []
        for a in sorted(self.agents.values(), key=lambda x: (x["start"], x["end"])):
            rows.append({"agent": a["agent"], "status": "failed" if a["error"] else "completed", "started_at": _iso(a["start"]),
                         "ended_at": _iso(a["end"]), "duration_s": round(max(0.0, a["end"] - a["start"]), 2), "events": a["events"],
                         "tool_calls": a["tool_calls"], "model": a["model"], "error": a["error"],
                         "input_tokens": a["input_tokens"] if a["has_usage"] else None,
                         "output_tokens": a["output_tokens"] if a["has_usage"] else None,
                         "total_tokens": a["total_tokens"] if a["has_usage"] else None})
        return rows


def record_event(rec, ev):
    """Feed one ADK Event. Defensive about missing attributes, since ADK versions differ."""
    if rec is None or getattr(ev, "partial", False):
        return
    calls = 0
    try:
        calls = len(ev.get_function_calls() or [])
    except Exception:
        pass
    rec.add(getattr(ev, "author", None) or "unknown", getattr(ev, "timestamp", None), getattr(ev, "usage_metadata", None), calls,
            getattr(ev, "error_message", None) or getattr(ev, "error_code", None), getattr(ev, "model_version", None))
