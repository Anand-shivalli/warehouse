import asyncio
from google.adk.agents import ParallelAgent, SequentialAgent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

from agents.extraction_agent import extraction_agent
from agents.vision_agent import vision_agent
from agents.classifier_pipeline import classification_pipeline
from agents.review_compose_pipeline import reviewer_pass1, composer_agent, reviewer_pass2
from agents.review_gate import ReviewGate

# Stage 1: Extraction + Vision run in parallel
capture_analysis = ParallelAgent(
    name="CaptureAnalysis",
    sub_agents=[extraction_agent, vision_agent],
)

# Stage 3b: Composer -> Reviewer Pass 2 -> Gate2 (pass = done, fail = human queue)
gate2 = ReviewGate(
    name="Gate_Pass2", review_key="review2_result", next_agent=None, stage_name="Final report"
)
compose_and_verify = SequentialAgent(
    name="ComposeAndVerify",
    sub_agents=[composer_agent, reviewer_pass2, gate2],
)

# Stage 3a: Reviewer Pass 1 -> Gate1 (pass = continue to compose_and_verify, fail = human queue)
gate1 = ReviewGate(
    name="Gate_Pass1", review_key="review1_result", next_agent=compose_and_verify,
    stage_name="Pre-composition review",
)
review_and_compose = SequentialAgent(
    name="ReviewAndCompose",
    sub_agents=[reviewer_pass1, gate1],
)

# Full pipeline: Parallel capture -> Sequential classification -> Review/Compose/Review
pipeline = SequentialAgent(
    name="IncidentPipeline",
    sub_agents=[capture_analysis, classification_pipeline, review_and_compose],
)

session_service = InMemorySessionService()
runner = Runner(agent=pipeline, app_name="incident_pipeline", session_service=session_service)


def load_audio_part(path: str) -> types.Part:
    with open(path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type="audio/wav")


def load_image_part(path: str) -> types.Part:
    with open(path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")


async def run(audio_path: str, image_path: str):
    await session_service.create_session(
        app_name="incident_pipeline", user_id="field_worker_1", session_id="incident_001"
    )

    content = types.Content(
        role="user",
        parts=[load_audio_part(audio_path), load_image_part(image_path)],
    )

    async for event in runner.run_async(
        user_id="field_worker_1", session_id="incident_001", new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                print(f"[{event.author}] {text}")

    final_session = await session_service.get_session(
        app_name="incident_pipeline", user_id="field_worker_1", session_id="incident_001"
    )
    print("\n--- Final state ---")
    for key, value in final_session.state.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(run(
        audio_path="sample_data/audio/ttsMP3.com_VoiceText_2026-9-11_2-8-34.mp3",
        image_path="sample_data/images/incident1.png",
    ))