from pydantic import BaseModel, Field
from typing import List, Literal


class ExtractionResult(BaseModel):
    injury_occurred: bool
    treatment_described: str
    location: str
    witnesses: List[str] = Field(default_factory=list)
    narrative_summary: str


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


class ComposedReport(BaseModel):
    report_text: str



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