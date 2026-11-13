"""Register Feature 7 routes on an existing Flask app without replacing older routes."""
import os
from flask import jsonify, request
from ledger_comparison import available_documents, compare, analysis


def register_comparison_routes(app, connection):
    @app.get('/api/comparison/documents')
    def comparison_documents():
        con = connection()
        try:
            return jsonify(status='success', documents=available_documents(con))
        finally:
            con.close()

    @app.post('/api/comparison/run')
    def comparison_run():
        payload = request.get_json(silent=True) or {}
        try:
            left_id = str(payload.get('left_doc_id') or '').strip()
            right_id = str(payload.get('right_doc_id') or '').strip()
            if not left_id or not right_id:
                return jsonify(error='left_doc_id and right_doc_id are required'), 400
            def parse_year(key):
                value = payload.get(key)
                if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
                    raise ValueError(f'{key} must be a valid integer')
                return int(value)
            left_year, right_year = parse_year('left_year'), parse_year('right_year')
            con = connection()
            try:
                result = compare(con, left_id, right_id, left_year, right_year)
            finally:
                con.close()
            return jsonify(result)
        except ValueError as exc:
            return jsonify(error=str(exc)), 422
        except Exception:
            app.logger.exception('Comparison failed')
            return jsonify(error='Comparison failed; inspect backend logs'), 500

    @app.post('/api/comparison/analyze')
    def comparison_analyze():
        payload = request.get_json(silent=True) or {}
        try:
            left_id = str(payload.get('left_doc_id') or '').strip()
            right_id = str(payload.get('right_doc_id') or '').strip()
            if not left_id or not right_id:
                return jsonify(error='Both document IDs are required'), 400
            years = (payload.get('left_year'), payload.get('right_year'))
            if any(isinstance(y, bool) or not isinstance(y, int) or not 1990 <= y <= 2100 for y in years):
                return jsonify(error='Both years must be integer values from 1990 to 2100'), 400
            con = connection()
            try:
                result = compare(con, left_id, right_id, years[0], years[1])
            finally:
                con.close()
            out = analysis(result, os.getenv('GROQ_API_KEY'), os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b'))
            return jsonify(**out)
        except ValueError as exc:
            return jsonify(error=str(exc)), 422
        except Exception:
            app.logger.exception('AI comparison unavailable')
            return jsonify(error='Groq comparison unavailable; numeric comparison remains available'), 503
