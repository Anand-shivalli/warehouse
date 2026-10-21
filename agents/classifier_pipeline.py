from google.adk.agents import LlmAgent, SequentialAgent
from schemas.models import ConflictResult, Signals, ClassificationResult
from tools.classifier_tools import category_tool, flags_tool
from config import MODEL_FLASH

conflict_check_agent = LlmAgent(
    name="ConflictCheck",
    model=MODEL_FLASH,
    instruction="""Compare these two accounts of the same incident:
Narrative: {extraction_result}
Visual evidence: {vision_result}

Do they meaningfully contradict each other? Output conflict (true/false) and reason.""",
    output_schema=ConflictResult,
    output_key="conflict_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

signal_agent = LlmAgent(
    name="SignalNormalizer",
    model=MODEL_FLASH,
    instruction="""Based on this narrative and visual evidence, output fixed signals:
Narrative: {extraction_result}
Visual evidence: {vision_result}

injury_occurred, treatment_level (none|first_aid|medical_treatment|hospitalization),
potential_severity (low|high), confidence (low|medium|high).""",
    output_schema=Signals,
    output_key="signals",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

# this agent calls plain-code tools — it does not reason out the category itself
classifier_agent = LlmAgent(
    name="ComplianceClassifier",
    model=MODEL_FLASH,
    instruction="""Using {signals}, call category_lookup to get the category,
then call get_flags with that category. Return category and flags as structured output.""",
    tools=[category_tool, flags_tool],
    output_schema= ClassificationResult,   # ← add this
    output_key="category_result",
    disallow_transfer_to_parent=True,      # ← required alongside output_schema
    disallow_transfer_to_peers=True,
)

classification_pipeline = SequentialAgent(
    name="ClassificationPipeline",
    sub_agents=[conflict_check_agent, signal_agent, classifier_agent],
)