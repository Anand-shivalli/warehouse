import argparse
import asyncio
import os
import uuid

from google.adk.agents import SequentialAgent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

# Agents
from agents.triage_agent import triage_agent
from agents.extraction_agent_text import text_extraction_agent
from agents.extraction_agent import extraction_agent
from agents.vision_agent import vision_agent
from agents.classifier_pipeline import classification_pipeline
from agents.review_compose_pipeline import reviewer_pass1, composer_agent, reviewer_pass2
from agents.review_gate import ReviewGate

# Tools
from tools.transcript_loader import load_transcript, format_transcript, build_incident_text
from tools.acoustic_events import load_events, ask_to_report

APP = "incident_pipeline_ambient"

NO_PHOTO_VISION = {
    "hazard_type": "not available",
    "visible_injury_severity": "not available",
    "visible_damage": "not available",
    "description": "No photo was provided for this incident (audio-only report).",
}

# 1. Review & Compose pipeline (Unique hierarchy)
gate2 = ReviewGate(
    name="Gate_Pass2", review_key="review2_result", next_agent=None, stage_name="Final report"
)
compose_and_verify = SequentialAgent(
    name="ComposeAndVerify", sub_agents=[composer_agent, reviewer_pass2, gate2]
)
gate1 = ReviewGate(
    name="Gate_Pass1", review_key="review1_result", next_agent=compose_and_verify,
    stage_name="Pre-composition review",
)
review_and_compose = SequentialAgent(
    name="ReviewAndCompose", sub_agents=[reviewer_pass1, gate1]
)

# 2. Downstream classification + review (Has classification_pipeline and review_and_compose as children)
downstream_pipeline = SequentialAgent(
    name="DownstreamPipeline",
    sub_agents=[classification_pipeline, review_and_compose],
)

# 3. Branch A extractor pipeline (Vision + Direct Extraction)
branch_a_intake = SequentialAgent(
    name="DirectIntake",
    sub_agents=[vision_agent, extraction_agent],
)

# Branch B extractor is just `text_extraction_agent` on its own.


async def run_pipeline_with_session(session_service, session_id, user_id, agent):
    """Executes a runner on an existing session state."""
    runner = Runner(agent=agent, app_name=APP, session_service=session_service)
    content = types.Content(
        role="user", parts=[types.Part(text="Process the data in the session state.")]
    )
    events = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                events.append((event.author, text))
    return events


async def main(dialogue_path: str, events_path: str | None):
    # Step 0 + 1: YAMNet anomaly check if file supplied
    if events_path:
        events_data = load_events(events_path)
        if not ask_to_report(events_data):
            print("No report requested.")
            return

    # Select intake mode
    branch = input(
        "\nSelect Intake Mode:\n  [A] Direct report (Upload photo/voice note)\n  [B] Team dialogue (WhisperX transcript)\nEnter choice [A/B]: "
    ).strip().upper()

    session_service = InMemorySessionService()
    user_id, session_id = "worker_1", str(uuid.uuid4())
    all_events = []

    # =========================================================
    # BRANCH A: Direct Media / Photos / Audio Recording
    # =========================================================
    if branch == "A":
        print("\n--- Running Branch A (Direct Intake) ---")
        img_path = input("Enter path to incident photo (or press Enter if none): ").strip()
        voice_path = input("Enter path to audio recording (or press Enter if text only): ").strip()

        initial_state = {}
        if img_path and os.path.exists(img_path):
            initial_state["image_path"] = img_path
        else:
            initial_state["vision_result"] = NO_PHOTO_VISION

        if voice_path and os.path.exists(voice_path):
            initial_state["audio_path"] = voice_path
        else:
            notes = input("Enter description of what happened: ").strip()
            initial_state["worker_notes"] = notes

        # Initialize session state
        await session_service.create_session(
            app_name=APP, user_id=user_id, session_id=session_id, state=initial_state
        )

        # Run Branch A intake (Vision + Audio Extraction)
        events_a = await run_pipeline_with_session(session_service, session_id, user_id, branch_a_intake)
        all_events.extend(events_a)

    # =========================================================
    # BRANCH B: Ambient Dialogue Transcript
    # =========================================================
    elif branch == "B":
        print("\n--- Running Branch B (Ambient Dialogue) ---")
        if not os.path.exists(dialogue_path):
            dialogue_path = input(f"File not found at '{dialogue_path}'. Enter valid path to JSON: ").strip()

        data = load_transcript(dialogue_path)

        # Standalone Triage Agent run
        triage_session_id = str(uuid.uuid4())
        await session_service.create_session(
            app_name=APP, user_id=user_id, session_id=triage_session_id,
            state={"conversation_text": format_transcript(data)}
        )
        await run_pipeline_with_session(session_service, triage_session_id, user_id, triage_agent)
        triage_session = await session_service.get_session(app_name=APP, user_id=user_id, session_id=triage_session_id)
        triage = triage_session.state.get("triage_result")
        print("\nTriage Result:", triage)

        if not triage or not triage.get("incident_detected"):
            print("No incident detected in the dialogue.")
            return

        if input("\nIncident detected in dialogue. Create a report? [y/N]: ").strip().lower() != "y":
            print("Cancelled.")
            return

        incident_text = build_incident_text(data, triage)

        # Initialize main pipeline session state for Branch B
        await session_service.create_session(
            app_name=APP, user_id=user_id, session_id=session_id,
            state={"incident_text": incident_text, "vision_result": NO_PHOTO_VISION}
        )

        # Run text extraction
        events_b = await run_pipeline_with_session(session_service, session_id, user_id, text_extraction_agent)
        all_events.extend(events_b)

    else:
        print("Invalid option. Please enter 'A' or 'B'.")
        return

    # =========================================================
    # SHARED DOWNSTREAM: Classification -> Review -> Compose
    # =========================================================
    print("\n--- Running Classification & Final Composition ---")
    events_downstream = await run_pipeline_with_session(session_service, session_id, user_id, downstream_pipeline)
    all_events.extend(events_downstream)

    # Output results
    print("\n=== Agent Responses ===")
    for author, text in all_events:
        print(f"[{author}] {text}")

    session = await session_service.get_session(app_name=APP, user_id=user_id, session_id=session_id)
    print("\n--- Final state ---")
    for key, value in session.state.items():
        if key not in ("incident_text", "conversation_text"):
            print(f"{key}: {value}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dialogue", default="sample_data/dialogue/team_dialogue_transcript.json")
    p.add_argument("--events", default=None, help="YAMNet events JSON from Colab (optional)")
    args = p.parse_args()
    asyncio.run(main(args.dialogue, args.events))