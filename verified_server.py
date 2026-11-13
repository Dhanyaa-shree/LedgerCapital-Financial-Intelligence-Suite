"""LedgerCapital validated core API.

Run: python verified_server.py
Optional integrations (Chroma, Groq, Neo4j) degrade explicitly, never fabricate results.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DB = DATA / 'duckdb' / 'ledgercapital_verified.duckdb'
CHROMA = DATA / 'chromadb_verified'
UPLOAD = ROOT / 'uploads'
COLLECTION = 'ledgercapital_evidence_v1'
MAX_BYTES = 30 * 1024 * 1024

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES
CORS(app, resources={r'/api/*': {'origins': os.getenv('FRONTEND_ORIGIN', 'http://localhost:3000')}})


def connection():
    import duckdb
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    con.execute('''CREATE TABLE IF NOT EXISTS documents (
      doc_id VARCHAR PRIMARY KEY, filename VARCHAR, company VARCHAR,
      fiscal_year INTEGER, pages INTEGER, status VARCHAR, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    con.execute('''CREATE TABLE IF NOT EXISTS evidence (
      chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, company VARCHAR,
      fiscal_year INTEGER, page INTEGER, section VARCHAR, content VARCHAR)''')
    return con


def vector_collection():
    import chromadb
    CHROMA.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA))
    # Chroma's default embedding model is intentionally used consistently for indexing and querying.
    return client.get_or_create_collection(COLLECTION, metadata={'hnsw:space': 'cosine'})


def metadata(filename):
    stem = Path(filename).stem
    match = re.search(r'(?<!\d)(20\d{2})(?!\d)', stem)
    year = int(match.group(1)) if match else None
    company = re.split(r'[_\s-]+', stem)[0].upper()
    if company in {'', 'REPORT', 'ANNUAL', 'FINANCIAL'}:
        company = 'UNKNOWN'
    return company, year


def section_label(text):
    t = text[:600].lower()
    for label, pattern in (
        ('risk_factors', r'item\s*1a\b|risk factors'),
        ('mda', r'item\s*7\b|management.s discussion'),
        ('cashflow', r'statement[s]? of cash flows'),
        ('income_statement', r'statement[s]? of (operations|income)'),
        ('balance_sheet', r'balance sheets|statement[s]? of financial position'),
        ('ceo_letter', r'dear shareholders|letter to shareholders'),
        ('esg', r'sustainability|environmental, social'),
    ):
        if re.search(pattern, t):
            return label
    return 'general'


def chunks_from_pdf(path, doc_id, company, year):
    import fitz
    chunks = []
    with fitz.open(str(path)) as pdf:
        if not pdf.is_pdf:
            raise ValueError('Not a PDF')
        if pdf.needs_pass:
            raise ValueError('Password-protected PDF is not supported')
        pages = len(pdf)
        for p, page in enumerate(pdf, 1):
            text = page.get_text('text') or ''
            words = text.split()
            if not words:
                continue
            section = section_label(text)
            for i, start in enumerate(range(0, len(words), 400)):
                content = ' '.join(words[start:start + 480])
                if len(content) < 70:
                    continue
                cid = f'{doc_id}:p{p}:c{i}'
                chunks.append(dict(chunk_id=cid, doc_id=doc_id, company=company,
                                   fiscal_year=year, page=p, section=section, content=content))
    return pages, chunks


def ingest(path, filename, company=None, year=None):
    company0, year0 = metadata(filename)
    company = (company or company0).strip().upper()
    year = int(year) if year is not None else year0
    if not re.fullmatch(r'[A-Z0-9_. -]{1,80}', company):
        raise ValueError('Invalid company')
    if year is not None and not 1990 <= year <= 2100:
        raise ValueError('Invalid fiscal year')
    doc_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    pages, chunks = chunks_from_pdf(path, doc_id, company, year)
    if not chunks:
        raise ValueError('No extractable text found. Scanned PDF requires OCR.')
    # Vector upsert first; if it fails, do not claim the document is ingested.
    col = vector_collection()
    for start in range(0, len(chunks), 100):
        batch = chunks[start:start + 100]
        col.upsert(ids=[c['chunk_id'] for c in batch],
                   documents=[c['content'] for c in batch],
                   metadatas=[dict(doc_id=c['doc_id'], company=c['company'],
                                   fiscal_year=c['fiscal_year'] or 0,
                                   page=c['page'], section=c['section']) for c in batch])
    con = connection()
    try:
        con.execute('BEGIN TRANSACTION')
        con.execute('DELETE FROM evidence WHERE doc_id=?', [doc_id])
        con.execute('DELETE FROM documents WHERE doc_id=?', [doc_id])
        con.execute('INSERT INTO documents(doc_id,filename,company,fiscal_year,pages,status) VALUES(?,?,?,?,?,?)',
                    [doc_id, filename, company, year, pages, 'indexed'])
        con.executemany('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',
                        [[c[k] for k in ('chunk_id','doc_id','company','fiscal_year','page','section','content')] for c in chunks])
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise
    finally:
        con.close()
    return dict(doc_id=doc_id, filename=filename, company=company, year=year, pages=pages, chunks=len(chunks), status='indexed')


def docs():
    con = connection()
    try:
        rows = con.execute('SELECT doc_id,filename,company,fiscal_year,pages,status FROM documents ORDER BY created_at DESC').fetchall()
        return [dict(zip(('doc_id','filename','company','year','pages','status'), r)) for r in rows]
    finally:
        con.close()


def search(query, company=None, year=None, limit=8):
    col = vector_collection()
    if col.count() == 0:
        return []
    conditions = []
    if company:
        conditions.append({'company': {'$eq': company.upper()}})
    if year:
        conditions.append({'fiscal_year': {'$eq': int(year)}})
    where = ({'$and': conditions} if len(conditions) > 1 else conditions[0]) if conditions else None
    kwargs = {'query_texts': [query], 'n_results': min(limit, col.count()), 'include': ['documents','metadatas','distances']}
    if where:
        kwargs['where'] = where
    result = col.query(**kwargs)
    out = []
    for cid, txt, meta, distance in zip(result['ids'][0], result['documents'][0], result['metadatas'][0], result['distances'][0]):
        out.append(dict(id=cid, text=txt, metadata=meta, distance=distance,
                        citation=f"{meta['company']} {meta['fiscal_year'] or 'year unknown'}, page {meta['page']}"))
    return out


@app.get('/api/health')
def health():
    try:
        count = len(docs())
        return jsonify(status='ok', documents=count, storage='duckdb+chromadb')
    except Exception:
        return jsonify(status='unavailable'), 503


@app.post('/api/documents/upload')
def upload():
    f = request.files.get('file')
    if f is None or not f.filename:
        return jsonify(error='PDF file required'), 400
    if Path(f.filename).suffix.lower() != '.pdf':
        return jsonify(error='Only PDF files are supported'), 400
    filename = secure_filename(f.filename)
    UPLOAD.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD / f'{uuid.uuid4().hex}_{filename}'
    f.save(dest)
    if dest.stat().st_size == 0 or dest.read_bytes()[:5] != b'%PDF-':
        dest.unlink(missing_ok=True)
        return jsonify(error='Invalid PDF content'), 400
    return jsonify(status='success', filename=filename, upload_id=dest.name, message='PDF uploaded. Indexing is the next step.')


@app.post('/api/documents/implement-learning')
def process_upload():
    payload = request.get_json(silent=True) or {}
    upload_id = payload.get('upload_id')
    filename = payload.get('filename', '')
    if upload_id:
        if Path(upload_id).name != upload_id:
            return jsonify(error='Invalid upload ID'), 400
        path = UPLOAD / upload_id
    else:
        # Backwards compatibility for the existing AdminPanel, which sends filename only.
        safe = secure_filename(filename)
        matches = sorted(UPLOAD.glob(f'*_{safe}'), key=lambda p: p.stat().st_mtime, reverse=True) if safe else []
        path = matches[0] if matches else UPLOAD / '__missing__'
    if not path.is_file():
        return jsonify(error='Uploaded file not found'), 404
    try:
        info = ingest(path, filename or path.name, payload.get('company'), payload.get('year'))
        return jsonify(status='success', filename=info['filename'], implementation=f"Indexed {info['chunks']} evidence chunks across {info['pages']} pages.", document=info)
    except ValueError as e:
        return jsonify(error=str(e)), 422
    except Exception:
        app.logger.exception('Document indexing failed')
        return jsonify(error='Indexing failed; check backend logs'), 500


@app.get('/api/documents/parsed')
def parsed():
    rows = docs()
    return jsonify(documents=[dict(name=d['filename'], filename=d['filename'], doc_id=d['doc_id'],
                                   company=d['company'], year=d['year'], sections='indexed', uploaded='') for d in rows], total=len(rows))


@app.get('/api/documents/stats')
def document_stats():
    rows = docs()
    return jsonify(count=len(list(UPLOAD.glob('*.pdf'))) if UPLOAD.exists() else 0, duckdb_count=len(rows), indexed=len(rows))


@app.get('/api/documents/<doc_id>')
def detail(doc_id):
    con = connection()
    try:
        rows = con.execute('SELECT page,section,content FROM evidence WHERE doc_id=? ORDER BY page LIMIT 100', [doc_id]).fetchall()
        if not rows:
            return jsonify(error='Document not found'), 404
        return jsonify(doc_id=doc_id, chunks=[dict(page=p,section=s,text=t) for p,s,t in rows])
    finally:
        con.close()


@app.post('/api/kb/search')
def kb_search():
    p = request.get_json(silent=True) or {}
    q = str(p.get('query','')).strip()
    if not q:
        return jsonify(error='query required'), 400
    try:
        return jsonify(results=search(q,p.get('company'),p.get('year'),min(max(int(p.get('top_k',8)),1),30)))
    except Exception:
        app.logger.exception('Search failed')
        return jsonify(error='Search unavailable; check indexing and dependencies'), 503


def normalize_financial_markdown(answer: str) -> str:
    """Repair flattened GFM tables without altering evidence or citations."""
    if not answer:
        return answer
    answer = answer.replace('\r\n', '\n').replace('\r', '\n')
    lines = []
    for line in answer.split('\n'):
        # Some LLMs emit a whole table on one line, separating rows with " | | ".
        # Only split when the line contains a Markdown separator row.
        if re.search(r'\|\s*:?-{3,}:?\s*\|', line) and re.search(r'\|\s+\|', line):
            line = re.sub(r'\|\s+\|', '|\n|', line)
        lines.append(line)
    return '\n'.join(lines).strip()


@app.post('/api/query')
def query():
    from ledger_kpis import list_kpis
    from ledger_query_signals import select_signals, signal_context, signal_sources

    request_started = time.perf_counter()
    p = request.get_json(silent=True) or {}
    q = str(p.get('query', '')).strip()
    if not q:
        return jsonify(error='query required'), 400
    indexed = docs()
    known = {d['company'] for d in indexed if d['company'] != 'UNKNOWN'}
    companies = sorted(c for c in known if re.search(r'(?<!\w)' + re.escape(c) + r'(?!\w)', q, re.I))
    years = sorted(set(int(y) for y in re.findall(r'(?<!\d)20\d{2}(?!\d)', q)))

    # Read actual, previously extracted financial records from DuckDB.
    try:
        con = connection()
        try:
            signals = select_signals(q, list_kpis(con), companies, years)
        finally:
            con.close()
    except Exception:
        app.logger.exception('DuckDB KPI lookup failed')
        return jsonify(error='KPI lookup failed; check backend logs'), 503

    # Retrieve PDF evidence independently. The question can contain two years;
    # do not force the Chroma document fiscal year to equal both years.
    try:
        evidence = search(q, companies[0] if len(companies) == 1 else None,
                          years[0] if len(years) == 1 else None, 8)
    except Exception:
        app.logger.exception('Retrieval failed')
        return jsonify(error='Retrieval failed'), 503

    # Stable evidence IDs match the IDs supplied to the language model.
    # Keep legacy citation strings for existing dashboard components.
    kpi_sources = signal_sources(signals)
    citations = [e['citation'] for e in evidence]
    citations.extend(s['citation'] for s in kpi_sources)
    sources = [
        dict(ref_id=f'P{i}', evidence_id=f'P{i}', text=e['text'],
             citation=e['citation'], page=e['metadata']['page'],
             company=e['metadata']['company'], year=e['metadata']['fiscal_year'],
             doc_id=e['metadata']['doc_id'], source_type='chromadb')
        for i, e in enumerate(evidence, 1)
    ]
    for i, source in enumerate(kpi_sources, 1):
        item = dict(source)
        item['ref_id'] = f'K{i}'
        item['evidence_id'] = f'K{i}'
        sources.append(item)

    if not evidence and not signals:
        answer = 'No supporting evidence was found in indexed reports or extracted KPIs. The requested figures cannot be verified.'
    elif os.getenv('GROQ_API_KEY'):
        try:
            from groq import Groq
            pdf_context = '\n\n'.join(f"[P{i+1}] {e['citation']}: {e['text'][:1300]}" for i, e in enumerate(evidence))
            kpi_context = signal_context(signals)
            context = f"PDF EXCERPTS:\n{pdf_context or 'None'}\n\nVERIFIED STRUCTURED KPI ROWS:\n{kpi_context or 'None'}"
            response = Groq(api_key=os.getenv('GROQ_API_KEY')).chat.completions.create(
                model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b'), temperature=0,
                messages=[
                    {'role': 'system', 'content': (
                        'You are LedgerCapital, a precise, professional financial analyst. '
                        'Answer ONLY from supplied PDF excerpts and verified KPI rows. '
                        'Use [P1], [P2] for PDF evidence and [K1], [K2] for KPI evidence. '
                        'Every financial number must be supported by a citation. '
                        'Show calculations in plain text, cite each input, and verify arithmetic. '
                        'Distinguish reported values from calculated ratios. Never invent data, '
                        'years, sources, or investment recommendations. If evidence is insufficient, '
                        'say what cannot be verified. A FY2023 report with FY2022 comparisons '
                        'does not establish FY2021 figures. '
                        'Write natural, concise financial analysis: a direct answer, useful '
                        'comparisons, relevant trade-offs, and a balanced conclusion. '
                        'Avoid raw LaTeX, HTML, and overly long table cells. '
                        'Prefer paragraphs or bullets for simple answers. '
                        'When comparing multiple metrics, use valid GitHub-flavored Markdown '
                        'tables with a REAL newline after EVERY row. Never put the whole '
                        'table on one line. Never use "| |" between rows. '
                        'Example of the required layout:\n'
                        '| Metric | Company A | Company B |\n'
                        '|---|---:|---:|\n'
                        '| Revenue | $1,250 million | $1,460 million |\n'
                        '| Net income | $168 million | $255 million |\n'
                        'Do not infer liquidity solely from cash, or leverage solely from '
                        'absolute debt. Use only evidence-grounded conclusions. '
                        'Separate directly reported facts from arithmetic-derived metrics '
                        'and from hypotheses. Do not assert a causal explanation for a '
                        'margin difference unless the evidence explicitly establishes it. '
                        'Use language such as "the filings do not establish why" when '
                        'the cause is unknown. Do not cite a source that does not actually '
                        'support the nearby claim. If PDF and KPI figures conflict, '
                        'acknowledge the discrepancy rather than silently selecting one. '
                        'For ratios, identify the numerator and denominator and verify '
                        'the computation. Never present a hypothesis as a verified finding.'
                    )},
                    {'role': 'user', 'content': f'Question: {q}\n\n{context}'},
                ])
            answer = normalize_financial_markdown(
                response.choices[0].message.content or 'No answer returned.'
            )
        except Exception:
            app.logger.exception('Groq generation failed')
            return jsonify(error='LLM unavailable; evidence remains available via /api/kb/search and /api/financial-kpis'), 503
    else:
        answer = ('GROQ_API_KEY is not configured. Verified financial records:\n' + signal_context(signals)
                  + '\n\nPDF excerpts:\n' + '\n\n'.join(f"[P{i+1}] {e['citation']}: {e['text'][:350]}" for i,e in enumerate(evidence)))

    try:
        from ledger_neo4j_graph import graph_counts
        neo4j_document_count = graph_counts()['documents']
    except Exception:
        neo4j_document_count = 0

    return jsonify(answer=answer, companies=companies, years=years, citations=citations,
                   sources=sources,
                   stats=dict(chromadb_chunks=len(evidence), neo4j_documents=neo4j_document_count,
                              duckdb_signals=len(signals),
                              latency_seconds=round(time.perf_counter() - request_started, 3)),
                   agents_called=['retriever'] + (['duckdb_kpi_retriever'] if signals else [])
                                 + (['synthesizer'] if (evidence or signals) and os.getenv('GROQ_API_KEY') else []),
                   visualizations=[], analysis=None,
                   planner_reasoning='Grounded PDF retrieval + structured DuckDB KPI lookup')


@app.get('/api/stats')
def stats():
    rows = docs()
    con = connection()
    try:
        count = con.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
    finally:
        con.close()
    try:
        vectors = vector_collection().count()
    except Exception:
        vectors = None
    from ledger_kpis import list_kpis
    con = connection()
    try:
        kpi_count = len(list_kpis(con))
    finally:
        con.close()
    return jsonify(companies=len(set(d['company'] for d in rows)), total_analyses=0,
                   duckdb={'documents':len(rows),'sections_metadata':count,'signals':kpi_count,'tables_metadata':0},
                   chromadb={COLLECTION:vectors}, neo4j={})


@app.post('/api/graph/sync')
def graph_sync():
    """Explicitly synchronize verified DuckDB records to Neo4j (never on GET)."""
    from ledger_kpis import list_kpis
    from ledger_neo4j_graph import document_rows, sync
    try:
        con = connection()
        try:
            documents = document_rows(con)
            kpis = list_kpis(con)
        finally:
            con.close()
        return jsonify(sync(documents, kpis))
    except (RuntimeError, ImportError, OSError) as exc:
        app.logger.warning('Neo4j sync unavailable: %s', exc)
        return jsonify(status='unavailable', error=str(exc)), 503
    except Exception:
        app.logger.exception('Neo4j sync failed')
        return jsonify(status='error', error='Neo4j sync failed; inspect backend logs'), 503


@app.post('/api/neo4j-graph')
@app.get('/api/neo4j-graph')
def graph():
    """Read Neo4j graph; compatible with the existing POST graph endpoint."""
    from ledger_neo4j_graph import graph_data
    payload = request.get_json(silent=True) if request.method == 'POST' else request.args
    payload = payload or {}
    try:
        return jsonify(graph_data(payload.get('company'), payload.get('limit', 250)))
    except (ValueError, TypeError):
        return jsonify(error='limit must be an integer'), 400
    except (RuntimeError, ImportError, OSError) as exc:
        app.logger.warning('Neo4j graph unavailable: %s', exc)
        return jsonify(status='unavailable', nodes=[], edges=[], error=str(exc)), 503
    except Exception:
        app.logger.exception('Neo4j graph query failed')
        return jsonify(status='error', nodes=[], edges=[], error='Neo4j graph query failed; inspect backend logs'), 503


@app.get('/api/graph/status')
def graph_status():
    from ledger_neo4j_graph import graph_counts
    try:
        return jsonify(status='connected', **graph_counts())
    except (RuntimeError, ImportError, OSError) as exc:
        return jsonify(status='unavailable', error=str(exc)), 503
    except Exception:
        app.logger.exception('Neo4j status failed')
        return jsonify(status='unavailable', error='Neo4j connection failed; inspect backend logs'), 503


@app.get('/api/graph/companies')
def graph_companies():
    return jsonify([dict(company=c,docs=sum(d['company']==c for d in docs())) for c in sorted({d['company'] for d in docs()})])


@app.get('/api/outliers/company')
@app.get('/api/outliers/year')
def outliers():
    return jsonify(status='not_computed', results=[], message='No verified financial outlier analysis has been computed.')


# ------------------------------------------------------------
# AdminPanel-compatible document analysis and inventory report
# ------------------------------------------------------------
@app.post('/api/documents/analysis')
def document_analysis():
    payload = request.get_json(silent=True) or {}
    filename = str(payload.get('filename') or '').strip()
    doc_id = str(payload.get('doc_id') or '').strip()
    if not filename and not doc_id:
        return jsonify(error='filename or doc_id is required'), 400

    con = None
    try:
        con = connection()
        if doc_id:
            row = con.execute('''SELECT doc_id,filename,company,fiscal_year,pages,status
                                 FROM documents WHERE doc_id=?''', [doc_id]).fetchone()
        else:
            row = con.execute('''SELECT doc_id,filename,company,fiscal_year,pages,status
                                 FROM documents WHERE filename=?
                                 ORDER BY created_at DESC LIMIT 1''', [filename]).fetchone()
        if row is None:
            return jsonify(error='Document is not indexed'), 404
        did, name, company, year, pages, status = row
        evidence = con.execute('''SELECT page,section,content FROM evidence
                                  WHERE doc_id=? ORDER BY page,chunk_id''', [did]).fetchall()
        if not evidence:
            return jsonify(error='No indexed text exists for this document'), 404
        section_counts = {}
        for page, section, content in evidence:
            key = section or 'general'
            section_counts[key] = section_counts.get(key, 0) + 1
        lines = [
            'LEDGERCAPITAL — INDEXED DOCUMENT ANALYSIS',
            '=' * 55,
            f'Filename: {name}', f'Document ID: {did}',
            f'Company: {company or "Unknown"}',
            f'Fiscal year: {year if year is not None else "Unknown"}',
            f'PDF pages: {pages}', f'Indexing status: {status}',
            f'Indexed text chunks: {len(evidence)}',
            '', 'DETECTED SECTIONS', '-' * 55,
        ]
        lines.extend(f'{section}: {count} chunks'
                     for section, count in sorted(section_counts.items()))
        lines.extend(['', 'EXTRACTED TEXT PREVIEW', '-' * 55])
        for page, section, content in evidence[:8]:
            lines.extend(['', f'Page {page} | {section or "general"}', (content or '')[:650]])
        lines.extend(['', 'This is a text-index summary, not an audited KPI analysis.'])
        return jsonify(status='success', filename=name, doc_id=did,
                       company=company, year=year, pages=pages,
                       total_chunks=len(evidence), section_counts=section_counts,
                       analysis='\n'.join(lines))
    except Exception:
        app.logger.exception('Document analysis failed')
        return jsonify(error='Document analysis failed; inspect backend logs'), 500
    finally:
        if con is not None:
            con.close()


@app.post('/api/documents/report')
def parsed_data_report():
    con = None
    try:
        con = connection()
        rows = con.execute('''SELECT d.doc_id,d.filename,d.company,d.fiscal_year,
                                     d.pages,d.status,COUNT(e.chunk_id) AS chunks
                              FROM documents d LEFT JOIN evidence e ON d.doc_id=e.doc_id
                              GROUP BY d.doc_id,d.filename,d.company,d.fiscal_year,
                                       d.pages,d.status,d.created_at
                              ORDER BY d.created_at DESC''').fetchall()
        lines = [
            'LEDGERCAPITAL — INDEXED DOCUMENT INVENTORY',
            '=' * 55,
            f'Generated UTC: {datetime.now(timezone.utc).isoformat()}',
            f'Indexed documents: {len(rows)}',
            f'Total indexed text chunks: {sum(r[6] for r in rows)}',
        ]
        if not rows:
            lines.append('No indexed documents available.')
        for index, (did, name, company, year, pages, status, chunks) in enumerate(rows, 1):
            lines.extend(['', f'DOCUMENT {index}', '-' * 45,
                          f'Filename: {name}', f'Document ID: {did}',
                          f'Company: {company or "Unknown"}',
                          f'Fiscal year: {year if year is not None else "Unknown"}',
                          f'Pages: {pages}', f'Status: {status}',
                          f'Indexed text chunks: {chunks}'])
            sections = con.execute('''SELECT section,COUNT(*) FROM evidence
                                      WHERE doc_id=? GROUP BY section ORDER BY section''',
                                   [did]).fetchall()
            for section, count in sections:
                lines.append(f'  Section {section or "general"}: {count} chunks')
        lines.extend(['', 'This report lists indexed text, not verified financial KPIs.'])
        return jsonify(status='success', document_count=len(rows),
                       total_chunks=sum(r[6] for r in rows), report='\n'.join(lines))
    except Exception:
        app.logger.exception('Document report failed')
        return jsonify(error='Document report failed; inspect backend logs'), 500
    finally:
        if con is not None:
            con.close()


# Structured KPI extraction from the original uploaded PDF (not from LLM guesses).
@app.post('/api/financial-kpis/extract')
def extract_financial_kpis():
    from ledger_kpis import extract_pdf_kpis, save_kpis
    payload = request.get_json(silent=True) or {}
    doc_id = str(payload.get('doc_id') or '').strip()
    if not doc_id:
        return jsonify(error='doc_id is required'), 400
    con = connection()
    try:
        row = con.execute('SELECT filename,company FROM documents WHERE doc_id=?', [doc_id]).fetchone()
        if row is None:
            return jsonify(error='Indexed document not found'), 404
        filename, company = row
        matches = sorted((p for p in UPLOAD.glob('*') if p.is_file() and
                          p.name.endswith('_' + filename) and
                          hashlib.sha256(p.read_bytes()).hexdigest()[:24] == doc_id),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            return jsonify(error='Original uploaded PDF not found'), 404
        items = extract_pdf_kpis(matches[0], doc_id, company)
        save_kpis(con, doc_id, items)
        return jsonify(status='success', doc_id=doc_id, count=len(items), kpis=items,
                       note='Only explicitly labelled two-year USD-million tables are extracted. Other formats are skipped.')
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    except Exception:
        app.logger.exception('KPI extraction failed')
        return jsonify(error='KPI extraction failed; inspect backend logs'), 500
    finally:
        con.close()


@app.get('/api/financial-kpis')
def financial_kpis():
    from ledger_kpis import list_kpis
    con = connection()
    try:
        items = list_kpis(con, request.args.get('doc_id'))
        return jsonify(count=len(items), kpis=items)
    finally:
        con.close()


@app.get('/api/financial-kpis/compare')
def financial_kpi_compare():
    from ledger_kpis import list_kpis
    company = (request.args.get('company') or '').strip().upper()
    metric = (request.args.get('metric') or 'revenue').strip()
    try:
        year = int(request.args.get('year', '0'))
    except ValueError:
        return jsonify(error='year must be an integer'), 400
    if not company or not 1991 <= year <= 2100:
        return jsonify(error='company and valid year are required'), 400
    con = connection()
    try:
        rows = [r for r in list_kpis(con) if r['company']==company and r['metric']==metric
                and r['fiscal_year'] in (year,year-1)]
        grouped = {}
        for r in rows:
            grouped.setdefault(r['fiscal_year'], []).append(r)
        if any(len(grouped.get(y, [])) != 1 for y in (year, year-1)):
            return jsonify(error='Exactly one unambiguous value per year is required',
                           matches={str(k):len(v) for k,v in grouped.items()}), 422
        current, previous = grouped[year][0], grouped[year-1][0]
        if (current['currency'],current['unit']) != (previous['currency'],previous['unit']):
            return jsonify(error='Incompatible units'), 422
        if previous['value'] == 0:
            return jsonify(error='Cannot calculate growth with zero prior-year value'), 422
        pct = (current['value'] - previous['value']) / abs(previous['value']) * 100
        return jsonify(company=company,metric=metric,year=year,previous_year=year-1,
                       current=current,previous=previous,growth_percent=round(pct,4),
                       note='Source citations are stored with each KPI.')
    finally:
        con.close()


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='PDF exceeds 30 MB limit'), 413


# Feature 7: register independent multi-document comparison endpoints.
from feature7_routes import register_comparison_routes
register_comparison_routes(app, connection)


# Feature 9: read saved RAG evaluation results for the React dashboard.
from evals.feature9_routes import register_feature9_routes
register_feature9_routes(app)

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=int(os.getenv('PORT','5001')),debug=False)
