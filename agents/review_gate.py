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

    async def _run_async_impl(self, ctx):
        review = ctx.session.state.get(self.review_key)

        if review and review.get("review_pass"):
            if self.next_agent:
                async for event in self.next_agent.run_async(ctx):
                    yield event
            else:
                yield Event(
                    author=self.name,
                    content=types.Content(parts=[types.Part(text=f"{self.stage_name} passed.")]),
                )
        else:
            notes = review.get("notes", "unspecified issue") if review else "review result missing"
            # TODO: write to Firestore human review queue here
            # flag_for_human_review(ctx.session.id, notes)
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Routed to human review: {notes}")]
                ),
            )