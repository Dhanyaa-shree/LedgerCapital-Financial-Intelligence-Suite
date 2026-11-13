"""Neo4j projection of verified LedgerCapital DuckDB data.

No LLM-created graph facts. All nodes are derived from indexed documents and
structured KPIs. Graph is a read-optimized projection; DuckDB is authoritative.
"""
from __future__ import annotations
import os
from contextlib import contextmanager


def settings():
    uri = os.getenv('NEO4J_URI', '').strip()
    user = os.getenv('NEO4J_USERNAME', os.getenv('NEO4J_USER', '')).strip()
    password = os.getenv('NEO4J_PASSWORD', '')
    database = os.getenv('NEO4J_DATABASE', 'neo4j').strip() or 'neo4j'
    if not all((uri, user, password)):
        raise RuntimeError('Set NEO4J_URI, NEO4J_USERNAME (or NEO4J_USER), and NEO4J_PASSWORD in .env')
    if not uri.startswith(('neo4j://', 'neo4j+s://', 'neo4j+ssc://', 'bolt://', 'bolt+s://', 'bolt+ssc://')):
        raise RuntimeError('NEO4J_URI must be a Neo4j/Bolt URI')
    return uri, user, password, database


@contextmanager
def session():
    from neo4j import GraphDatabase
    uri, user, password, database = settings()
    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=8, max_connection_pool_size=5)
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as s:
            yield s
    finally:
        driver.close()


def document_rows(con):
    rows = con.execute('SELECT doc_id,filename,company,fiscal_year,pages,status FROM documents ORDER BY doc_id').fetchall()
    return [dict(zip(('doc_id','filename','company','fiscal_year','pages','status'), r)) for r in rows]


def projection(documents, kpis):
    """Pure, testable normalization; skip orphaned KPI rows."""
    docs = [d for d in documents if d.get('doc_id') and d.get('company')]
    valid = {d['doc_id'] for d in docs}
    facts = [k for k in kpis if k.get('doc_id') in valid and k.get('fiscal_year') is not None
             and k.get('metric') and k.get('page') is not None]
    return docs, facts


def sync(documents, kpis):
    docs, facts = projection(documents, kpis)
    if not docs:
        return {'status':'success','documents':0,'kpis':0,'message':'No indexed documents to synchronize'}
    with session() as s:
        # Uniqueness constraints prevent duplicate nodes on repeated syncs.
        s.run('CREATE CONSTRAINT lc_company IF NOT EXISTS FOR (n:LCCompany) REQUIRE n.name IS UNIQUE').consume()
        s.run('CREATE CONSTRAINT lc_document IF NOT EXISTS FOR (n:LCDocument) REQUIRE n.doc_id IS UNIQUE').consume()
        s.run('CREATE CONSTRAINT lc_fact IF NOT EXISTS FOR (n:LCFinancialFact) REQUIRE n.key IS UNIQUE').consume()
        s.run('CREATE CONSTRAINT lc_year IF NOT EXISTS FOR (n:LCFiscalYear) REQUIRE n.key IS UNIQUE').consume()
        s.run('''UNWIND $docs AS d
            MERGE (c:LCCompany {name:d.company})
            MERGE (r:LCDocument {doc_id:d.doc_id})
            SET r.filename=d.filename, r.fiscal_year=d.fiscal_year,
                r.pages=d.pages, r.status=d.status, r.company=d.company
            MERGE (c)-[:HAS_REPORT]->(r)''', docs=docs).consume()
        if facts:
            s.run('''UNWIND $facts AS k
                MATCH (r:LCDocument {doc_id:k.doc_id})
                MERGE (y:LCFiscalYear {key:k.company + ':' + toString(k.fiscal_year)})
                SET y.company=k.company, y.year=k.fiscal_year
                MERGE (f:LCFinancialFact {key:k.doc_id + ':' + toString(k.fiscal_year) + ':' + k.metric})
                SET f.doc_id=k.doc_id, f.company=k.company, f.fiscal_year=k.fiscal_year,
                    f.metric=k.metric, f.value=k.value, f.currency=k.currency,
                    f.unit=k.unit, f.page=k.page, f.source_label=k.source_label
                MERGE (r)-[:REPORTS_FACT]->(f)
                MERGE (f)-[:FOR_YEAR]->(y)''', facts=facts).consume()
    return {'status':'success','documents':len(docs),'kpis':len(facts),
            'message':'Graph synchronized from indexed DuckDB documents and KPIs'}


def graph_data(company=None, limit=250):
    limit = min(max(int(limit), 1), 1000)
    company = (company or '').strip().upper() or None
    with session() as s:
        records = list(s.run('''MATCH (c:LCCompany)-[:HAS_REPORT]->(d:LCDocument)
            WHERE $company IS NULL OR c.name = $company
            OPTIONAL MATCH (d)-[:REPORTS_FACT]->(f:LCFinancialFact)
            WITH c,d,f ORDER BY d.doc_id, f.fiscal_year DESC, f.metric
            RETURN c.name AS company, d.doc_id AS doc_id, d.filename AS filename,
                   d.fiscal_year AS report_year, f.key AS fact_key,
                   f.metric AS metric, f.fiscal_year AS fiscal_year,
                   f.value AS value, f.currency AS currency, f.unit AS unit,
                   f.page AS page, f.source_label AS source_label
            LIMIT $limit''', company=company, limit=limit))
    nodes = {}
    edges = {}
    for rec in records:
        r = dict(rec)
        cid = 'company:' + r['company']; did = 'document:' + r['doc_id']
        nodes[cid] = {'id':cid,'label':r['company'],'type':'company'}
        nodes[did] = {'id':did,'label':r['filename'],'type':'document', 'doc_id':r['doc_id'], 'year':r['report_year']}
        edges[(cid,did,'HAS_REPORT')] = {'source':cid,'target':did,'type':'HAS_REPORT'}
        if r['fact_key']:
            fid = 'fact:' + r['fact_key']
            yid = 'year:' + r['company'] + ':' + str(r['fiscal_year'])
            nodes[fid] = {'id':fid,'label':r['metric'],'type':'financial_fact',
                          'value':r['value'],'currency':r['currency'],'unit':r['unit'],
                          'page':r['page'],'source_label':r['source_label'],
                          'doc_id':r['doc_id'],'fiscal_year':r['fiscal_year']}
            nodes[yid] = {'id':yid,'label':str(r['fiscal_year']),'type':'fiscal_year'}
            edges[(did,fid,'REPORTS_FACT')] = {'source':did,'target':fid,'type':'REPORTS_FACT'}
            edges[(fid,yid,'FOR_YEAR')] = {'source':fid,'target':yid,'type':'FOR_YEAR'}
    return {'status':'success','nodes':list(nodes.values()),'edges':list(edges.values()),
            'node_count':len(nodes),'edge_count':len(edges), 'company_filter':company,
            'limit':limit, 'note':'Graph contains verified DuckDB-derived data only; results may be limited'}


def graph_counts():
    with session() as s:
        row = s.run('''MATCH (d:LCDocument) WITH count(d) AS documents
            OPTIONAL MATCH (f:LCFinancialFact)
            RETURN documents, count(f) AS financial_facts''').single()
        return {'documents':row['documents'],'financial_facts':row['financial_facts']}
