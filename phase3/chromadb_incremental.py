"""
ChromaDB Incremental: Add new chunks without rebuilding the whole collection.

Usage:
    python phase3/chromadb_incremental.py
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

import chromadb
from sentence_transformers import SentenceTransformer

import sys
sys.path.append(str(Path(__file__).parent.parent))
from phase3.config import CHROMADB_PATH, PHASE2_OUTPUT, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

BATCH_SIZE = 32


def _load_all_chunks() -> List[Dict]:
    """Load every chunk JSON from phase2 output."""
    chunks_dir = PHASE2_OUTPUT / "chunks"
    all_chunks: List[Dict] = []
    if not chunks_dir.exists():
        logger.warning(f"No chunks directory at {chunks_dir}")
        return all_chunks

    for f in sorted(chunks_dir.rglob("*_chunks.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            meta = data.get("metadata", {})
            doc_id = data.get("doc_id", f.stem)
            for c in data.get("chunks", []):
                c["doc_id"] = c.get("doc_id") or doc_id
                c["company"] = c.get("company") or meta.get("company", "")
                c["year"] = c.get("year") or meta.get("year", 0)
                c["doc_type"] = c.get("doc_type") or meta.get("doc_type", "")
                c["section_type"] = c.get("section_type") or "general"
                # make sure IDs are unique across docs
                if "chunk_id" in c:
                    c["chunk_id"] = f"{doc_id}_{c['chunk_id']}" if not c["chunk_id"].startswith(doc_id) else c["chunk_id"]
                all_chunks.append(c)
        except Exception as e:
            logger.warning(f"Failed to load {f}: {e}")

    logger.info(f"Loaded {len(all_chunks)} chunks from phase2")
    return all_chunks


def _already_indexed(collection, chunk_ids: List[str]) -> set:
    """Return the subset of chunk_ids that already exist in the collection."""
    if not chunk_ids:
        return set()
    try:
        existing = collection.get(ids=chunk_ids)
        return set(existing.get("ids", []) or [])
    except Exception:
        return set()


def setup_chromadb_incremental(collection_name: str = "all_sections") -> Dict:
    """
    Add only new chunks to the ChromaDB collection.

    Returns:
        Dict with counts: total, new, skipped.
    """
    logger.info(f"🔄 Incremental ChromaDB at {CHROMADB_PATH}")
    CHROMADB_PATH.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    # Get or create collection
    try:
        collection = client.get_collection(collection_name)
        logger.info(f"   Using existing collection: {collection_name}")
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "Financial document chunks"},
        )
        logger.info(f"   Created new collection: {collection_name}")

    # Load
    all_chunks = _load_all_chunks()
    if not all_chunks:
        return {"collection": collection_name, "total": 0, "new": 0, "skipped": 0}

    # Filter to chunks with text
    chunks = [c for c in all_chunks if c.get("text", "").strip()]
    for c in chunks:
        # guarantee a chunk_id
        if not c.get("chunk_id"):
            c["chunk_id"] = f"{c.get('doc_id','doc')}_p{c.get('page',0)}_c{c.get('chunk_index',0)}"

    chunk_ids = [c["chunk_id"] for c in chunks]
    existing = _already_indexed(collection, chunk_ids)
    new_chunks = [c for c in chunks if c["chunk_id"] not in existing]

    logger.info(f"   Total: {len(chunks)}, already indexed: {len(existing)}, new: {len(new_chunks)}")

    if not new_chunks:
        return {"collection": collection_name, "total": len(chunks), "new": 0, "skipped": len(existing)}

    # Load embedding model
    logger.info(f"   Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    # Insert in batches
    inserted = 0
    for i in range(0, len(new_chunks), BATCH_SIZE):
        batch = new_chunks[i:i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["chunk_id"] for c in batch]
        metadatas = [
            {
                "doc_id": c.get("doc_id", ""),
                "company": c.get("company", ""),
                "year": str(c.get("year") or ""),
                "doc_type": c.get("doc_type", ""),
                "section_type": c.get("section_type", "general"),
                "section_id": c.get("section_id", ""),
                "page": str(c.get("page", 0)),
                "chunk_index": str(c.get("chunk_index", 0)),
            }
            for c in batch
        ]

        try:
            embeddings = model.encode(texts, show_progress_bar=False).tolist()
            collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            inserted += len(batch)
            logger.info(f"   Batch {i // BATCH_SIZE + 1}: +{len(batch)} chunks (running total {inserted})")
        except Exception as e:
            logger.error(f"   Batch insert failed: {e}")

    final_count = collection.count()
    logger.info(f"   ✅ Inserted {inserted} new chunks. Collection now has {final_count} total.")

    return {
        "collection": collection_name,
        "total": len(chunks),
        "new": inserted,
        "skipped": len(existing),
        "final_count": final_count,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = setup_chromadb_incremental()
    print(json.dumps(result, indent=2))