"""
Generate Analytics summaries from the indexed corpus.

Reads:
  - ChromaDB (data/chromadb)  → company, year, section metadata
  - Neo4j                     → document inventory

Writes:
  - outlier_analysis/company_summary.json
  - outlier_analysis/year_wise_summary.json

These match the shape the Analytics page expects, so it renders real
corpus stats instead of being empty.

Run:
    py tools/generate_outlier_summary.py
"""

import os
import json
from collections import defaultdict
from pathlib import Path

import chromadb
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

CHROMADB_PATH = PROJECT_ROOT / "data" / "chromadb"
OUTLIER_DIR = PROJECT_ROOT / "outlier_analysis"
OUTLIER_DIR.mkdir(parents=True, exist_ok=True)

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "ledgerpilot")


# ── Read ChromaDB ─────────────────────────────────────────────────────
def collect_from_chroma():
    """Aggregate company/year/section stats from ChromaDB."""
    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    # Aggregate across all collections (chunks can live in any of them)
    try:
        listed = client.list_collections()
    except Exception as e:
        print(f"❌ Cannot list ChromaDB collections: {e}")
        return {}

    collection_names = [c.name if hasattr(c, "name") else str(c) for c in listed]
    if not collection_names:
        print("❌ No ChromaDB collections found. Run phase3/setup.py first.")
        return {}

    print(f"📚 Reading from {len(collection_names)} collections: {collection_names}")

    by_company = defaultdict(lambda: {
        "documents": defaultdict(lambda: {
            "doc_id": "",
            "doc_type": "",
            "year": None,
            "chunk_count": 0,
            "section_types": defaultdict(int),
        }),
        "total_chunks": 0,
        "years": set(),
    })

    by_year = defaultdict(lambda: {
        "companies": defaultdict(lambda: {"chunk_count": 0, "doc_type": ""}),
        "total_chunks": 0,
    })

    total_seen = 0
    seen_ids = set()

    for col_name in collection_names:
        try:
            col = client.get_collection(col_name)
        except Exception as e:
            print(f"   ⚠️  Skipping {col_name}: {e}")
            continue

        count = col.count()
        if count == 0:
            continue

        print(f"   Reading {col_name}: {count} chunks")

        BATCH = 500
        offset = 0
        while offset < count:
            try:
                batch = col.get(limit=BATCH, offset=offset, include=["metadatas"])
            except Exception as e:
                print(f"   ⚠️  get failed on {col_name} at offset {offset}: {e}")
                break

            metadatas = batch.get("metadatas", []) or []
            ids = batch.get("ids", []) or []

            for i, m in enumerate(metadatas):
                chunk_id = ids[i] if i < len(ids) else None
                if chunk_id and chunk_id in seen_ids:
                    continue
                if chunk_id:
                    seen_ids.add(chunk_id)
                total_seen += 1

                company = (m.get("company") or "").upper().strip()
                year = m.get("year")
                doc_id = m.get("doc_id") or ""
                doc_type = m.get("doc_type") or ""
                section_type = m.get("section_type") or "general"

                if not company:
                    continue

                # Company rollup
                co = by_company[company]
                co["total_chunks"] += 1
                if year:
                    try:
                        co["years"].add(int(year))
                    except (ValueError, TypeError):
                        pass

                if doc_id:
                    doc = co["documents"][doc_id]
                    doc["doc_id"] = doc_id
                    doc["doc_type"] = doc_type
                    if year:
                        try:
                            doc["year"] = int(year)
                        except (ValueError, TypeError):
                            pass
                    doc["chunk_count"] += 1
                    doc["section_types"][section_type] += 1

                # Year rollup
                if year:
                    try:
                        y = int(year)
                        by_year[y]["total_chunks"] += 1
                        by_year[y]["companies"][company]["chunk_count"] += 1
                        if doc_type:
                            by_year[y]["companies"][company]["doc_type"] = doc_type
                    except (ValueError, TypeError):
                        pass

            offset += BATCH

    print(f"   ✅ Aggregated {total_seen} unique chunks")

    # Convert to JSON-friendly shape
    company_summary = []
    for company, data in sorted(by_company.items()):
        years_sorted = sorted(data["years"])
        docs_list = []
        for doc_id, doc in data["documents"].items():
            docs_list.append({
                "doc_id": doc_id,
                "doc_type": doc["doc_type"],
                "year": doc["year"],
                "chunk_count": doc["chunk_count"],
                "analysis": (
                    f"{company} {doc.get('year', '')} {doc.get('doc_type', '')} — "
                    f"{doc['chunk_count']} indexed chunks across "
                    f"{len(doc['section_types'])} section types."
                ),
                "section_breakdown": dict(doc["section_types"]),
            })
        docs_list.sort(key=lambda d: (d.get("year") or 0), reverse=True)

        company_summary.append({
            "company": company,
            "total_documents": len(docs_list),
            "year_range": (
                f"{years_sorted[0]}-{years_sorted[-1]}"
                if len(years_sorted) > 1
                else (str(years_sorted[0]) if years_sorted else "—")
            ),
            "years_covered": years_sorted,
            "total_chunks": data["total_chunks"],
            "documents": docs_list,
        })

    year_summary = {}
    for year, data in sorted(by_year.items(), reverse=True):
        year_summary[str(year)] = {
            company: {
                "chunk_count": info["chunk_count"],
                "doc_type": info["doc_type"],
                "doc_id": f"{company}_{year}_10K",
                "analysis": (
                    f"{company} filed a {info['doc_type'] or '10-K'} in {year} "
                    f"with {info['chunk_count']} indexed chunks."
                ),
            }
            for company, info in data["companies"].items()
        }

    return {
        "company_summary": company_summary,
        "year_summary": year_summary,
    }


