# LedgerCapital — verified-core integration (not the entire finished project)

This package preserves the original source and adds `verified_server.py`, an evidence-first Flask API using DuckDB and ChromaDB. It does **not** claim the original CrewAI, Neo4j, KPI, anomaly, reporting, or evaluation modules are corrected.

## Windows installation

1. Install Python 3.11 and Node.js LTS.
2. In the project root, run `py -3.11 -m venv .venv`.
3. Run `.venv\Scripts\activate`.
4. Run `python -m pip install -r requirements-verified.txt`.
5. Set `GROQ_API_KEY` in your local `.env` (optional; without it the API returns retrieved evidence excerpts instead of generated prose). Do not upload or commit `.env`.
6. Run `python verified_server.py` in one terminal.
7. In a second terminal, run `cd frontend`, `npm install`, then `npm run dev`.
8. Open http://localhost:3000. Health: http://localhost:5001/api/health.

The existing AdminPanel uploads the PDF, then calls `/api/documents/implement-learning`. This now actually indexes the document. Documents with no extractable text return HTTP 422; scanned PDFs need OCR.

## Important limitations

- Financial KPI extraction, financial unit normalization, Neo4j ingestion, peer comparison, real outlier analysis, CrewAI multi-agent execution, chart/report generation and evaluation are NOT integrated into this verified core.
- Semantic retrieval uses Chroma's default embedding function consistently, not the original BGE-large model. On first use, Chroma may download an embedding model and needs internet.
- The core does not fabricate graph data or evaluation scores. It returns explicit empty/not-computed results for those endpoints.
- The uploaded project contains other legacy endpoints that are not implemented by `verified_server.py`. Frontend pages relying on those may not function yet.
- Uploaded PDFs should be from sources you are authorized to process. Financial figures are not verified against source tables by this core.
- Never commit `.env`, tokens or database credentials. Rotate previously exposed keys.

## Smoke tests

- `python -m compileall -q verified_server.py`
- `python -m unittest discover -s tests -p 'test_verified_core.py' -v`
- Start API and visit `/api/health`.
- Upload a machine-readable PDF via AdminPanel, wait for indexing, then ask a question that quotes content in the PDF.
- Inspect `/api/documents/parsed` and `/api/kb/search` for actual indexed evidence.
