from google.adk.agents import LlmAgent
from schemas.models import TriageResult
from config import MODEL_FLASH

triage_agent = LlmAgent(
    name="ConversationTriage",
    model=MODEL_FLASH,
    instruction="""You are reviewing a recorded workplace conversation between warehouse staff.
Speakers are anonymous labels (SPEAKER_00, SPEAKER_01, ...). Each line looks like:
[start-end seconds] SPEAKER_xx: text

Conversation:
{conversation_text}

Decide whether the conversation contains a workplace safety incident being described or reacted to:
an injury, a near miss, a spill or leak, equipment or property damage, a fall, a fire or smoke event,
or a clear safety hazard. Ordinary work chat (schedules, small talk, routine instructions) is not an incident.
Err on the side of flagging: a person confirms before any report is created.

Return:
- incident_detected: true or false
- start_sec and end_sec: the time span covering the whole incident discussion, including how it started
- reporter_speaker: the speaker mainly describing what happened
- involved_speakers: other speakers who were involved in or witnessed it
- summary: one or two sentences on what the conversation says happened
- confidence: low, medium or high
If there is no incident, set incident_detected to false and leave the other fields empty or zero.""",
    output_schema=TriageResult,
    output_key="triage_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)