# ── Read Neo4j (optional enrichment) ─────────────────────────────────
def enrich_with_neo4j(company_summary):
    """If Neo4j is up, fill in doc_type / year where Chroma metadata is missing."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database=NEO4J_DATABASE) as s:
            rows = s.run("""
                MATCH (c:Company)-[:FILED]->(d:Document)
                RETURN c.name AS company, d.doc_id AS doc_id,
                       d.year AS year, d.doc_type AS doc_type
            """).data()
        driver.close()

        lookup = {(r["company"], r["doc_id"]): r for r in rows}
        for co in company_summary:
            for doc in co["documents"]:
                key = (co["company"], doc["doc_id"])
                if key in lookup:
                    r = lookup[key]
                    if not doc.get("doc_type") and r.get("doc_type"):
                        doc["doc_type"] = r["doc_type"]
                    if not doc.get("year") and r.get("year"):
                        doc["year"] = r["year"]
        print(f"🔗 Enriched from Neo4j ({len(rows)} documents)")
    except Exception as e:
        print(f"⚠️  Neo4j enrichment skipped: {e}")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("GENERATE ANALYTICS SUMMARIES")
    print("=" * 60)

    data = collect_from_chroma()
    if not data or not data.get("company_summary"):
        print("❌ No data to summarize. Is ChromaDB populated? Run phase3/setup.py first.")
        return

    company_summary = data["company_summary"]
    year_summary = data["year_summary"]

    enrich_with_neo4j(company_summary)

    # Write company summary
    co_path = OUTLIER_DIR / "company_summary.json"
    with open(co_path, "w") as f:
        json.dump(company_summary, f, indent=2)
    print(f"\n✅ Wrote {co_path}")
    print(f"   {len(company_summary)} companies:")
    for co in company_summary:
        print(
            f"     • {co['company']:12s} | {co['total_documents']} doc(s) | "
            f"{co['year_range']:>9s} | {co['total_chunks']:>5d} chunks"
        )

    # Write year summary
    yr_path = OUTLIER_DIR / "year_wise_summary.json"
    with open(yr_path, "w") as f:
        json.dump(year_summary, f, indent=2)
    print(f"\n✅ Wrote {yr_path}")
    print(f"   {len(year_summary)} year(s):")
    for year, companies in year_summary.items():
        n = len(companies)
        print(f"     • {year}: {n} compan{'y' if n == 1 else 'ies'}")

    print("\n" + "=" * 60)
    print("✅ Done. Restart Flask, then open /analytics in the browser.")
    print("=" * 60)


if __name__ == "__main__":
    main()