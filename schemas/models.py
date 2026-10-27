from pydantic import BaseModel, Field
from typing import List, Literal


class ExtractionResult(BaseModel):
    injury_occurred: bool
    treatment_described: str
    location: str
    witnesses: List[str] = Field(default_factory=list)
    narrative_summary: str
    transcript: str = ""        # verbatim transcription of the audio (Path A), machine-generated


class VisionResult(BaseModel):
    hazard_type: str
    visible_injury_severity: str
    visible_damage: str
    description: str


class ConflictResult(BaseModel):
    conflict: bool
    reason: str = ""


class Signals(BaseModel):
    injury_occurred: bool
    treatment_level: Literal["none", "first_aid", "medical_treatment", "hospitalization"]
    potential_severity: Literal["low", "high"]
    confidence: Literal["low", "medium", "high"]


class ReviewResult(BaseModel):
    review_pass: bool
    notes: str = ""


class Recommendation(BaseModel):
    action: str
    source_ids: List[str] = Field(default_factory=list)   # ids like "S1" from the retrieved passages


class ComposedReport(BaseModel):
    report_text: str
    observed: List[str] = Field(default_factory=list)
    interpretation: List[str] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)



class ProcedurePoint(BaseModel):
    requirement: str
    source_id: str                                     # retrieved passage id, e.g. "S1"
    status: Literal["followed", "possible_deviation", "cannot_tell"]
    evidence_quote: str = ""                           # exact words from the incident facts; required unless cannot_tell
    explanation: str = ""


class DeviationResult(BaseModel):
    points: List[ProcedurePoint] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    category: str
    flags: List[str]


class TriageResult(BaseModel):
    incident_detected: bool
    start_sec: float = 0.0
    end_sec: float = 0.0
    reporter_speaker: str = ""
    involved_speakers: List[str] = Field(default_factory=list)
    summary: str = ""
    confidence: Literal["low", "medium", "high"] = "low"