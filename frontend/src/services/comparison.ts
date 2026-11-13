import API from './api';
export const getComparisonDocuments = () => API.get('/comparison/documents');
export const runComparison = (payload: { left_doc_id: string; right_doc_id: string; left_year: number; right_year: number }) => API.post('/comparison/run', payload);
export const analyzeComparison = (payload: { left_doc_id: string; right_doc_id: string; left_year: number; right_year: number }) => API.post('/comparison/analyze', payload);
