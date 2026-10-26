"""RoHS candidate extraction (Document Ingestion sheet, step 3).

Rule-based and deliberately conservative: it only reads fields that appear after a recognisable label
("Supplier:", "Part Number:", ...), records the page and a confidence for each, and NEVER outputs a compliance
verdict. Ambiguous numeric dates (03/04/2026) are left empty rather than guessed. Every record starts as
'Pending verification'; a compliance reviewer confirms or corrects it.
"""
import re
from datetime import date, datetime

SEP = r"\s*[:=\-–]\s*"
SUPPLIER = re.compile(rf"(?im)^\W*(?:supplier|manufacturer|vendor|company(?:\s+name)?){SEP}(.+?)\s*$")
PART = re.compile(rf"(?im)\b(?:part\s*(?:number|no\.?|#)|p/n|item\s*(?:number|no\.?)|model(?:\s*number)?){SEP}([A-Z0-9][A-Z0-9\-_./]{{2,40}})")
DATE = re.compile(rf"(?im)\b(?:declaration\s+date|date\s+of\s+declaration|date\s+of\s+issue|issued|date){SEP}([^\n]{{4,30}})")
SCOPE = re.compile(rf"(?im)^\W*(?:product\s+scope|scope|applicable\s+products?|products?\s+covered){SEP}(.+?)\s*$")
VALID = re.compile(rf"(?im)\b(?:valid\s+(?:until|through|to)|expiry\s+date|expires?){SEP}([^\n]{{4,30}})")
EXEMPT_TOKEN = re.compile(r"\b\d{1,2}\([a-z]\)(?:-[IVX]+)?")

MONTHS = "january february march april may june july august september october november december".split()
_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y")


def parse_date(text: str):
    """ISO and written-month dates only. Numeric d/m/y or m/d/y is ambiguous, so it returns None (never guesses)."""
    t = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", text.strip().rstrip(".,"), flags=re.I)
    t = re.sub(r"\s+", " ", t)
    for f in _FORMATS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            continue
    return None


def _first(rx, pages):
    for page, text in pages:
        m = rx.search(text)
        if m:
            return m.group(1).strip(), page, m.group(0)[:200]
    return None, None, None


def extract_candidates(chunks):
    """chunks: objects with .content and .page_start. Returns (records, warnings)."""
    pages = [(c.page_start, c.content) for c in chunks]
    full = "\n".join(t for _, t in pages)
    warnings = []

    supplier, sp, sx = _first(SUPPLIER, pages)
    scope, _, _ = _first(SCOPE, pages)
    raw_date, dp, dx = _first(DATE, pages)
    raw_valid, _, _ = _first(VALID, pages)
    decl = parse_date(raw_date) if raw_date else None
    valid = parse_date(raw_valid) if raw_valid else None
    if raw_date and decl is None:
        warnings.append(f"Declaration date '{raw_date}' is ambiguous or in an unsupported format; left empty.")

    exemptions = []
    for m in re.finditer(r"(?i)exempt", full):
        window = full[m.start(): m.start() + 300]
        for tok in EXEMPT_TOKEN.findall(window):
            if tok not in exemptions:
                exemptions.append(tok)
    exempt_conf = 0.8 if exemptions else None
    if not exemptions and re.search(r"(?i)exempt", full):
        warnings.append("Exemption field extracted with low confidence.")

    parts = []
    for page, text in pages:
        for m in PART.finditer(text):
            pn = m.group(1).strip(".")
            if pn.lower() not in [p[0].lower() for p in parts]:
                parts.append((pn, page, m.group(0)[:200]))

    conf = {"supplier": 0.9 if supplier else 0.0, "declaration_date": (0.9 if decl else 0.0),
            "exemptions": exempt_conf if exempt_conf else (0.3 if re.search(r"(?i)exempt", full) else 0.0)}
    records = []
    for pn, page, excerpt in (parts or [(None, sp or dp, sx or dx)]):
        fc = dict(conf, part_number=0.9 if pn else 0.0)
        required = [fc["supplier"], fc["part_number"], fc["declaration_date"]]
        records.append({
            "supplier": supplier, "part_number": pn, "product_scope": scope, "declaration_date": decl, "valid_until": valid,
            "exemptions": exemptions, "source_page": page, "source_excerpt": excerpt,
            "extraction_confidence": round(sum(required) / 3, 2), "field_confidence": fc})
    if not supplier:
        warnings.append("No supplier found.")
    if not parts:
        warnings.append("No part number found; a placeholder record was created for the reviewer to complete.")
    return records, warnings


def needs_review(records, warnings) -> bool:
    """True when a human must look before this is trusted (anything missing or low confidence)."""
    return bool(warnings) or any(r["extraction_confidence"] < 0.9 for r in records)
