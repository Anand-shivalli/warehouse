import re

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types

# Compliance is decided by a person. A report may quote a verified RoHS record but must not declare a verdict.
_VERDICT = re.compile(r"\b(?:non[- ]?compliant|not compliant|is compliant|are compliant|rohs[- ]compliant|compliant with rohs)\b", re.I)


def validate_report(report, hits) -> dict:
    """Deterministic checks on the composed report. Returns the same shape as ReviewResult plus the list of failed checks."""
    problems = []
    if not report or not (report.get("report_text") or "").strip():
        return {"review_pass": False, "notes": "No report was composed.", "problems": ["no_report"]}
    sids = {h["sid"] for h in (hits or [])}
    if not report.get("observed"):
        problems.append("The report lists no observed facts.")
    for i, rec in enumerate(report.get("recommendations") or [], start=1):
        ids = rec.get("source_ids") or []
        if not ids:
            problems.append(f"Recommendation {i} cites no source.")
        for x in ids:
            if x not in sids:
                problems.append(f"Recommendation {i} cites {x}, which was not retrieved.")
    text = " ".join([report.get("report_text") or "", *map(str, report.get("interpretation") or []),
                     *[r.get("action", "") for r in report.get("recommendations") or []]])
    if _VERDICT.search(text):
        problems.append("The report states a RoHS/compliance verdict; that is for a human reviewer to decide.")
    return {"review_pass": not problems, "notes": " ".join(problems), "problems": problems}


def _norm(s) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(s).casefold()).split())


def facts_text(state) -> str:
    """All text the agents were given as facts about the incident, flattened, for checking quotes against."""
    out = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    for k in ("extraction_result", "vision_result", "incident_text"):
        walk(state.get(k))
    return _norm(" ".join(out))


def check_procedure(dev, hits, facts: str) -> dict:
    """Keep only procedure-check points that cite a retrieved passage and, when they claim followed / possible deviation,
    quote words that really appear in the incident facts. Dropped points are counted and explained, never shown."""
    sids = {h["sid"] for h in (hits or [])}
    kept, dropped = [], []
    for p in (dev or {}).get("points") or []:
        status, quote = p.get("status"), _norm(p.get("evidence_quote") or "")
        if p.get("source_id") not in sids:
            dropped.append(f"cites {p.get('source_id')}, which was not retrieved")
        elif status not in ("followed", "possible_deviation", "cannot_tell"):
            dropped.append(f"unknown status {status}")
        elif status != "cannot_tell" and (len(quote) < 6 or quote not in facts):
            dropped.append(f"'{p.get('requirement', '')[:40]}': quote not found in the incident facts")
        else:
            kept.append({k: p.get(k) for k in ("requirement", "source_id", "status", "evidence_quote", "explanation")})
    return {"points": kept, "dropped": dropped}


class ReportValidator(BaseAgent):
    """Code check between Composer and ReviewerPass2: every recommendation traces to a passage that was actually retrieved."""

    async def _run_async_impl(self, ctx):
        s = ctx.session.state
        result = validate_report(s.get("report_text"), s.get("retrieval_hits"))
        checked = check_procedure(s.get("deviation_result"), s.get("retrieval_hits"), facts_text({k: s.get(k) for k in ("extraction_result", "vision_result", "incident_text")}))
        yield Event(author=self.name, actions=EventActions(state_delta={"validation_result": result, "deviation_checked": checked}),
                    content=types.Content(parts=[types.Part(text="Validation " + ("passed." if result["review_pass"] else "failed: " + result["notes"]))]))
