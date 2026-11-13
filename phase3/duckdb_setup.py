"""
DuckDB Setup: Create schema and load chunks + signals + tables + KPIs.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

import duckdb

import sys
sys.path.append(str(Path(__file__).parent.parent))
from phase3.config import DUCKDB_PATH, PHASE2_OUTPUT

logger = logging.getLogger(__name__)


def init_schema(conn):
    """Create all required tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id VARCHAR PRIMARY KEY,
            company VARCHAR,
            year INTEGER,
            doc_type VARCHAR,
            page_count INTEGER,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sections_metadata (
            section_id VARCHAR PRIMARY KEY,
            doc_id VARCHAR,
            company VARCHAR,
            year INTEGER,
            section_type VARCHAR,
            char_count INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            signal_id VARCHAR PRIMARY KEY,
            doc_id VARCHAR,
            company VARCHAR,
            year INTEGER,
            section_id VARCHAR,
            signal_type VARCHAR,
            signal_text VARCHAR,
            context VARCHAR
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tables_metadata (
            table_id VARCHAR PRIMARY KEY,
            doc_id VARCHAR,
            company VARCHAR,
            year INTEGER,
            section_id VARCHAR,
            table_type VARCHAR,
            caption VARCHAR,
            row_count INTEGER,
            column_count INTEGER
        )
    """)

    # NEW: financial_metrics — one row per (doc_id, metric_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financial_metrics (
            metric_id VARCHAR PRIMARY KEY,
            doc_id VARCHAR,
            company VARCHAR,
            year INTEGER,
            metric_name VARCHAR,
            value DOUBLE,
            unit VARCHAR,
            source VARCHAR
        )
    """)

    # NEW: financial_metrics historically written by knowledge_base pipeline
    # Keep the same table name so api_server._query_duckdb_metrics works
    # without further changes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_kpis (
            kpi_id VARCHAR PRIMARY KEY,
            doc_id VARCHAR,
            company VARCHAR,
            fiscal_year INTEGER,
            metric_name VARCHAR,
            value DOUBLE,
            unit VARCHAR
        )
    """)


def _load_chunks():
    """Load all chunks from phase2 output. Returns list of dicts."""
    chunks_dir = PHASE2_OUTPUT / "chunks"
    all_chunks: List[Dict] = []
    if not chunks_dir.exists():
        return all_chunks
    for f in chunks_dir.rglob("*_chunks.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
            meta = data.get("metadata", {})
            for c in data.get("chunks", []):
                c["company"] = meta.get("company", "")
                c["year"] = meta.get("year", 0)
                c["doc_type"] = meta.get("doc_type", "")
                c["doc_id"] = data.get("doc_id", "")
                all_chunks.append(c)
        except Exception as e:
            logger.warning(f"Failed to load {f}: {e}")
    return all_chunks


def _load_signals():
    """Load all signal files from phase2 output."""
    signals_dir = PHASE2_OUTPUT / "signals"
    all_signals: List[Dict] = []
    if not signals_dir.exists():
        return all_signals
    for f in signals_dir.rglob("*_signals.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
            meta = data.get("metadata", {})
            doc_id = data.get("doc_id", "")
            company = meta.get("company", "")
            year = meta.get("year", 0)

            for i, text in enumerate(data.get("top_risk_markers", [])):
                all_signals.append({
                    "signal_id": f"{doc_id}_risk_{i}",
                    "doc_id": doc_id, "company": company, "year": year,
                    "section_id": "",
                    "signal_type": "risk_marker",
                    "signal_text": str(text)[:500],
                    "context": str(text)[:500],
                })
            for i, text in enumerate(data.get("top_commitments", [])):
                all_signals.append({
                    "signal_id": f"{doc_id}_commit_{i}",
                    "doc_id": doc_id, "company": company, "year": year,
                    "section_id": "",
                    "signal_type": "commitment",
                    "signal_text": str(text)[:500],
                    "context": str(text)[:500],
                })
        except Exception as e:
            logger.warning(f"Failed to load {f}: {e}")
    return all_signals


def _load_kpis_from_metadata():
    """
    Load KPIs from phase2_output/classified_sections/*/*/*_sections.json
    AND phase1_output/metadata/*_meta.json files.

    Returns list of dicts {company, year, doc_id, metric_name, value, unit}.
    """
    kpis: List[Dict] = []

    # Source A: Phase 1 metadata files (per-document KPIs, may be empty)
    from phase3.config import PROJECT_ROOT
    phase1_meta = PROJECT_ROOT / "phase1_output" / "metadata"
    if phase1_meta.exists():
        for f in phase1_meta.rglob("*_meta.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                doc_id = data.get("doc_id", f.stem)
                company = data.get("company", "")
                year = data.get("fiscal_year") or data.get("year", 0)
                doc_kpis = data.get("kpis", {}) or {}

                # Two shapes:
                #  1) {metric: number}
                #  2) {metric: {"value": number, "unit": "..."}}
                for metric_name, raw in doc_kpis.items():
                    if metric_name in ("extraction_metadata", "company", "fiscal_year"):
                        continue
                    if isinstance(raw, dict):
                        value = raw.get("value")
                        unit = raw.get("unit", "")
                    else:
                        value = raw
                        unit = ""
                    if value is None:
                        continue
                    try:
                        fv = float(value)
                    except (TypeError, ValueError):
                        continue
                    kpis.append({
                        "company": company,
                        "year": int(year) if year else 0,
                        "doc_id": doc_id,
                        "metric_name": metric_name,
                        "value": fv,
                        "unit": unit,
                    })
            except Exception as e:
                logger.debug(f"KPI load skipped {f}: {e}")

    # Source B: Phase 2 classified section files
    sections_dir = PHASE2_OUTPUT / "classified_sections"
    if sections_dir.exists():
        for f in sections_dir.rglob("*_sections.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                doc_id = data.get("doc_id", f.stem)
                meta = data.get("metadata", {})
                company = meta.get("company", "")
                year = meta.get("year") or meta.get("fiscal_year", 0)
                doc_kpis = data.get("kpis", {}) or {}
                if not doc_kpis:
                    continue
                for metric_name, raw in doc_kpis.items():
                    if metric_name in ("extraction_metadata", "company", "fiscal_year"):
                        continue
                    if isinstance(raw, dict):
                        value = raw.get("value")
                        unit = raw.get("unit", "")
                    else:
                        value = raw
                        unit = ""
                    if value is None:
                        continue
                    try:
                        fv = float(value)
                    except (TypeError, ValueError):
                        continue
                    kpis.append({
                        "company": company,
                        "year": int(year) if year else 0,
                        "doc_id": doc_id,
                        "metric_name": metric_name,
                        "value": fv,
                        "unit": unit,
                    })
            except Exception as e:
                logger.debug(f"KPI load skipped {f}: {e}")

    # Deduplicate on (doc_id, metric_name) — first wins
    seen = set()
    deduped = []
    for k in kpis:
        key = (k["doc_id"], k["metric_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(k)
    return deduped


def setup_duckdb() -> Dict:
    """
    Create the DuckDB schema and load documents / sections / signals / KPIs.
    """
    logger.info(f"📦 Setting up DuckDB at {DUCKDB_PATH}")
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(DUCKDB_PATH))
    init_schema(conn)

    chunks = _load_chunks()
    signals = _load_signals()
    kpis = _load_kpis_from_metadata()

    # ── documents ──────────────────────────────────────────────────────
    doc_set = {}
    for c in chunks:
        doc_id = c.get("doc_id", "")
        if doc_id and doc_id not in doc_set:
            doc_set[doc_id] = {
                "doc_id": doc_id,
                "company": c.get("company", ""),
                "year": int(c.get("year") or 0),
                "doc_type": c.get("doc_type", "10-K"),
                "page_count": 0,
            }

    for d in doc_set.values():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO documents (doc_id, company, year, doc_type, page_count) "
                "VALUES (?, ?, ?, ?, ?)",
                [d["doc_id"], d["company"], d["year"], d["doc_type"], d["page_count"]],
            )
        except Exception as e:
            logger.warning(f"Doc insert failed: {e}")

    # ── sections_metadata ──────────────────────────────────────────────
    seen_sections = set()
    sec_count = 0
    for c in chunks:
        sid = c.get("section_id", "")
        if sid and sid not in seen_sections:
            seen_sections.add(sid)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO sections_metadata "
                    "(section_id, doc_id, company, year, section_type, char_count) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        sid, c.get("doc_id", ""), c.get("company", ""),
                        int(c.get("year") or 0),
                        c.get("section_type", "general"),
                        len(c.get("text", "")),
                    ],
                )
                sec_count += 1
            except Exception:
                pass

    # ── signals ────────────────────────────────────────────────────────
    sig_count = 0
    for s in signals:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO signals "
                "(signal_id, doc_id, company, year, section_id, signal_type, signal_text, context) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    s["signal_id"], s["doc_id"], s["company"], int(s["year"] or 0),
                    s.get("section_id", ""), s["signal_type"],
                    s["signal_text"], s["context"],
                ],
            )
            sig_count += 1
        except Exception as e:
            logger.debug(f"Signal insert failed: {e}")

    # ── financial_metrics + knowledge_kpis ────────────────────────────
    kpi_count = 0
    for k in kpis:
        try:
            metric_id = f"{k['doc_id']}_{k['metric_name']}"
            conn.execute(
                "INSERT OR REPLACE INTO financial_metrics "
                "(metric_id, doc_id, company, year, metric_name, value, unit, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [metric_id, k["doc_id"], k["company"], int(k["year"] or 0),
                 k["metric_name"], k["value"], k.get("unit", ""), "phase1_metadata"],
            )
            conn.execute(
                "INSERT OR REPLACE INTO knowledge_kpis "
                "(kpi_id, doc_id, company, fiscal_year, metric_name, value, unit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [metric_id, k["doc_id"], k["company"], int(k["year"] or 0),
                 k["metric_name"], k["value"], k.get("unit", "")],
            )
            kpi_count += 1
        except Exception as e:
            logger.debug(f"KPI insert failed: {e}")

    # ── tables_metadata (count only) ──────────────────────────────────
    table_count = 0
    try:
        table_count = conn.execute("SELECT COUNT(*) FROM tables_metadata").fetchone()[0]
    except Exception:
        table_count = 0

    conn.close()

    stats = {
        "documents": len(doc_set),
        "sections": sec_count,
        "signals": sig_count,
        "kpis": kpi_count,
        "tables": table_count,
    }
    logger.info(f"   ✅ DuckDB: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(setup_duckdb())