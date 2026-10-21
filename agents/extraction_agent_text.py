from google.adk.agents import LlmAgent
from schemas.models import ExtractionResult
from config import MODEL_FLASH

text_extraction_agent = LlmAgent(
    name="TextExtractionAgent",
    model=MODEL_FLASH,
    instruction="""You will receive a speaker-labelled transcript of a workplace conversation
that discusses an incident. Speaker labels (SPEAKER_00, SPEAKER_01, ...) are anonymous.
Use only what the speakers actually say. Do not assume or invent details.

Transcript:
{incident_text}

Extract:
- injury_occurred (true/false, based on what the speakers say about anyone being hurt)
- treatment_described (what treatment was mentioned, or "none mentioned")
- location (where it happened, or "not stated")
- witnesses (names mentioned, or anonymous labels such as SPEAKER_00 for people who were present)
- narrative_summary (a brief summary of what happened, attributing statements to speakers where it matters)

Return structured output only.""",
    output_schema=ExtractionResult,
    output_key="extraction_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)