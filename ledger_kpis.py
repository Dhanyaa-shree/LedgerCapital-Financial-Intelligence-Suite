"""Conservative PDF KPI extraction for labelled 2- or 3-year financial tables.

Supports the LedgerCapital synthetic sample reports. Does not infer missing data
from prose or guess currency units. Table rows must be label then N values.
"""
from __future__ import annotations

import re

METRICS = {
    'total revenue': 'revenue', 'revenue': 'revenue',
    'cost of revenue': 'cost_of_revenue',
    'gross profit': 'gross_profit',
    'operating expenses': 'operating_expenses',
    'operating income': 'operating_income',
    'net income': 'net_income',
    'total assets': 'total_assets',
    'total liabilities': 'total_liabilities',
    'total equity': 'total_equity',
    'cash and equivalents': 'cash_and_equivalents',
    'total debt': 'total_debt',
    'operating cash flow': 'operating_cash_flow',
    'operating margin': 'operating_margin',
}
SEGMENTS = {
    'cloud platforms': 'cloud_platforms_revenue',
    'enterprise solutions': 'enterprise_solutions_revenue',
}
YEAR = re.compile(r'^FY\s*(20\d{2})$', re.I)
NUMBER = re.compile(r'^\(?\s*\$?\s*(-?[\d,]+(?:\.\d+)?)\s*\)?$')
PERCENT = re.compile(r'^(-?[\d,]+(?:\.\d+)?)\s*%$')
UNIT = re.compile(r'\b(?:USD\s+millions?|USD\s+in\s+millions?)\b', re.I)


def ensure_table(con):
    con.execute('''CREATE TABLE IF NOT EXISTS financial_kpis (
        doc_id VARCHAR NOT NULL, company VARCHAR NOT NULL,
        fiscal_year INTEGER NOT NULL, metric VARCHAR NOT NULL,
        value DOUBLE NOT NULL, currency VARCHAR NOT NULL,
        unit VARCHAR NOT NULL, page INTEGER NOT NULL,
        source_label VARCHAR NOT NULL,
        PRIMARY KEY (doc_id, fiscal_year, metric)
    )''')


def parse_number(s):
    s = s.strip()
    match = NUMBER.fullmatch(s)
    if not match:
        return None
    val = float(match.group(1).replace(',', ''))
    return -abs(val) if s.startswith('(') else val


def _parse_value(text, metric):
    if metric == 'operating_margin':
        match = PERCENT.fullmatch(text.strip())
        return float(match.group(1).replace(',', '')) if match else None
    return parse_number(text)


def _year_header(lines, start):
    """Read a consecutive FY-year header of length 2 or 3."""
    years = []
    for line in lines[start:start + 3]:
        match = YEAR.fullmatch(line)
        if not match:
            break
        years.append(int(match.group(1)))
    if len(years) in (2, 3) and len(set(years)) == len(years):
        return tuple(years)
    return None


def extract_pdf_kpis(pdf_path, doc_id, company):
    import pymupdf

    results = []
    with pymupdf.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf, 1):
            text = page.get_text('text') or ''
            # Do not infer units from a different page.
            if not UNIT.search(text):
                continue
            lines = [s.strip() for s in text.splitlines() if s.strip()]
            years = None
            section = 'consolidated'
            i = 0
            while i < len(lines):
                label = lines[i].casefold()
                if label == 'segment revenue':
                    section, years = 'segments', None
                    i += 1
                    continue

                header = _year_header(lines, i)
                if header:
                    years = header
                    i += len(header)
                    continue

                mapping = SEGMENTS if section == 'segments' else METRICS
                metric = mapping.get(label)
                if metric is not None and years is not None:
                    value_lines = lines[i + 1:i + 1 + len(years)]
                    if len(value_lines) == len(years):
                        values = [_parse_value(s, metric) for s in value_lines]
                        if all(v is not None for v in values):
                            for year, val in zip(years, values):
                                results.append({
                                    'doc_id': doc_id, 'company': company,
                                    'fiscal_year': year, 'metric': metric,
                                    'value': val, 'currency': 'USD',
                                    'unit': 'percent' if metric == 'operating_margin' else 'million',
                                    'page': page_no, 'source_label': lines[i],
                                })
                            i += 1 + len(years)
                            continue
                i += 1

    unique = {}
    for item in results:
        key = (item['fiscal_year'], item['metric'])
        if key in unique and unique[key]['value'] != item['value']:
            raise ValueError(f'Conflicting values for {key} in PDF')
        unique[key] = item
    return list(unique.values())


def save_kpis(con, doc_id, rows):
    ensure_table(con)
    con.execute('BEGIN TRANSACTION')
    try:
        con.execute('DELETE FROM financial_kpis WHERE doc_id = ?', [doc_id])
        for r in rows:
            con.execute('''INSERT INTO financial_kpis
                (doc_id,company,fiscal_year,metric,value,currency,unit,page,source_label)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                [r[k] for k in ('doc_id','company','fiscal_year','metric','value',
                                'currency','unit','page','source_label')])
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise


def list_kpis(con, doc_id=None):
    ensure_table(con)
    sql = '''SELECT doc_id,company,fiscal_year,metric,value,currency,unit,page,source_label
             FROM financial_kpis'''
    args = []
    if doc_id:
        sql += ' WHERE doc_id = ?'
        args.append(doc_id)
    sql += ' ORDER BY company,fiscal_year DESC,metric'
    keys = ('doc_id','company','fiscal_year','metric','value','currency','unit','page','source_label')
    return [dict(zip(keys, row)) for row in con.execute(sql, args).fetchall()]
