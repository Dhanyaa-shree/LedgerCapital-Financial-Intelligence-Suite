"""LedgerCapital evaluation runner, stdlib-only (no torch/pandas).
Uses extracted KPI records as *silver-reference* test cases, not independent gold labels.
Run with the verified Flask server on port 5001.
"""
from __future__ import annotations
import json, math, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'evals' / 'results'
RESULTS.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get('LEDGERCAPITAL_API', 'http://127.0.0.1:5001/api').rstrip('/')
METRICS = ('recall_at_k', 'precision_at_k', 'mrr', 'ndcg', 'context_recall', 'context_precision', 'context_relevance', 'faithfulness', 'answer_relevancy', 'answer_correctness', 'semantic_similarity')


def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(BASE + path, data=data, headers={'Content-Type': 'application/json'} if data is not None else {}, method='POST' if data is not None else 'GET')
    with urlopen(req, timeout=90) as resp:
        return json.load(resp)


def token_set(s):
    return set(re.findall(r'[a-z]{4,}', str(s).lower())) - {'what', 'were', 'from', 'with', 'that', 'this', 'year', 'company', 'value', 'fiscal'}


def score_case(case):
    start = time.perf_counter()
    query = case['query']
    try:
        response = api('/query', {'query': query})
        sources = response.get('sources', [])
        if not isinstance(sources, list): sources = []
        ids = [str(s.get('doc_id')) for s in sources if isinstance(s, dict) and s.get('doc_id')]
        unique_ids = list(dict.fromkeys(ids))
        expected = str(case['doc_id'])
        hits = [i for i, x in enumerate(unique_ids) if x == expected]
        recall = 1.0 if hits else 0.0
        precision = sum(x == expected for x in unique_ids) / len(unique_ids) if unique_ids else 0.0
        mrr = 1 / (hits[0] + 1) if hits else 0.0
        ndcg = (1 / math.log2(hits[0] + 2)) if hits else 0.0
        chunks = [str(s.get('text', '')) for s in sources if isinstance(s, dict) and s.get('text')]
        qwords = token_set(query)
        context_precision = sum(bool(token_set(t) & qwords) for t in chunks) / len(chunks) if chunks else 0.0
        answer = str(response.get('answer') or '')
        # Check an explicitly expected numeric KPI, with its magnitude and currency unit.
        # Not a general-purpose financial fact checker; other numbers in the answer may match.
        expected_value = float(case['expected_value'])
        nums = [float(n.replace(',', '')) for n in re.findall(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?', answer)]
        # Accept numbers in millions or equivalent billions (for USD million records).
        candidates = [expected_value]
        if case.get('unit', '').lower() == 'million': candidates.append(expected_value / 1000)
        correct = 1.0 if any(abs(n-v) <= max(abs(v)*0.01, 0.005) for v in candidates for n in nums) else 0.0
        # No embedding model / LLM judge is run here. Do not fabricate semantic or faithfulness scores.
        layers = {
            'layer1_retrieval': {'recall_at_k': recall, 'precision_at_k': precision, 'mrr': mrr, 'ndcg': ndcg},
            'layer2_context': {'context_recall': None, 'context_precision': context_precision, 'context_relevance': None},
            'layer3_generation': {'faithfulness': None, 'answer_relevancy': None, 'answer_correctness': correct, 'semantic_similarity': None},
        }
        values = [v for layer in layers.values() for v in layer.values() if isinstance(v, (int,float))]
        return {'ground_truth_id': case['id'], 'query': query, 'category': 'kpi_factual', 'status': 'completed',
                'expected': {'metric': case['metric'], 'value': expected_value, 'unit': case.get('unit'), 'doc_id': expected},
                'answer': answer, 'source_count': len(sources), 'evaluation': {**layers, 'overall_score': round(sum(values)/len(values),3) if values else None,
                'diagnosis': 'numeric_match' if correct else 'numeric_mismatch', 'latency': round(time.perf_counter()-start,3)}}
    except Exception as exc:
        return {'ground_truth_id': case['id'], 'query': query, 'category': 'kpi_factual', 'status': 'error', 'error': str(exc), 'evaluation': None}


def make_cases():
    data = api('/financial-kpis')
    rows = data.get('kpis', [])
    # Only unambiguous records. Limit to 20 to avoid unnecessary API calls.
    groups = {}
    for row in rows:
        try:
            key = (str(row['company']), int(row['fiscal_year']), str(row['metric']))
            if row.get('doc_id') and isinstance(row.get('value'), (float,int)):
                groups.setdefault(key, []).append(row)
        except (KeyError, TypeError, ValueError): continue
    cases = []
    for (company, year, metric), matches in sorted(groups.items()):
        if len(matches) != 1: continue
        row = matches[0]
        cases.append({'id': f'kpi_{len(cases)+1:03}', 'query': f'What was {company} {metric.replace("_", " ")} in {year}? Cite the source.',
                      'doc_id': row['doc_id'], 'metric': metric, 'expected_value': row['value'], 'unit': row.get('unit','')})
        if len(cases) >= 20: break
    return cases


def main():
    try: cases = make_cases()
    except (URLError, HTTPError, OSError) as exc:
        print(f'Cannot connect to verified_server.py at {BASE}: {exc}', file=sys.stderr)
        return 1
    if not cases:
        print('No unambiguous extracted KPIs found. Index PDFs and extract financial KPIs first.')
        return 1
    print(f'Evaluating {len(cases)} silver-reference KPI questions (not independent ground truth).')
    results = []
    for i, case in enumerate(cases, 1):
        item = score_case(case)
        results.append(item)
        print(f'[{i}/{len(cases)}] {item["status"]}: {case["query"]}')
    completed = [r for r in results if r['status'] == 'completed']
    averages = {}
    for metric in METRICS:
        vals = [v for r in completed for layer in ('layer1_retrieval','layer2_context','layer3_generation')
                if isinstance((v := r['evaluation'][layer].get(metric)), (int,float))]
        averages[metric] = round(sum(vals)/len(vals),3) if vals else None
    overall = [r['evaluation']['overall_score'] for r in completed if r['evaluation']['overall_score'] is not None]
    stats = {'total_evaluations': len(completed), 'total_cases': len(results), 'failed_cases': len(results)-len(completed),
             'average_overall': round(sum(overall)/len(overall),3) if overall else None,
             'average_metrics': averages, 'diagnoses': {}, 'by_category': {'kpi_factual': {'total': len(completed), 'avg_score': round(sum(overall)/len(overall),3) if overall else None}}}
    for r in completed:
        d = r['evaluation']['diagnosis']; stats['diagnoses'][d] = stats['diagnoses'].get(d,0)+1
    output = {'timestamp': datetime.now(timezone.utc).isoformat(), 'method': 'silver_reference_kpi',
              'note': 'Reference values come from extracted KPIs; not independently audited. Overall score averages available proxy metrics only. Null metrics were not measured.',
              'statistics': stats, 'results': results}
    dest = RESULTS / ('eval_results_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
    dest.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Saved: {dest}\nCompleted: {len(completed)}  Failed: {stats["failed_cases"]}')
    return 0 if completed else 1

if __name__ == '__main__': sys.exit(main())
