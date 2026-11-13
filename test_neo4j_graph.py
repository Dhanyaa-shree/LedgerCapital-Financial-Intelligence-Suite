import unittest
from unittest.mock import patch
import ledger_neo4j_graph as g

DOC = {'doc_id':'doc1','filename':'report.pdf','company':'ASTERION','fiscal_year':2023,'pages':4,'status':'indexed'}
FACT = {'doc_id':'doc1','company':'ASTERION','fiscal_year':2023,'metric':'revenue','value':1250.0,'currency':'USD','unit':'million','page':2,'source_label':'Total revenue'}

class Tests(unittest.TestCase):
    def test_projection(self):
        docs, facts = g.projection([DOC],[FACT]); self.assertEqual((len(docs),len(facts)),(1,1))
    def test_orphan_is_skipped(self):
        docs, facts = g.projection([DOC],[{**FACT,'doc_id':'missing'}]); self.assertEqual(len(facts),0)
    def test_missing_provenance_is_skipped(self):
        _, facts = g.projection([DOC],[{**FACT,'page':None}]); self.assertEqual(facts,[])
    def test_settings_missing(self):
        with patch.dict('os.environ',{'NEO4J_URI':'','NEO4J_USERNAME':'','NEO4J_PASSWORD':''}):
            with self.assertRaises(RuntimeError): g.settings()
    def test_settings(self):
        with patch.dict('os.environ',{'NEO4J_URI':'neo4j+s://example.com','NEO4J_USERNAME':'neo4j','NEO4J_PASSWORD':'test','NEO4J_DATABASE':'neo4j'}):
            self.assertEqual(g.settings()[0],'neo4j+s://example.com')

if __name__=='__main__': unittest.main()
