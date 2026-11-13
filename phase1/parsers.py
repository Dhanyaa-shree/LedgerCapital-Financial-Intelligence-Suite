"""
PDF parsing utilities: text, tables, section detection.
"""

import re
from typing import Dict, List, Optional
import pdfplumber

from .config import (
    SECTION_RULES,
    KPI_PATTERNS,
    CHUNK_SIZE_WORDS,
    CHUNK_OVERLAP_WORDS,
)


def clean_number(s) -> Optional[float]:
    """Convert a table cell string to float. Returns None if not numeric."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("$", "").replace("%", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def detect_section(text: str) -> str:
    """Classify a page into a canonical section type."""
    if not text:
        return "general"
    snippet = text.lower()[:1200]
    for pattern, label in SECTION_RULES:
        if re.search(pattern, snippet):
            return label
    return "general"


def chunk_text(
    text: str,
    size: int = CHUNK_SIZE_WORDS,
    overlap: int = CHUNK_OVERLAP_WORDS,
) -> List[str]:
    """Split text into overlapping word-chunks. Skips tiny fragments."""
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    chunks: List[str] = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + size])
        if len(chunk.strip()) > 60:
            chunks.append(chunk)
    return chunks


def extract_kpis_from_tables(tables: List[list], year: Optional[int]) -> Dict:
    """Scan table rows for known KPIs. First match per metric wins."""
    kpis: Dict = {}
    for table in tables or []:
        for row in table or []:
            if not row:
                continue
            row_str = " ".join(str(c) for c in row if c is not None)
            row_lower = row_str.lower()
            for key, pattern in KPI_PATTERNS.items():
                if key in kpis:
                    continue
                if re.search(pattern, row_lower):
                    nums = [
                        clean_number(c)
                        for c in row
                        if clean_number(c) is not None
                    ]
                    if nums:
                        kpis[key] = nums[0]
                        if len(nums) > 1:
                            kpis[f"{key}_prior"] = nums[1]
    return kpis


def parse_pdf(
    pdf_path: str,
    company: str,
    year: int,
    doc_type: str = "10-K",
) -> Dict:
    """
    Main extraction function. Returns a dict with sections, chunks,
    tables, and detected KPIs.
    """
    result: Dict = {
        "company": company,
        "year": year,
        "doc_type": doc_type,
        "sections": [],
        "chunks": [],
        "tables": [],
        "kpis": {},
        "page_count": 0,
    }

    with pdfplumber.open(pdf_path) as pdf:
        result["page_count"] = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages, 1):
            # Text
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""

            section_type = detect_section(text)

            # Chunks
            for idx, chunk in enumerate(chunk_text(text)):
                result["chunks"].append({
                    "chunk_id":     f"{company}_{year}_p{page_num}_c{idx}",
                    "page":         page_num,
                    "section_type": section_type,
                    "text":         chunk,
                })

            # Tables
            try:
                page_tables = page.extract_tables() or []
            except Exception:
                page_tables = []

            for t_idx, table in enumerate(page_tables):
                result["tables"].append({
                    "page":         page_num,
                    "table_idx":    t_idx,
                    "section_type": section_type,
                    "rows": [
                        [str(c) if c is not None else "" for c in row]
                        for row in (table or [])
                    ],
                })
                page_kpis = extract_kpis_from_tables([table], year)
                result["kpis"].update(page_kpis)

            # Sections (carry page text so phase2 can re-chunk)
            result["sections"].append({
                "page":         page_num,
                "section_id":   f"{company}_{year}_p{page_num}_{section_type}",
                "section_type": section_type,
                "text":         text,
                "char_count":   len(text),
            })

    return result