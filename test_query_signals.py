import unittest
from ledger_query_signals import select_signals, signal_context, signal_sources

ROWS = [
    dict(doc_id='abc',company='ASTERION',fiscal_year=y,metric=m,value=v,currency='USD',unit='million',page=2,source_label='Total revenue' if m=='revenue' else 'Net income')
    for m, vals in [('revenue', [(2023,1250.0),(2022,1000.0)]),('net_income',[(2023,168.0),(2022,104.0)])]
    for y,v in vals
]
class Tests(unittest.TestCase):
    def test_revenue(self):
        r=select_signals('Asterion revenue in 2023',ROWS,['ASTERION'],[2023]); self.assertEqual(len(r),1); self.assertEqual(r[0]['value'],1250)
    def test_growth_uses_prior_year(self):
        r=select_signals('Asterion revenue growth in 2023',ROWS,['ASTERION'],[2023]); self.assertEqual({x['fiscal_year'] for x in r},{2022,2023})
    def test_missing_year(self):
        self.assertEqual(select_signals('Asterion revenue 2021',ROWS,['ASTERION'],[2021]),[])
    def test_no_unrelated_metrics(self):
        self.assertEqual(len(select_signals('Asterion net income 2023',ROWS,['ASTERION'],[2023])),1)
    def test_company_scope(self):
        self.assertEqual(select_signals('Other revenue 2023',ROWS,['OTHER'],[2023]),[])
    def test_provenance(self):
        r=select_signals('revenue 2023',ROWS,['ASTERION'],[2023]); self.assertIn('page 2',signal_context(r)); self.assertEqual(signal_sources(r)[0]['source_type'],'duckdb_kpi')
if __name__=='__main__': unittest.main()
