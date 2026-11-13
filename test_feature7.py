"""Run: python -m unittest test_feature7.py"""
import unittest
import duckdb
from ledger_kpis import ensure_table, save_kpis
from ledger_comparison import compare, available_documents

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.con.execute('CREATE TABLE documents(doc_id VARCHAR, filename VARCHAR, company VARCHAR, fiscal_year INTEGER, pages INTEGER, status VARCHAR, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        self.con.executemany('INSERT INTO documents(doc_id,filename,company,fiscal_year,pages,status) VALUES (?,?,?,?,?,?)', [('a','A_2023.pdf','A',2023,2,'indexed'),('b','B_2023.pdf','B',2023,2,'indexed')])
        ensure_table(self.con)
        def k(doc,company,metric,value,unit='million'):
            return dict(doc_id=doc, company=company, fiscal_year=2023, metric=metric, value=value, currency='USD', unit=unit, page=2, source_label=metric)
        save_kpis(self.con,'a',[k('a','A','revenue',100),k('a','A','net_income',0),k('a','A','total_assets',200)])
        save_kpis(self.con,'b',[k('b','B','revenue',125),k('b','B','net_income',5),k('b','B','total_assets',220,'thousand'),k('b','B','total_debt',50)])
    def tearDown(self): self.con.close()
    def test_comparison(self):
        result=compare(self.con,'a','b',2023,2023)
        rows={m['metric']:m for m in result['metrics']}
        self.assertEqual(rows['revenue']['difference'],25)
        self.assertEqual(rows['revenue']['change_percent'],25)
        self.assertIsNone(rows['net_income']['change_percent'])
        self.assertEqual(rows['total_assets']['status'],'incompatible_units')
        self.assertEqual(rows['total_debt']['status'],'missing_left')
        self.assertEqual(result['comparable_count'],2)
    def test_requires_two_documents(self):
        with self.assertRaises(ValueError): compare(self.con,'a','a',2023,2023)
    def test_requires_existing_year(self):
        with self.assertRaises(ValueError): compare(self.con,'a','b',2022,2023)
    def test_documents(self): self.assertEqual(len(available_documents(self.con)),2)

if __name__ == '__main__': unittest.main()
