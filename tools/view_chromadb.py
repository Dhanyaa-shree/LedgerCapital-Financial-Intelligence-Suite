"""
View ChromaDB: Inspect indexed collections, chunks, and metadata.

Usage:
    python tools/view_chromadb.py
    python tools/view_chromadb.py --collection all_sections
    python tools/view_chromadb.py --collection all_sections --company AMD --year 2021
    python tools/view_chromadb.py --search "revenue growth"
    python tools/view_chromadb.py --sample 5
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

import chromadb

# Allow running from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

CHROMADB_PATH = PROJECT_ROOT / "data" / "chromadb"


# ── Helpers ───────────────────────────────────────────────────────────
def _truncate(text: str, n: int = 200) -> str:
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "..."


def _print_separator(char: str = "─", width: int = 80):
    print(char * width)


# ── Commands ──────────────────────────────────────────────────────────
def list_collections():
    """Print a summary of every ChromaDB collection."""
    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    try:
        collections = client.list_collections()
    except Exception as e:
        print(f"❌ Cannot list collections: {e}")
        return

    names = [c.name if hasattr(c, "name") else str(c) for c in collections]

    if not names:
        print("❌ No collections found. Run `py phase3/setup.py` first.")
        return

    print()
    _print_separator("=")
    print(f"CHROMADB  ·  {CHROMADB_PATH}")
    _print_separator("=")
    print()

    total = 0
    for name in names:
        try:
            col = client.get_collection(name)
            count = col.count()
            total += count
        except Exception as e:
            print(f"  {name:25s}  ⚠️  {e}")
            continue

        print(f"  {name:25s}  {count:>6d} chunks")

    print()
    print(f"  {'TOTAL':25s}  {total:>6d} chunks")
    print()


def inspect_collection(collection_name: str, sample_size: int = 3):
    """Show metadata distribution for one collection."""
    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    try:
        col = client.get_collection(collection_name)
    except Exception as e:
        print(f"❌ Collection '{collection_name}' not found: {e}")
        return

    count = col.count()
    if count == 0:
        print(f"⚠️  Collection '{collection_name}' is empty.")
        return

    # Sample up to `sample_size` chunks with full metadata
    sample = col.get(limit=sample_size, include=["documents", "metadatas"])
    # Load ALL metadatas for distribution stats (may be large; cap at 5000)
    full = col.get(limit=min(count, 5000), include=["metadatas"])

    print()
    _print_separator("=")
    print(f"COLLECTION: {collection_name}")
    print(f"Total chunks: {count}")
    _print_separator("=")
    print()

    # ── Distribution of companies ──
    metas = full.get("metadatas", []) or []
    companies = Counter((m.get("company") or "?") for m in metas)
    years = Counter(str(m.get("year") or "?") for m in metas)
    sections = Counter((m.get("section_type") or "?") for m in metas)
    doc_ids = Counter((m.get("doc_id") or "?") for m in metas)

    def _show_counter(title: str, counter: Counter, top: int = 10):
        print(f"  {title}:")
        for k, v in counter.most_common(top):
            print(f"    {k:35s}  {v:>5d}")
        if len(counter) > top:
            print(f"    ... +{len(counter) - top} more")
        print()

    _show_counter("Companies", companies)
    _show_counter("Years", years)
    _show_counter("Section types", sections)
    _show_counter("Documents", doc_ids)

    # ── Sample chunks ──
    print(f"  Sample chunks (first {sample_size}):")
    _print_separator("-")
    docs = sample.get("documents", []) or []
    for i, doc in enumerate(docs, 1):
        meta = sample["metadatas"][i - 1] if i - 1 < len(sample.get("metadatas", [])) else {}
        print(f"\n  [{i}] {meta.get('company')} {meta.get('year')} · "
              f"{meta.get('section_type')} · page {meta.get('page', '?')}")
        print(f"      {_truncate(doc, 300)}")
    print()


def filter_by_company_year(collection_name: str, company: str, year: int, limit: int = 5):
    """Search for chunks matching a company + year."""
    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    try:
        col = client.get_collection(collection_name)
    except Exception as e:
        print(f"❌ Collection '{collection_name}' not found: {e}")
        return

    where = {"$and": [{"company": company.upper()}, {"year": str(year)}]}

    try:
        results = col.get(where=where, limit=limit, include=["documents", "metadatas"])
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return

    ids = results.get("ids", []) or []
    if not ids:
        print(f"⚠️  No chunks found for {company} {year} in '{collection_name}'")
        return

    print()
    _print_separator("=")
    print(f"CHUNKS  ·  {company} {year}  ·  {collection_name}")
    print(f"Showing {len(ids)} of the matching chunks")
    _print_separator("=")
    print()

    docs = results.get("documents", []) or []
    metas = results.get("metadatas", []) or []
    for i, cid in enumerate(ids, 1):
        meta = metas[i - 1] if i - 1 < len(metas) else {}
        doc = docs[i - 1] if i - 1 < len(docs) else ""
        print(f"  [{i}] chunk_id: {cid}")
        print(f"      company={meta.get('company')}  year={meta.get('year')}  "
              f"section={meta.get('section_type')}  page={meta.get('page', '?')}")
        print(f"      {_truncate(doc, 300)}")
        print()


def semantic_search(collection_name: str, query: str, top_k: int = 5):
    """Embed a query and retrieve the nearest chunks (uses collection's own embeddings)."""
    from sentence_transformers import SentenceTransformer

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    try:
        col = client.get_collection(collection_name)
    except Exception as e:
        print(f"❌ Collection '{collection_name}' not found: {e}")
        return

    count = col.count()
    if count == 0:
        print(f"⚠️  Collection '{collection_name}' is empty.")
        return

    model = SentenceTransformer("BAAI/bge-large-en-v1.5")
    emb = model.encode(query).tolist()

    results = col.query(
        query_embeddings=[emb],
        n_results=min(top_k, count),
        include=["documents", "metadatas", "distances"],
    )

    ids = results.get("ids", [[]])[0]
    if not ids:
        print("No results.")
        return

    print()
    _print_separator("=")
    print(f"SEMANTIC SEARCH  ·  '{query}'")
    print(f"Collection: {collection_name}")
    _print_separator("=")
    print()

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    for i, cid in enumerate(ids, 1):
        meta = metas[i - 1] if i - 1 < len(metas) else {}
        doc = docs[i - 1] if i - 1 < len(docs) else ""
        dist = dists[i - 1] if i - 1 < len(dists) else 0
        sim = round(1 - dist, 3)
        print(f"  [{i}] similarity={sim}  {meta.get('company')} {meta.get('year')}  "
              f"· {meta.get('section_type')} · page {meta.get('page', '?')}")
        print(f"      {_truncate(doc, 300)}")
        print()


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="View ChromaDB contents")
    parser.add_argument("--collection", "-c", help="Collection name (default: show all)")
    parser.add_argument("--company", help="Filter by company (e.g. AMD)")
    parser.add_argument("--year", type=int, help="Filter by year (e.g. 2021)")
    parser.add_argument("--search", "-s", help="Semantic search query")
    parser.add_argument("--sample", type=int, default=3, help="Number of sample chunks to show")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for semantic search")

    args = parser.parse_args()

    # If no collection specified → list all and exit
    if not args.collection:
        list_collections()
        return

    # Semantic search mode
    if args.search:
        semantic_search(args.collection, args.search, top_k=args.top_k)
        return

    # Company+year filter mode
    if args.company and args.year:
        filter_by_company_year(args.collection, args.company, args.year, limit=args.sample)
        return

    # Default: show distribution + sample
    inspect_collection(args.collection, sample_size=args.sample)


if __name__ == "__main__":
    main()