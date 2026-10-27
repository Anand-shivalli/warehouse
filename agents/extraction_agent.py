from google.adk.agents import LlmAgent
from schemas.models import ExtractionResult
from config import MODEL_PRO

# MODEL_PRO — listening to raw audio and extracting structured facts
# is a harder task than parsing clean text, worth the stronger model

extraction_agent = LlmAgent(
    name="ExtractionAgent",
    model=MODEL_PRO,
    instruction="""You will receive an audio recording of a field worker describing an incident,
and possibly a photo alongside it. Listen to the AUDIO ONLY and ignore any image content —
the photo is handled by a separate agent.

From the audio, extract:
- injury_occurred (true/false)
- treatment_described (what treatment, if any, was mentioned)
- location (where the incident happened)
- witnesses (names or references to other people present)
- narrative_summary (a brief summary of what was said)
- transcript (a verbatim transcription of what the speaker said, in order, with nothing added or corrected.
  Mark unclear words as [unclear]. This is a machine transcript and will be shown to reviewers as evidence.)

Return structured output only.""",
    output_schema=ExtractionResult,
    output_key="extraction_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)