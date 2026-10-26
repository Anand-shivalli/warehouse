from typing import List

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types


class ReviewGate(BaseAgent):
    """Checks a review result in state and either continues to the next agent
    or routes to human review. This is the custom conditional-branching piece
    ADK's built-in Sequential/Parallel/Loop primitives don't provide out of the box."""

    review_key: str             # e.g. "review1_result" or "review2_result"
    next_agent: object = None   # agent to run if review passes; None if this is the last gate
    stage_name: str = "review"
    extra_keys: List[str] = []  # more results that must also pass, e.g. ["validation_result"]

    async def _run_async_impl(self, ctx):
        keys = [self.review_key, *self.extra_keys]
        reviews = [ctx.session.state.get(k) for k in keys]
        failed = [(k, r) for k, r in zip(keys, reviews) if not (r and r.get("review_pass"))]
        review = None if failed else reviews[0]

        if not failed:
            if self.next_agent:
                async for event in self.next_agent.run_async(ctx):
                    yield event
            else:
                yield Event(
                    author=self.name,
                    content=types.Content(parts=[types.Part(text=f"{self.stage_name} passed.")]),
                )
        else:
            notes = "; ".join(f"{k}: {(r.get('notes') or 'unspecified issue') if r else 'result missing'}" for k, r in failed)
            # TODO: write to Firestore human review queue here
            # flag_for_human_review(ctx.session.id, notes)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Routed to human review: {notes}")]
                ),
            )