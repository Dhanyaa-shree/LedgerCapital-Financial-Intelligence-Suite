"""Evidence-grounded retrieval of already-extracted DuckDB financial KPIs.

No extraction, inference, or writes occur in this module.
"""
from __future__ import annotations
import re

METRIC_TERMS = {
    'revenue': (r'\brevenue\b', r'\bsales\b', r'\bturnover\b'),
    'cost_of_revenue': (r'\bcost of (?:goods sold|revenue|sales)\b', r'\bcogs\b'),
    'gross_profit': (r'\bgross profit\b',),
    'operating_expenses': (r'\boperating expenses?\b', r'\bopex\b'),
    'operating_income': (r'\boperating (?:income|profit)\b',),
    'net_income': (r'\bnet (?:income|profit|earnings)\b',),
    'total_assets': (r'\b(?:total )?assets\b',),
    'total_liabilities': (r'\b(?:total )?liabilities\b',),
    'total_equity': (r'\b(?:total )?(?:equity|shareholders.? equity)\b',),
    'cash_and_equivalents': (r'\bcash (?:and|&) (?:cash )?equivalents\b',),
    'total_debt': (r'\b(?:total )?debt\b',),
    'cloud_platforms_revenue': (r'\bcloud platforms?\b',),
    'enterprise_solutions_revenue': (r'\benterprise solutions?\b',),
}


def select_signals(question, rows, companies=(), years=(), limit=20):
    """Filter KPI rows to metrics, company, and years named by the user.

    A growth question with one year also includes the preceding year, but only
    for the same metric/company. Never fills missing data with guessed values.
    """
    q = question.lower()
    metrics = {name for name, terms in METRIC_TERMS.items()
               if any(re.search(term, q) for term in terms)}
    # A segment question should not silently include consolidated revenue.
    if 'cloud_platforms_revenue' in metrics or 'enterprise_solutions_revenue' in metrics:
        metrics.discard('revenue')
    if not metrics:
        return []
    company_set = {str(c).upper() for c in companies}
    years_set = {int(y) for y in years}
    growth = bool(re.search(r'\b(growth|grew|change|increas\w*|decreas\w*|year.over.year|yoy)\b', q))
    if growth and len(years_set) == 1:
        y = next(iter(years_set))
        years_set.add(y - 1)
    chosen = [r for r in rows
              if r['metric'] in metrics
              and (not company_set or r['company'].upper() in company_set)
              and (not years_set or int(r['fiscal_year']) in years_set)]
    # Prevent ambiguous multi-company responses when no company was named.
    if not company_set and len({r['company'] for r in chosen}) > 1:
        return []
    return sorted(chosen, key=lambda r: (r['company'], r['metric'], -r['fiscal_year']))[:limit]


def signal_context(rows):
    lines = []
    for i, r in enumerate(rows, 1):
        lines.append(f"[K{i}] {r['company']} FY{r['fiscal_year']} "
                     f"{r['metric']} = {r['value']:g} {r['currency']} {r['unit']}; "
                     f"source: page {r['page']}, label '{r['source_label']}', document {r['doc_id']}")
    return '\n'.join(lines)


def signal_sources(rows):
    return [dict(text=f"{r['source_label']}: {r['value']:g} {r['currency']} {r['unit']}",
                 citation=f"{r['company']} {r['fiscal_year']}, page {r['page']} (KPI)",
                 page=r['page'], company=r['company'], year=r['fiscal_year'],
                 doc_id=r['doc_id'], metric=r['metric'], value=r['value'],
                 currency=r['currency'], unit=r['unit'], source_type='duckdb_kpi')
            for r in rows]
