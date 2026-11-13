"""
src/process_pdf.py
==================

Standalone PDF processing entry point.

Reads a PDF, extracts text + tables + charts, classifies sections,
pulls KPIs, and writes everything to DuckDB + ChromaDB.

Usage:
    python src/process_pdf.py --pdf uploads/AMD_2021_10K.pdf --company AMD --year 2021
    python src/process_pdf.py --batch uploads/
"""

import os
import sys
import json
import hashlib
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import duckdb
import chromadb
import pdfplumber
from sentence_transformers import SentenceTransformer

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.extract_pdf import extract_pdf_content
from src.section_classifier import classify_sections
from src.kpi_extractor import extract_kpis
from src.chart_extractor import extract_charts
from src.storage import save_to_duckdb, save_to_chromadb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────
DUCKDB_PATH = PROJECT_ROOT / "data" / "duckdb" / "financial_intelligence.db"
CHROMADB_PATH = PROJECT_ROOT / "data" / "chromadb"

DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
CHROMADB_PATH.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"

# Cache the model across runs
_EMBED_MODEL = None


def _load_embed_model() -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _EMBED_MODEL = SentenceTransformer(EMBEDDING_MODEL)
    return _EMBED_MODEL


def _doc_id(pdf_path: Path, company: str, year: int) -> str:
    """Stable document ID for a PDF."""
    return f"{company}_{year}_10K"


def _auto_metadata(name: str) -> tuple:
    """Best-effort company + year from a filename."""
    import re
    stem = Path(name).stem
    year_m = re.search(r"(20\d{2})", stem)
    year = int(year_m.group(1)) if year_m else None
    company = re.sub(r"20\d{2}", "", stem).strip("_- ").split("_")[0].upper() or "UNKNOWN"
    return company, year


def process_one(pdf_path: Path, company: str, year: int, doc_type: str = "10-K") -> Dict:
    """
    Full pipeline for one PDF:
      1. Extract text + tables + charts
      2. Classify sections
      3. Extract KPIs
      4. Save to DuckDB + ChromaDB
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"Processing: {pdf_path.name}  ({company} {year})")
    logger.info(f"{'='*70}")

    doc_id = _doc_id(pdf_path, company, year)

    # ── 1. Extract ─────────────────────────────────────────────────────
    logger.info("Step 1/4: Extracting PDF content...")
    try:
        extracted = extract_pdf_content(str(pdf_path))
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return {"doc_id": doc_id, "status": "error", "error": str(e)}

    logger.info(
        f"  pages={extracted.get('page_count', 0)} "
        f"text_blocks={len(extracted.get('pages', []))} "
        f"tables={len(extracted.get('tables', []))}"
    )

    # ── 2. Classify sections ───────────────────────────────────────────
    logger.info("Step 2/4: Classifying sections...")
    try:
        classified = classify_sections(extracted.get("pages", []))
    except Exception as e:
        logger.warning(f"Section classification failed: {e}")
        classified = extracted.get("pages", [])

    # ── 3. Extract KPIs ────────────────────────────────────────────────
    logger.info("Step 3/4: Extracting KPIs...")
    try:
        kpis = extract_kpis(extracted.get("tables", []), year)
    except Exception as e:
        logger.warning(f"KPI extraction failed: {e}")
        kpis = {}

    # ── 4. Extract charts ──────────────────────────────────────────────
    logger.info("Step 4a/4: Extracting charts...")
    try:
        charts = extract_charts(str(pdf_path))
    except Exception as e:
        logger.warning(f"Chart extraction failed: {e}")
        charts = []

    # ── 5. Save to DuckDB ──────────────────────────────────────────────
    logger.info("Step 4b/4: Saving to DuckDB...")
    try:
        save_to_duckdb(
            db_path=str(DUCKDB_PATH),
            doc_id=doc_id,
            company=company,
            year=year,
            doc_type=doc_type,
            pages=classified,
            tables=extracted.get("tables", []),
            kpis=kpis,
            charts=charts,
        )
        logger.info(f"  DuckDB: OK")
    except Exception as e:
        logger.error(f"  DuckDB save failed: {e}")

    # ── 6. Save to ChromaDB (chunks with embeddings) ───────────────────
    logger.info("Step 4c/4: Saving to ChromaDB...")
    try:
        model = _load_embed_model()
        chunks = []
        for page in classified:
            page_text = page.get("text", "")
            if not page_text.strip():
                continue
            section_type = page.get("section_type", "general")
            page_num = page.get("page", 0)

            # word-chunk the page
            words = page_text.split()
            size, overlap = 512, 64
            step = max(1, size - overlap)
            for i, start in enumerate(range(0, len(words), step)):
                chunk_text = " ".join(words[start:start + size])
                if len(chunk_text.strip()) < 60:
                    continue
                chunks.append({
                    "chunk_id":     f"{doc_id}_p{page_num}_c{i}",
                    "text":         chunk_text,
                    "section_type": section_type,
                    "page":         page_num,
                })

        save_to_chromadb(
            chroma_path=str(CHROMADB_PATH),
            collection_name="all_sections",
            doc_id=doc_id,
            company=company,
            year=year,
            doc_type=doc_type,
            chunks=chunks,
            embed_model=model,
        )
        logger.info(f"  ChromaDB: {len(chunks)} chunks embedded")
    except Exception as e:
        logger.error(f"  ChromaDB save failed: {e}")

    return {
        "doc_id":     doc_id,
        "company":    company,
        "year":       year,
        "status":     "success",
        "page_count": extracted.get("page_count", 0),
        "tables":     len(extracted.get("tables", [])),
        "charts":     len(charts),
        "kpis":       len(kpis),
    }


def process_batch(folder: Path) -> List[Dict]:
    """Process every PDF in a folder."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        logger.warning(f"No PDFs found in {folder}")
        return []

    logger.info(f"Found {len(pdfs)} PDFs in {folder}")
    results = []
    for pdf in pdfs:
        company, year = _auto_metadata(pdf.name)
        results.append(process_one(pdf, company, year or 2021))
    return results


def main():
    ap = argparse.ArgumentParser(description="Process PDFs into DuckDB + ChromaDB")
    ap.add_argument("--pdf", help="Single PDF path")
    ap.add_argument("--batch", help="Directory of PDFs")
    ap.add_argument("--company", help="Company name (overrides filename detection)")
    ap.add_argument("--year", type=int, help="Fiscal year (overrides filename detection)")
    args = ap.parse_args()

    if args.pdf:
        pdf = Path(args.pdf)
        if not pdf.exists():
            logger.error(f"PDF not found: {pdf}")
            sys.exit(1)
        auto_co, auto_yr = _auto_metadata(pdf.name)
        company = (args.company or auto_co).upper()
        year = args.year or auto_yr or 2021
        result = process_one(pdf, company, year)
        print(json.dumps(result, indent=2))

    elif args.batch:
        folder = Path(args.batch)
        if not folder.exists():
            logger.error(f"Folder not found: {folder}")
            sys.exit(1)
        results = process_batch(folder)
        print(json.dumps(results, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    main()