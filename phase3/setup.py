"""
Phase 3 Setup: Full pipeline runner
Runs Neo4j → DuckDB → ChromaDB in order.
"""

import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from phase3.neo4j_setup import setup_neo4j
from phase3.duckdb_setup import setup_duckdb
from phase3.chromadb_setup import setup_chromadb

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    print("\n" + "=" * 80)
    print("PHASE 3: STORAGE & RETRIEVAL SETUP")
    print("=" * 80)

    # ── STEP 1: Neo4j ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("STEP 1: NEO4J SETUP")
    print("=" * 80)
    neo4j_stats = setup_neo4j()

    # ── STEP 2: DuckDB ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("STEP 2: DUCKDB SETUP")
    print("=" * 80)
    duckdb_stats = setup_duckdb()

    # ── STEP 3: ChromaDB ───────────────────────────────────────────
    print("\n" + "=" * 80)
    print("STEP 3: CHROMADB SETUP")
    print("=" * 80)
    chromadb_stats = setup_chromadb()

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("PHASE 3 SETUP COMPLETE")
    print("=" * 80)

    print(f"\n✅ Neo4j Statistics:")
    print(f"   Documents: {neo4j_stats.get('documents', 0)}")
    print(f"   Sections:  {neo4j_stats.get('sections', 0)}")
    print(f"   Chunks:    {neo4j_stats.get('chunks', 0)}")

    print(f"\n✅ DuckDB Statistics:")
    print(f"   Documents: {duckdb_stats.get('documents', 0)}")
    print(f"   Sections:  {duckdb_stats.get('sections', 0)}")
    print(f"   Signals:   {duckdb_stats.get('signals', 0)}")

    print(f"\n✅ ChromaDB Statistics:")
    for name, count in (chromadb_stats or {}).items():
        print(f"   {name}: {count} chunks")

    print("\n" + "=" * 80)
    print("✅ Phase 3 complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()