def get_flags(category: str) -> list[str]:
    """Deterministic: category always maps to the same compliance flags."""
    flag_map = {
        "near_miss": [],
        "no_classification_needed": [],
        "first_aid_case": [],
        "recordable_injury": ["OSHA_recordable"],
        "serious_injury": ["OSHA_recordable", "report_within_24_hours"],
        "needs_review": ["manual_review_required"],
    }
    return flag_map.get(category, ["unknown_category"])