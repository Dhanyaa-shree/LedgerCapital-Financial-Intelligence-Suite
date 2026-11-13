import { useEffect, useMemo, useState } from 'react';
import { BarChart, Bar, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getComparisonDocuments, runComparison, analyzeComparison } from '../services/comparison';

type Document = { doc_id: string; filename: string; company: string; year: number | null; kpi_count: number };
type KPI = { doc_id: string; company: string; fiscal_year: number; metric: string; value: number; currency: string; unit: string; page: number };
type Metric = { metric: string; left: KPI | null; right: KPI | null; difference: number | null; change_percent: number | null; status: string };
type Comparison = { metrics: Metric[]; comparable_count: number; left_document: Document; right_document: Document; left_year: number; right_year: number; note: string };

const card: React.CSSProperties = { background: 'var(--panel, #12233c)', border: '1px solid var(--border, #30415c)', borderRadius: 14, padding: 22, marginBottom: 18 };
const control: React.CSSProperties = { width: '100%', background: 'var(--panel-strong, #172a45)', color: 'var(--text, #f1f5f9)', border: '1px solid var(--border, #40516a)', borderRadius: 8, padding: 10, marginTop: 6 };
const button: React.CSSProperties = { background: '#3478f6', color: 'white', border: 0, borderRadius: 8, padding: '11px 18px', cursor: 'pointer', fontWeight: 600 };
const nice = (v: number | null) => v === null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
const metricName = (v: string) => v.replace(/_/g, ' ').replace(/\b\w/g, x => x.toUpperCase());

