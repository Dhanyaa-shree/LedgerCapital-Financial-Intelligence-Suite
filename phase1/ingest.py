"""
Phase 1 entry point: PDF → structured JSON files.

Usage:
    python phase1/ingest.py --pdf uploads/AMD_2021_10K.pdf --company AMD --year 2021
    python phase1/ingest.py --batch uploads/
"""

import json
import argparse
import sys
import re
from pathlib import Path
from datetime import datetime

# Allow running as `python phase1/ingest.py`
sys.path.append(str(Path(__file__).parent.parent))

from phase1.parsers import parse_pdf
from phase1.config import (
    NORMALIZED_DIR,
    METADATA_DIR,
    TABLES_DIR,
    MARKDOWN_DIR,
)


def _doc_id(company: str, year: int) -> str:
    """Stable document identifier used across all phases."""
    return f"{company}_{year}_10K"


def _auto_metadata_from_filename(name: str):
    """Best-effort company + year extraction from a filename."""
    year_m = re.search(r"(20\d{2})", name)
    year = int(year_m.group(1)) if year_m else None
    stem = re.sub(r"20\d{2}", "", Path(name).stem).strip("_- ")
    company = stem.split("_")[0].upper() if stem else "UNKNOWN"
    return company, year


def _build_normalized(parsed, doc_id, company, year, doc_type, pdf_path):
    """Shape the JSON to match what phase2/process.py expects."""
    section_map = {}
    for s in parsed["sections"]:
        st = s["section_type"]
        section_map[st] = section_map.get(st, 0) + 1

    return {
        "metadata": {
            "doc_id":         doc_id,
            "company":        company,
            "year":           year,
            "fiscal_year":    year,
            "doc_type":       doc_type,
            "fiscal_period":  f"FY{year}",
            "source_pdf":     str(pdf_path),
            "page_count":     parsed["page_count"],
            "total_pages":    parsed["page_count"],
            "section_map":    section_map,
            "ingestion_date": datetime.now().isoformat(),
        },
        "sections": parsed["sections"],
        "chunks":   parsed["chunks"],
        "tables":   parsed["tables"],
        "kpis":     parsed["kpis"],
    }


def process_one(pdf_path: Path, company: str, year: int, doc_type: str = "10-K"):
    """Extract one PDF and write its four output files."""
    print(f"\n[Phase1] {pdf_path.name} → {company} {year}")

    parsed = parse_pdf(str(pdf_path), company, year, doc_type)
    doc_id = _doc_id(company, year)

    # 1. Normalized JSON (the file phase2 reads)
    normalized = _build_normalized(parsed, doc_id, company, year, doc_type, pdf_path)
    (NORMALIZED_DIR / f"{doc_id}.json").write_text(
        json.dumps(normalized, indent=2), encoding="utf-8"
    )

    # 2. Metadata JSON (lightweight, for humans)
    metadata = {
        "doc_id":     doc_id,
        "company":    company,
        "year":       year,
        "fiscal_year": year,
        "doc_type":   doc_type,
        "kpis":       parsed["kpis"],
        "page_count": parsed["page_count"],
    }
    (METADATA_DIR / f"{doc_id}_meta.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # 3. Tables JSON
    (TABLES_DIR / f"{doc_id}_tables.json").write_text(
        json.dumps({"doc_id": doc_id, "tables": parsed["tables"]}, indent=2),
        encoding="utf-8",
    )

    # 4. Raw markdown (concatenated chunk text)
    md = "\n\n".join(c["text"] for c in parsed["chunks"])
    (MARKDOWN_DIR / f"{doc_id}.md").write_text(md, encoding="utf-8")

    print(
        f"   ✅ chunks={len(parsed['chunks'])} "
        f"tables={len(parsed['tables'])} "
        f"kpis={len(parsed['kpis'])}"
    )
    return doc_id


def main():
    ap = argparse.ArgumentParser(description="Phase 1 — PDF extraction")
    ap.add_argument("--pdf", help="Single PDF path")
    ap.add_argument("--batch", help="Directory of PDFs")
    ap.add_argument("--company", help="Company ticker/name")
    ap.add_argument("--year", type=int, help="Fiscal year")
    args = ap.parse_args()

    if args.pdf:
        pdf = Path(args.pdf)
        if not pdf.exists():
            print(f"❌ Not found: {pdf}")
            return
        auto_company, auto_year = _auto_metadata_from_filename(pdf.name)
        company = (args.company or auto_company).upper()
        year = args.year or auto_year or 2021
        process_one(pdf, company, year)

    elif args.batch:
        root = Path(args.batch)
        pdfs = sorted(root.glob("**/*.pdf"))
        if not pdfs:
            print(f"❌ No PDFs in {root}")
            return
        for p in pdfs:
            c, y = _auto_metadata_from_filename(p.name)
            process_one(p, c, y or 2021)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()