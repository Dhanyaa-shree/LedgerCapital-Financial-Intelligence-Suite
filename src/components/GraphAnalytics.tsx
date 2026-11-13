import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import API from '../services/api';
import NeoGraphViewer from './NeoGraphViewer';

type KPI = { company: string; fiscal_year: number; metric: string; value: number; currency: string; unit: string; page: number; doc_id: string };
type Props = { query: string; nodes: any[]; edges: any[]; loading?: boolean };
const formatMetric = (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const measures = ['revenue', 'gross_profit', 'operating_income', 'net_income'];

export default function GraphAnalytics({ query, nodes, edges, loading = false }: Props) {
  const [tab, setTab] = useState<'graph' | 'analytics'>('graph');
  const [rows, setRows] = useState<KPI[]>([]);
  const [error, setError] = useState('');
  const [company, setCompany] = useState('');
  const [year, setYear] = useState<number | null>(null);
  useEffect(() => {
    let active = true;
    API.get<{ kpis: KPI[] }>('/financial-kpis').then(({ data }) => {
      if (!active) return;
      const kpis = Array.isArray(data.kpis) ? data.kpis.filter(r => Number.isFinite(r.value)) : [];
      setRows(kpis);
      if (kpis.length) { setCompany(kpis[0].company); setYear(Math.max(...kpis.map(r => r.fiscal_year))); }
    }).catch(e => { if (active) setError(e.message || 'Unable to load financial KPIs'); });
    return () => { active = false; };
  }, []);
  const companies = useMemo(() => [...new Set(rows.map(r => r.company))].sort(), [rows]);
  const years = useMemo(() => [...new Set(rows.filter(r => r.company === company).map(r => r.fiscal_year))].sort((a,b) => b-a), [rows, company]);
  const selected = rows.filter(r => r.company === company && r.fiscal_year === year);
  const reference = selected.find(r => r.metric === 'revenue') || selected[0];
  const comparable = selected.filter(r => measures.includes(r.metric) && reference && r.currency === reference.currency && r.unit === reference.unit);
  const counts = new Map<string, number>();
  comparable.forEach(r => counts.set(r.metric, (counts.get(r.metric) || 0) + 1));
  const barData = comparable.filter(r => counts.get(r.metric) === 1).map(r => ({ name: formatMetric(r.metric), value: r.value, page: r.page }));
  const trendData = years.slice().reverse().map(y => {
    const values = rows.filter(r => r.company === company && r.fiscal_year === y && r.metric === 'revenue' && (!reference || (r.currency === reference.currency && r.unit === reference.unit)));
    return { year: String(y), revenue: values.length === 1 ? values[0].value : null };
  });
  const control = 'rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--text)]';
  return <div className="flex h-full flex-col bg-[var(--panel)] text-[var(--text)]">
    <div className="flex border-b border-[var(--border)]">
      <button className="flex-1 p-3" onClick={() => setTab('graph')} aria-pressed={tab === 'graph'}>Neo4j Graph</button>
      <button className="flex-1 p-3" onClick={() => setTab('analytics')} aria-pressed={tab === 'analytics'}>Financial Analytics</button>
    </div>
    <div className="min-h-0 flex-1 overflow-auto">
      {tab === 'graph' ? <NeoGraphViewer query={query} nodes={nodes} edges={edges} loading={loading}/> :
      <div className="space-y-5 p-4">
        <p className="text-sm text-[var(--text-muted)]">Verified financial values from extracted report KPIs. No synthetic scores or forecasts.</p>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        <div className="flex flex-wrap gap-3">
          <select className={control} aria-label="Company" value={company} onChange={e => { const c = e.target.value; setCompany(c); const available = rows.filter(r => r.company === c).map(r => r.fiscal_year); setYear(available.length ? Math.max(...available) : null); }}>
            {companies.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className={control} aria-label="Fiscal year" value={year ?? ''} onChange={e => setYear(Number(e.target.value))}>
            {years.map(y => <option key={y} value={y}>FY{y}</option>)}
          </select>
        </div>
        {barData.length ? <>
          <div><h3 className="mb-3 font-semibold">Financial performance ({reference?.currency} {reference?.unit})</h3>
            <ResponsiveContainer width="100%" height={260}><BarChart data={barData} margin={{ bottom: 50, right: 12 }}><CartesianGrid strokeDasharray="3 3" opacity={0.2}/><XAxis dataKey="name" angle={-20} textAnchor="end" interval={0} height={70} tick={{ fontSize: 10 }}/><YAxis/><Tooltip/><Bar dataKey="value" name="Reported value" fill="#4F8EF7"/></BarChart></ResponsiveContainer>
            <p className="text-xs text-[var(--text-muted)]">Source pages: {barData.map(r => `${r.name} p.${r.page}`).join(' · ')}</p>
          </div>
          <div><h3 className="mb-3 font-semibold">Revenue by fiscal year ({reference?.currency} {reference?.unit})</h3>
            <ResponsiveContainer width="100%" height={230}><LineChart data={trendData}><CartesianGrid strokeDasharray="3 3" opacity={0.2}/><XAxis dataKey="year"/><YAxis/><Tooltip/><Legend/><Line dataKey="revenue" stroke="#00C9A7" name="Revenue" connectNulls={false}/></LineChart></ResponsiveContainer>
          </div>
        </> : <p>No unique, comparable financial KPIs are available for this selection.</p>}
      </div>}
    </div>
  </div>;
}