export default function ComparisonDashboard() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [leftId, setLeftId] = useState(''); const [rightId, setRightId] = useState('');
  const [leftYear, setLeftYear] = useState(''); const [rightYear, setRightYear] = useState('');
  const [result, setResult] = useState<Comparison | null>(null);
  const [insights, setInsights] = useState(''); const [error, setError] = useState('');
  const [busy, setBusy] = useState(false); const [aiBusy, setAiBusy] = useState(false);
  useEffect(() => { getComparisonDocuments().then(r => {
    const docs: Document[] = r.data.documents || []; setDocuments(docs);
    if (docs.length) setLeftId(docs[0].doc_id);
    if (docs.length > 1) setRightId(docs[1].doc_id);
  }).catch(e => setError(e.response?.data?.error || e.message)); }, []);
  const [years, setYears] = useState<Record<string, number[]>>({});
  useEffect(() => { Promise.all(documents.filter(d => d.kpi_count > 0).map(async d => {
    // Years are derived from the verified KPI listing, not guessed from report filenames.
    const response = await fetch(`/api/financial-kpis?doc_id=${encodeURIComponent(d.doc_id)}`);
    if (!response.ok) return [d.doc_id, []] as const;
    const json = await response.json();
    return [d.doc_id, Array.from(new Set<number>((json.kpis || []).map((k: KPI) => k.fiscal_year))).sort((a,b) => b-a)] as const;
  })).then(entries => setYears(Object.fromEntries(entries))).catch(() => {}); }, [documents]);
  const leftYears = years[leftId] || []; const rightYears = years[rightId] || [];
  useEffect(() => { setLeftYear(leftYears.length ? String(leftYears[0]) : ''); }, [leftId, years]);
  useEffect(() => { setRightYear(rightYears.length ? String(rightYears[0]) : ''); }, [rightId, years]);
  const chartData = useMemo(() => (result?.metrics || []).filter(m => m.status === 'comparable').slice(0, 10).map(m => ({ metric: metricName(m.metric), Left: m.left?.value, Right: m.right?.value })), [result]);
  const selection = { left_doc_id: leftId, right_doc_id: rightId, left_year: Number(leftYear), right_year: Number(rightYear) };
  async function compare() { setError(''); setResult(null); setInsights(''); setBusy(true);
    try { const r = await runComparison(selection); setResult(r.data); }
    catch (e: any) { setError(e.response?.data?.error || e.message); } finally { setBusy(false); }
  }
  async function analyze() { setAiBusy(true); setError('');
    try { const r = await analyzeComparison(selection); setInsights(r.data.analysis || 'No analysis available.'); }
    catch (e: any) { setError(e.response?.data?.error || e.message); } finally { setAiBusy(false); }
  }
  return <div style={{ padding: '30px 28px', color: 'var(--text, #f1f5f9)', maxWidth: 1300, margin: 'auto' }}>
    <h1 style={{ fontSize: 27, fontWeight: 750 }}>Financial Comparison</h1>
    <p style={{ color: 'var(--text-muted, #94a3b8)', marginBottom: 22 }}>Compare verified metrics from two different indexed PDF reports. Extract KPIs in Admin before comparing.</p>
    <section style={card}><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 18 }}>
      {([['Left report', leftId, setLeftId, leftYears, leftYear, setLeftYear], ['Right report', rightId, setRightId, rightYears, rightYear, setRightYear]] as const).map(([title, id, setId, yrs, year, setYear]) => <div key={title}>
        <label>{title}<select style={control} value={id} onChange={e => setId(e.target.value)}><option value="">Select report</option>{documents.filter(d => d.kpi_count > 0).map(d => <option key={d.doc_id} value={d.doc_id}>{d.company} — {d.filename}</option>)}</select></label>
        <label style={{ display: 'block', marginTop: 14 }}>Fiscal year<select style={control} value={year} onChange={e => setYear(e.target.value)}><option value="">Select year</option>{yrs.map(y => <option key={y} value={y}>{y}</option>)}</select></label>
      </div>)}
    </div><div style={{ marginTop: 20 }}><button style={button} disabled={busy || !leftId || !rightId || leftId === rightId || !leftYear || !rightYear} onClick={compare}>{busy ? 'Comparing…' : 'Compare financials'}</button></div></section>
    {documents.filter(d => d.kpi_count > 0).length < 2 && <p>At least two different indexed PDFs with extracted KPIs are required. Currently available: {documents.filter(d => d.kpi_count > 0).length}.</p>}
    {error && <p role="alert" style={{ color: '#fda4af', marginBottom: 18 }}>{error}</p>}
    {result && <><section style={card}><h2 style={{ fontSize: 19, marginBottom: 12 }}>Verified KPI comparison ({result.comparable_count} comparable)</h2>
      <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}><thead><tr>{['Metric', `${result.left_document.company} FY${result.left_year}`, `${result.right_document.company} FY${result.right_year}`, 'Right − left', '% difference', 'Status / source'].map(x => <th key={x} style={{ padding: 10, borderBottom: '1px solid var(--border, #30415c)' }}>{x}</th>)}</tr></thead>
      <tbody>{result.metrics.map(m => <tr key={m.metric}>{[metricName(m.metric), m.left ? `${nice(m.left.value)} ${m.left.currency} ${m.left.unit}` : '—', m.right ? `${nice(m.right.value)} ${m.right.currency} ${m.right.unit}` : '—', nice(m.difference), m.change_percent === null ? '—' : `${nice(m.change_percent)}%`, m.status].map((v,i) => <td key={i} style={{ padding: 10, borderBottom: '1px solid var(--border, #30415c)' }}>{v}{i===5 && <div style={{ fontSize: 11, opacity: .7 }}>{m.left && `Left p.${m.left.page}`}{m.right && ` · Right p.${m.right.page}`}</div>}</td>)}</tr>)}</tbody></table></div>
      <p style={{ fontSize: 12, opacity: .75, marginTop: 14 }}>{result.note}</p></section>
      {chartData.length > 0 && <section style={card}><h2 style={{ fontSize: 19 }}>Metric comparison</h2><p style={{ fontSize: 12, opacity: .75 }}>Only directly comparable values are plotted. Different metrics may have very different scales.</p><div style={{ height: 350 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 20, right: 20, left: 15, bottom: 65 }}><CartesianGrid strokeDasharray="3 3" opacity={0.2}/><XAxis dataKey="metric" angle={-30} textAnchor="end" interval={0} height={90} tick={{ fontSize: 11 }}/><YAxis/><Tooltip/><Legend/><Bar dataKey="Left" fill="#4F8EF7"/><Bar dataKey="Right" fill="#00C9A7"/></BarChart></ResponsiveContainer></div></section>}
      <section style={card}><h2 style={{ fontSize: 19, marginBottom: 12 }}>Evidence-grounded AI interpretation</h2><button style={button} disabled={aiBusy || !result.comparable_count} onClick={analyze}>{aiBusy ? 'Analyzing…' : 'Generate Groq analysis'}</button>{insights && <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, marginTop: 15 }}>{insights}</p>}</section>
    </>}
  </div>;
}
