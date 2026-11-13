"""
Phase 1 Configuration — paths, section rules, KPI patterns.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
PHASE1_OUTPUT = PROJECT_ROOT / "phase1_output"

NORMALIZED_DIR = PHASE1_OUTPUT / "normalized"
METADATA_DIR = PHASE1_OUTPUT / "metadata"
TABLES_DIR = PHASE1_OUTPUT / "tables"
MARKDOWN_DIR = PHASE1_OUTPUT / "raw_markdown"

for _d in (PHASE1_OUTPUT, NORMALIZED_DIR, METADATA_DIR, TABLES_DIR, MARKDOWN_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── Section detection ─────────────────────────────────────────────────
# Regex rules applied to page text. First match wins.
# Order matters: more specific patterns first.
SECTION_RULES = [
    (r"letter\s+to\s+(shareholder|investor|stockholder)", "ceo_letter"),
    (r"dear\s+(shareholder|investor|stockholder)",        "ceo_letter"),
    (r"item\s*1a[\.\s]|risk\s+factor",                    "risk_factors"),
    (r"item\s*7[\.\s]|management.{0,20}discussion",       "mda"),
    (r"item\s*8[\.\s]|financial\s+statements",            "financial_statements"),
    (r"consolidated\s+statement",                         "financial_statements"),
    (r"note\s*\d+[\.\s]|footnote",                        "footnotes"),
    (r"segment\s+(breakdown|report|information)",         "segment_breakdown"),
    (r"esg|environmental|sustainability|carbon\s+emission", "esg"),
    (r"item\s*3[\.\s]|legal\s+proceedings|litigation",    "legal"),
    (r"item\s*1[\.\s]|business\s+overview|our\s+business", "business_overview"),
]


# ── KPI patterns ──────────────────────────────────────────────────────
# Matched against table rows and page text. First match per metric wins.
KPI_PATTERNS = {
    "revenue":              r"(total\s+)?net\s+revenue|total\s+revenue",
    "gross_profit":         r"gross\s+profit",
    "gross_margin_pct":     r"gross\s+margin",
    "operating_income":     r"operating\s+income|income\s+from\s+operations",
    "net_income":           r"net\s+income",
    "r_and_d":              r"research\s+and\s+development",
    "total_debt":           r"total\s+(long.term\s+)?debt",
    "cash_and_equivalents": r"cash\s+and\s+cash\s+equivalents?\s*$",
    "total_assets":         r"total\s+assets",
    "total_liabilities":    r"total\s+liabilities",
    "shareholders_equity":  r"total\s+(stockholders?|shareholders?)\s+equity",
    "capex":                r"capital\s+expenditure|purchase.{0,20}property",
    "free_cash_flow":       r"free\s+cash\s+flow",
    "employee_count":       r"(number\s+of\s+)?employees",
}


# ── Chunking ──────────────────────────────────────────────────────────
# Matches phase2/config.py so chunks align cleanly across phases.
CHUNK_SIZE_WORDS = 512
CHUNK_OVERLAP_WORDS = 64