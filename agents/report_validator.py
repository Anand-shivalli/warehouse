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


class ReportValidator(BaseAgent):
    """Code check between Composer and ReviewerPass2: every recommendation traces to a passage that was actually retrieved."""

    async def _run_async_impl(self, ctx):
        s = ctx.session.state
        result = validate_report(s.get("report_text"), s.get("retrieval_hits"))
        yield Event(author=self.name, actions=EventActions(state_delta={"validation_result": result}),
                    content=types.Content(parts=[types.Part(text="Validation " + ("passed." if result["review_pass"] else "failed: " + result["notes"]))]))
