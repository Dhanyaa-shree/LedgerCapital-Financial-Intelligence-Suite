"""Evidence-only two-document KPI comparison. No inferred or fabricated values."""
from __future__ import annotations
import math


def available_documents(con):
    from ledger_kpis import list_kpis
    rows = con.execute('SELECT doc_id, filename, company, fiscal_year, pages, status FROM documents ORDER BY created_at DESC').fetchall()
    counts = {}
    for k in list_kpis(con):
        counts[k['doc_id']] = counts.get(k['doc_id'], 0) + 1
    return [dict(doc_id=r[0], filename=r[1], company=r[2], year=r[3], pages=r[4], status=r[5], kpi_count=counts.get(r[0], 0)) for r in rows]


def compare(con, left_doc_id, right_doc_id, left_year, right_year):
    from ledger_kpis import list_kpis
    docs = {d['doc_id']: d for d in available_documents(con)}
    if left_doc_id not in docs or right_doc_id not in docs:
        raise ValueError('Both document IDs must belong to indexed documents')
    if left_doc_id == right_doc_id:
        raise ValueError('Select two different documents for multi-document comparison')
    if not isinstance(left_year, int) or isinstance(left_year, bool) or not 1990 <= left_year <= 2100:
        raise ValueError('left_year must be an integer between 1990 and 2100')
    if not isinstance(right_year, int) or isinstance(right_year, bool) or not 1990 <= right_year <= 2100:
        raise ValueError('right_year must be an integer between 1990 and 2100')
    all_rows = list_kpis(con)
    def collect(doc_id, year):
        result = {}
        for k in all_rows:
            if k['doc_id'] == doc_id and k['fiscal_year'] == year:
                result.setdefault(k['metric'], []).append(k)
        return result
    left = collect(left_doc_id, left_year)
    right = collect(right_doc_id, right_year)
    if not left or not right:
        missing = []
        if not left: missing.append('left')
        if not right: missing.append('right')
        raise ValueError('No extracted KPIs for selected document/year: ' + ', '.join(missing) + '. Extract KPIs first or select a supported year.')
    output = []
    for metric in sorted(set(left) | set(right)):
        a, b = left.get(metric, []), right.get(metric, [])
        item = {'metric': metric, 'left': a[0] if len(a) == 1 else None,
                'right': b[0] if len(b) == 1 else None, 'difference': None,
                'change_percent': None, 'status': None}
        if len(a) > 1 or len(b) > 1:
            item['status'] = 'ambiguous'
        elif not a or not b:
            item['status'] = 'missing_left' if not a else 'missing_right'
        elif (a[0]['currency'], a[0]['unit']) != (b[0]['currency'], b[0]['unit']):
            item['status'] = 'incompatible_units'
        elif not all(math.isfinite(float(k['value'])) for k in (a[0], b[0])):
            item['status'] = 'invalid_value'
        else:
            item['status'] = 'comparable'
            # Right minus left, never a growth claim for different companies.
            item['difference'] = round(float(b[0]['value']) - float(a[0]['value']), 6)
            if float(a[0]['value']) != 0:
                item['change_percent'] = round(item['difference'] / abs(float(a[0]['value'])) * 100, 4)
        output.append(item)
    return {'status': 'success', 'left_document': docs[left_doc_id], 'right_document': docs[right_doc_id],
            'left_year': left_year, 'right_year': right_year, 'metrics': output,
            'comparable_count': sum(m['status'] == 'comparable' for m in output),
            'note': 'Difference = right minus left. Percent difference uses abs(left) as denominator. Cross-company differences are NOT growth rates. Values are DuckDB-extracted and cited to source PDF pages.'}


def analysis(result, groq_api_key, model):
    comparable = [m for m in result['metrics'] if m['status'] == 'comparable']
    if not comparable:
        return {'status': 'unavailable', 'analysis': 'No compatible, verified metrics available for AI analysis.'}
    if not groq_api_key:
        return {'status': 'unavailable', 'analysis': 'GROQ_API_KEY is not configured. Numeric comparison is still available.'}
    from groq import Groq
    context = []
    for i, m in enumerate(comparable, 1):
        a, b = m['left'], m['right']
        context.append(f"[M{i}] {m['metric']}: LEFT {a['value']} {a['currency']} {a['unit']} ({result['left_document']['filename']}, FY{result['left_year']}, p.{a['page']}); RIGHT {b['value']} {b['currency']} {b['unit']} ({result['right_document']['filename']}, FY{result['right_year']}, p.{b['page']}); right-minus-left={m['difference']}; percentage difference={m['change_percent']}")
    answer = Groq(api_key=groq_api_key).chat.completions.create(
        model=model, temperature=0,
        messages=[{'role': 'system', 'content': 'You compare verified financial KPIs. Use ONLY provided metrics. Cite [M1], [M2], etc. for every numeric claim. Do not invent values or reasons. A difference between different companies is NOT a growth rate. Distinguish fiscal years, currency and units. If the sources do not explain why a metric changed, do not invent a cause. Keep response concise.'},
                  {'role': 'user', 'content': 'Summarize the main differences in these verified records:\n' + '\n'.join(context)}]
    ).choices[0].message.content
    return {'status': 'success', 'analysis': answer or 'No text returned.', 'source_legend': [f"[M{i}] {m['metric']}: {m['left']['doc_id']} page {m['left']['page']}; {m['right']['doc_id']} page {m['right']['page']}" for i, m in enumerate(comparable, 1)]}
