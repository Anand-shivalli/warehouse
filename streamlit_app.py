import streamlit as st
import asyncio
import uuid


@st.cache_resource
def build_pipeline():
    from google.adk.agents import ParallelAgent, SequentialAgent
    from google.adk.sessions import InMemorySessionService
    from google.adk.runners import Runner

    from agents.extraction_agent import extraction_agent
    from agents.vision_agent import vision_agent
    from agents.classifier_pipeline import classification_pipeline
    from agents.review_compose_pipeline import reviewer_pass1, composer_agent, reviewer_pass2
    from agents.review_gate import ReviewGate

    capture_analysis = ParallelAgent(
        name="CaptureAnalysis", sub_agents=[extraction_agent, vision_agent]
    )

    gate2 = ReviewGate(
        name="Gate_Pass2", review_key="review2_result", next_agent=None, stage_name="Final report"
    )
    compose_and_verify = SequentialAgent(
        name="ComposeAndVerify", sub_agents=[composer_agent, reviewer_pass2, gate2]
    )

    gate1 = ReviewGate(
        name="Gate_Pass1", review_key="review1_result",
        next_agent=compose_and_verify, stage_name="Pre-composition review",
    )
    review_and_compose = SequentialAgent(
        name="ReviewAndCompose", sub_agents=[reviewer_pass1, gate1]
    )

    pipeline = SequentialAgent(
        name="IncidentPipeline",
        sub_agents=[capture_analysis, classification_pipeline, review_and_compose],
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=pipeline, app_name="incident_pipeline", session_service=session_service)

    return runner, session_service


runner, session_service = build_pipeline()


async def run_pipeline(audio_bytes: bytes, audio_mime: str, image_bytes: bytes, image_mime: str):
    from google.genai import types

    session_id = str(uuid.uuid4())
    user_id = "streamlit_user"

    await session_service.create_session(
        app_name="incident_pipeline", user_id=user_id, session_id=session_id
    )

    content = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime),
            types.Part.from_bytes(data=image_bytes, mime_type=image_mime),
        ],
    )

    events_log = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                events_log.append((event.author, text))

    final_session = await session_service.get_session(
        app_name="incident_pipeline", user_id=user_id, session_id=session_id
    )
    return events_log, final_session.state


# --- Streamlit UI ---
st.set_page_config(page_title="Incident Reporter", layout="centered")
st.title("AI Incident Reporter")
st.caption("Upload an audio description and a photo of the incident")

audio_file = st.file_uploader("Audio recording", type=["wav", "mp3", "m4a"])
image_file = st.file_uploader("Incident photo", type=["jpg", "jpeg", "png"])

if audio_file and image_file:
    st.audio(audio_file)
    st.image(image_file, caption="Uploaded photo", use_container_width=True)

    if st.button("Generate Incident Report", type="primary"):
        with st.spinner("Running extraction, vision, classification, and review..."):
            audio_bytes = audio_file.read()
            image_bytes = image_file.read()

            audio_mime = "audio/wav" if audio_file.name.endswith(".wav") else "audio/mp3"
            image_mime = "image/jpeg" if image_file.name.endswith((".jpg", ".jpeg")) else "image/png"

            events_log, final_state = asyncio.run(
                run_pipeline(audio_bytes, audio_mime, image_bytes, image_mime)
            )

        st.success("Pipeline complete")

        # --- Show the final report front and center ---
        report = final_state.get("report_text", {})
        if isinstance(report, dict):
            report = report.get("report_text", "")
        st.subheader("Incident Report")
        st.text_area("Generated report", report, height=300)

        # --- Key results at a glance ---
        col1, col2 = st.columns(2)
        with col1:
            category = final_state.get("category_result", {})
            st.metric(
                "Category",
                category.get("category", "N/A") if isinstance(category, dict) else str(category),
            )
        with col2:
            review2 = final_state.get("review2_result", {})
            passed = review2.get("review_pass") if isinstance(review2, dict) else None
            st.metric("Final Review", "✅ Passed" if passed else "⚠️ Needs Human Review")

        # --- Expandable raw detail for debugging/audit ---
        with st.expander("View full pipeline trace"):
            for author, text in events_log:
                st.markdown(f"**{author}**")
                st.code(text, language="json")

        with st.expander("View raw session state"):
            st.json(final_state)
else:
    st.info("Upload both an audio file and a photo to continue.")