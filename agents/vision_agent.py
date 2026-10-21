from google.adk.agents import LlmAgent
from schemas.models import VisionResult
from config import MODEL_PRO

vision_agent = LlmAgent(
    name="VisionAgent",
    model=MODEL_PRO,
    instruction="""You will receive a photo/video of an incident scene, and possibly an audio
recording alongside it. Analyze the IMAGE ONLY and ignore any audio content —
the audio is handled by a separate agent.

From the image, identify:
- hazard_type (what kind of hazard is visible, if any)
- visible_injury_severity (none/minor/moderate/severe, based only on what's visible)
- visible_damage (any equipment or property damage visible)
- description (brief description of the scene)

Return structured output only.""",
    output_schema=VisionResult,
    output_key="vision_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)