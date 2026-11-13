import unittest
from pathlib import Path
import ast

SOURCE = Path(__file__).resolve().parents[1] / 'verified_server.py'

class VerifiedCoreStaticTests(unittest.TestCase):
    def test_valid_python(self):
        ast.parse(SOURCE.read_text(encoding='utf-8'))

    def test_required_endpoints_present(self):
        text = SOURCE.read_text(encoding='utf-8')
        for endpoint in ('/api/health','/api/documents/upload','/api/documents/implement-learning','/api/query','/api/kb/search','/api/stats'):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, text)

    def test_no_fabricated_default_companies(self):
        text = SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('fallback_companies', text)

if __name__ == '__main__':
    unittest.main()
