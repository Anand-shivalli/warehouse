from schemas.models import Signals


def category_lookup(signals: Signals) -> str:
    """Deterministic: same signals always produce the same category."""
    if not signals.injury_occurred and signals.potential_severity == "high":
        return "near_miss"
    if not signals.injury_occurred:
        return "no_classification_needed"
    if signals.treatment_level in ("none", "first_aid"):
        return "first_aid_case"
    if signals.treatment_level == "medical_treatment":
        return "recordable_injury"
    if signals.treatment_level == "hospitalization":
        return "serious_injury"
    return "needs_review"