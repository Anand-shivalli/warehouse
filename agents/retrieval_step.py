import asyncio

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types

import retrieval


class RetrievalStep(BaseAgent):
    """Plain-code step (no LLM) that runs after classification. Searches the indexed SOPs, guidelines and RoHS documents
    and writes retrieved_context / retrieval_hits / retrieval_log / retrieval_status to state.
    A retrieval failure must never stop a report, so errors become an empty context plus a status the reviewers can see."""

    async def _run_async_impl(self, ctx):
        s = ctx.session.state
        state = {k: s.get(k) for k in ("extraction_result", "vision_result", "category_result", "signals")}
        try:
            delta = await asyncio.to_thread(retrieval.run_retrieval, state)
        except Exception as e:
            delta = retrieval.empty_delta(f"unavailable: {type(e).__name__}: {e}")
        n = len(delta["retrieval_hits"])
        yield Event(author=self.name, actions=EventActions(state_delta=delta),
                    content=types.Content(parts=[types.Part(text=f"Retrieved {n} passage(s); status: {delta['retrieval_status']}.")]))
