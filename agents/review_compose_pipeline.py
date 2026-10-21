from google.adk.agents import LlmAgent
from schemas.models import ReviewResult, ComposedReport
from config import MODEL_PRO

# MODEL_PRO for all three — this is the compliance safety net and the
# report-writing step, both worth the stronger model

reviewer_pass1 = LlmAgent(
    name="ReviewerPass1",
    model=MODEL_PRO,
    instruction="""Review this incident data for consistency and completeness before a report is written:

Extraction: {extraction_result}
Vision: {vision_result}
Signals: {signals}
Category and flags: {category_result}

Check:
- Do extraction and vision agree with each other, and with the assigned category?
- Are required fields present (location, injury status, treatment level)?
- Does the category logically follow from the signals?

Output review_pass (true/false) and notes explaining any issue found.""",
    output_schema=ReviewResult,
    output_key="review1_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

composer_agent = LlmAgent(
    name="Composer",
    model=MODEL_PRO,
    instruction="""Write a formal incident report using only the following verified data.
Do not add any detail not present in this data.

Extraction: {extraction_result}
Vision: {vision_result}
Category and flags: {category_result}

Write a clear, professional incident report narrative.""",
    output_schema=ComposedReport,
    output_key="report_text",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

reviewer_pass2 = LlmAgent(
    name="ReviewerPass2",
    model=MODEL_PRO,
    instruction="""Check this generated report against the original verified data.
Every claim in the report must trace back to something in the data below —
flag anything added, overstated, or softened that isn't actually supported.

Generated report: {report_text}
Original extraction: {extraction_result}
Original vision: {vision_result}
Original signals: {signals}

Output review_pass (true/false) and notes on any ungrounded claim found.""",
    output_schema=ReviewResult,
    output_key="review2_result",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)