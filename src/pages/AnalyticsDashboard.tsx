import { useEffect, useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import API, { getOutliersCompany, getOutliersYear } from '../services/api';
import { PageShell } from '../components/ui';
import { useTheme } from '../theme';

type KPI = {
  company: string; currency: string; doc_id: string; fiscal_year: number;
  metric: string; page: number; source_label?: string; unit: string; value: number;
};
type Coverage = { company: string; total_documents: number; total_chunks: number };
type View = 'financial' | 'coverage';
const METRICS = ['revenue', 'gross_profit', 'operating_income', 'net_income', 'total_assets', 'total_liabilities', 'total_debt', 'cash_and_equivalents'];
const COLORS = ['#2563eb', '#0d9488', '#f59e0b', '#8b5cf6', '#e11d48'];
const title = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 });
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Request failed';
const isKPI = (v: unknown): v is KPI => {
  if (!v || typeof v !== 'object') return false;
  const k = v as KPI;
  return typeof k.company === 'string' && typeof k.metric === 'string' &&
    typeof k.currency === 'string' && typeof k.unit === 'string' &&
    typeof k.value === 'number' && Number.isFinite(k.value) &&
    typeof k.fiscal_year === 'number' && Number.isFinite(k.fiscal_year);
};
const unique = (rows: KPI[], metric: string): KPI | undefined => {
  const matching = rows.filter(k => k.metric === metric);
  return matching.length === 1 ? matching[0] : undefined;
};
const comparable = (a?: KPI, b?: KPI) => !!a && !!b && a.currency === b.currency && a.unit === b.unit;
const percent = (n: number | null) => n === null || !Number.isFinite(n) ? 'N/A' : `${fmt(n)}%`;
const money = (k?: KPI) => k ? `${fmt(k.value)} ${k.currency} ${k.unit}` : 'N/A';
const change = (now?: KPI, before?: KPI): number | null => comparable(now, before) && before!.value !== 0
  ? ((now!.value - before!.value) / Math.abs(before!.value)) * 100 : null;

function Panel({ title: heading, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return <section className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="border-b border-slate-100 px-5 py-4">
      <h2 className="text-base font-semibold text-slate-900">{heading}</h2>
      {subtitle && <p className="mt-1 text-xs leading-5 text-slate-500">{subtitle}</p>}
    </div>
    <div className="p-5">{children}</div>
  </section>;
}
function Empty({ message }: { message: string }) {
  return <div className="flex min-h-44 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">{message}</div>;
}
function Stat({ label, value, detail, trend }: { label: string; value: string; detail: string; trend?: number | null }) {
  return <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="mb-3 flex items-center justify-between"><p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p><span className="h-2 w-2 rounded-full bg-blue-500" /></div>
    <p className="break-words text-xl font-semibold tracking-tight text-slate-900 xl:text-2xl">{value}</p>
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
      {trend !== null && trend !== undefined && <span className={`rounded-md px-2 py-1 font-semibold ${trend >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{trend >= 0 ? '+' : ''}{percent(trend)} YoY</span>}
      <span>{detail}</span>
    </div>
  </div>;
}

export default function AnalyticsDashboard() {
  const { isDark } = useTheme();
  const chartAxis = { fontSize: 11, fill: isDark ? '#a2b2ca' : '#64748b' };
  const chartTooltip = { backgroundColor: isDark ? '#101f34' : '#ffffff', border: `1px solid ${isDark ? '#26384f' : '#e2e8f0'}`, borderRadius: 12, color: isDark ? '#f8fafc' : '#15263f', fontSize: 12 };
  const chartGrid = isDark ? '#26384f' : '#e2e8f0';
  const [view, setView] = useState<View>('financial');
  const [kpis, setKpis] = useState<KPI[]>([]);
  const [company, setCompany] = useState('');
  const [year, setYear] = useState<number | null>(null);
  const [compareCompany, setCompareCompany] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [coverage, setCoverage] = useState<Coverage[]>([]);
  const [yearCoverage, setYearCoverage] = useState<Record<string, unknown>>({});
  const [coverageError, setCoverageError] = useState('');
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [exportError, setExportError] = useState('');

  async function refresh() {
    setLoading(true); setError('');
    try {
      const { data } = await API.get<{ kpis: KPI[] }>('/financial-kpis');
      const rows = Array.isArray(data.kpis) ? data.kpis.filter(isKPI) : [];
      setKpis(rows);
      const names = [...new Set(rows.map(k => k.company))].sort();
      setCompany(old => names.includes(old) ? old : names[0] || '');
    } catch (e) { setError(errorText(e)); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    let active = true;
    API.get<{ kpis: KPI[] }>('/financial-kpis')
      .then(({ data }) => {
        if (!active) return;
        const rows = Array.isArray(data.kpis) ? data.kpis.filter(isKPI) : [];
        setKpis(rows);
        const names = [...new Set(rows.map(k => k.company))].sort();
        setCompany(names[0] || '');
      })
      .catch(e => { if (active) setError(errorText(e)); })
      .finally(() => { if (active) setLoading(false); });
    Promise.all([getOutliersCompany(), getOutliersYear()])
      .then(([a, b]) => {
        if (!active) return;
        setCoverage(Array.isArray(a.data) ? a.data : []);
        setYearCoverage(b.data && typeof b.data === 'object' ? b.data as Record<string, unknown> : {});
      })
      .catch(e => { if (active) setCoverageError(errorText(e)); })
      .finally(() => { if (active) setCoverageLoading(false); });
    return () => { active = false; };
  }, []);

  const companies = useMemo(() => [...new Set(kpis.map(k => k.company))].sort(), [kpis]);
  const companyRows = useMemo(() => kpis.filter(k => k.company === company), [kpis, company]);
  const years = useMemo(() => [...new Set(companyRows.map(k => k.fiscal_year))].sort((a, b) => b - a), [companyRows]);
  useEffect(() => { if (!years.includes(year ?? NaN)) setYear(years[0] ?? null); }, [years, year]);
  useEffect(() => {
    const alternatives = companies.filter(c => c !== company);
    if (!alternatives.includes(compareCompany)) setCompareCompany(alternatives[0] || '');
  }, [companies, company, compareCompany]);

  const current = useMemo(() => companyRows.filter(k => k.fiscal_year === year), [companyRows, year]);
  const previous = useMemo(() => companyRows.filter(k => k.fiscal_year === (year ?? 0) - 1), [companyRows, year]);
  const revenue = unique(current, 'revenue');
  const income = unique(current, 'net_income');
  const operating = unique(current, 'operating_income');
  const revenueChange = change(revenue, unique(previous, 'revenue'));
  const netMargin = comparable(income, revenue) && revenue!.value !== 0 ? income!.value / revenue!.value * 100 : null;
  const operatingMargin = comparable(operating, revenue) && revenue!.value !== 0 ? operating!.value / revenue!.value * 100 : null;
  const trend = useMemo(() => [...years].reverse().map(y => {
    const rows = companyRows.filter(k => k.fiscal_year === y);
    const value = (m: string) => {
      const k = unique(rows, m);
      return k?.currency === 'USD' && k.unit === 'million' ? k.value : null;
    };
    return { year: String(y), Revenue: value('revenue'), 'Gross profit': value('gross_profit'), 'Net income': value('net_income') };
  }), [companyRows, years]);
  const comparison = useMemo(() => METRICS.map(metric => {
    const get = (name: string) => {
      const k = unique(kpis.filter(r => r.company === name && r.fiscal_year === year), metric);
      return k?.currency === 'USD' && k.unit === 'million' ? k.value : null;
    };
    return { metric: title(metric), primary: get(company), secondary: get(compareCompany) };
  }), [kpis, year, company, compareCompany]);
  const comparableRows = comparison.filter(r => r.primary !== null || r.secondary !== null);
  const coverageYears = useMemo(() => {
    const found = new Set<string>();
    Object.values(yearCoverage).forEach(v => {
      if (v && typeof v === 'object') Object.keys(v).forEach(y => { if (/^20\d{2}$/.test(y)) found.add(y); });
    });
    return found.size;
  }, [yearCoverage]);

  function exportReport() {
    setExportError('');
    if (!company || year === null || !current.length) { setExportError('No financial records are available for export.'); return; }
    try {
      const lines = [
        'LEDGERCAPITAL — FINANCIAL ANALYTICS REPORT',
        `Company: ${company}`, `Fiscal year: ${year}`, `Generated: ${new Date().toISOString()}`,
        'Source: Extracted financial KPI records (not investment advice)', '',
        `Revenue: ${money(revenue)}`, `Net income: ${money(income)}`,
        `Operating margin: ${percent(operatingMargin)}`, `Net profit margin: ${percent(netMargin)}`,
        `Revenue growth vs FY${year - 1}: ${percent(revenueChange)}`, '',
        'EXTRACTED KPI RECORDS',
        'Metric | Value | Document ID | PDF page',
        ...current.map(k => `${title(k.metric)} | ${money(k)} | ${k.doc_id} | ${k.page ?? 'N/A'}`),
        '', `COMPANY COMPARISON — FY${year} (USD millions)`,
        `Metric | ${company} | ${compareCompany || 'Other company'}`,
        ...comparison.map(r => `${r.metric} | ${r.primary === null ? 'N/A' : fmt(r.primary)} | ${r.secondary === null ? 'N/A' : fmt(r.secondary)}`),
        '', 'Unavailable or ambiguous figures are shown as N/A. No values are estimated.',
      ];
      const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ledgercapital-analytics-${company.replace(/[^a-z0-9_-]/gi, '_')}-${year}.txt`;
      document.body.appendChild(link);
      link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setExportError(errorText(e)); }
  }

  const selectClass = 'mt-1 block w-full min-w-36 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100';
  return <PageShell>
    <div className={`lc-dashboard lc-analytics ${isDark ? "lc-mode-dark" : "lc-mode-light"} h-full min-h-0 overflow-y-auto px-1 pb-10 sm:px-3`}>
      <div className="mx-auto max-w-7xl space-y-5 py-4">
        <header className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
          <div><p className="mb-1 text-xs font-bold uppercase tracking-widest text-blue-600">LedgerCapital / Financial intelligence</p>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Financial Analytics</h1>
            <p className="mt-2 text-sm text-slate-500">Evidence-based performance insights from your indexed financial reports.</p></div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void refresh()} disabled={loading} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">{loading ? 'Loading…' : 'Refresh data'}</button>
            <button type="button" onClick={exportReport} disabled={!current.length || loading} className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">Export report</button>
          </div>
        </header>

        <nav aria-label="Analytics views" className="flex flex-wrap gap-2">
          {([['financial', 'Financial performance'], ['coverage', 'Knowledge base']] as const).map(([key, label]) =>
            <button key={key} type="button" onClick={() => setView(key)} aria-pressed={view === key} className={`rounded-lg px-4 py-2.5 text-sm font-semibold ${view === key ? 'bg-blue-700 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-100'}`}>{label}</button>)}
        </nav>
        {exportError && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">Export failed: {exportError}</p>}
        {view === 'financial' ? <>
          {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">Could not load KPIs: {error}</p>}
          {loading ? <Empty message="Loading financial analytics…" /> : !error && !kpis.length ? <Empty message="No extracted KPIs yet. Upload and index reports, then run KPI extraction from Admin." /> : null}
          {!!kpis.length && <>
            <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <label className="text-xs font-semibold text-slate-500">Company<select className={selectClass} value={company} onChange={e => setCompany(e.target.value)}>{companies.map(c => <option key={c} value={c}>{c}</option>)}</select></label>
              <label className="text-xs font-semibold text-slate-500">Fiscal year<select className={selectClass} value={year ?? ''} onChange={e => setYear(Number(e.target.value))}>{years.map(y => <option key={y} value={y}>{y}</option>)}</select></label>
              <p className="pb-2 text-xs text-slate-500">Figures come from extracted PDF records, not forecasts.</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Revenue" value={money(revenue)} detail={revenue ? `FY${year} · Page ${revenue.page}` : 'Missing or ambiguous'} trend={revenueChange}/>
              <Stat label="Net income" value={money(income)} detail={income ? `FY${year} · Page ${income.page}` : 'Missing or ambiguous'} />
              <Stat label="Operating margin" value={percent(operatingMargin)} detail="Operating income / Revenue" />
              <Stat label="Net profit margin" value={percent(netMargin)} detail="Net income / Revenue" />
            </div>
            <Panel title="Financial performance trend" subtitle={`${company} · Extracted USD-million figures across available fiscal years. Missing values are not interpolated.`}>
              {trend.some(r => r.Revenue !== null || r['Gross profit'] !== null || r['Net income'] !== null) ?
                <div className="h-80 w-full"><ResponsiveContainer width="100%" height="100%"><LineChart data={trend} margin={{ top: 10, right: 16, left: 6, bottom: 6 }}>
                  <CartesianGrid stroke={chartGrid} strokeDasharray="4 4" /><XAxis dataKey="year" tick={chartAxis} /><YAxis width={75} tick={chartAxis} tickFormatter={fmt} /><Tooltip contentStyle={chartTooltip} formatter={(v: number | string | undefined) => typeof v === 'number' ? `${fmt(v)} USD million` : 'N/A'} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="Revenue" stroke={COLORS[0]} strokeWidth={3} dot={{ r: 4 }} connectNulls={false} />
                  <Line type="monotone" dataKey="Gross profit" stroke={COLORS[1]} strokeWidth={2.5} dot={{ r: 4 }} connectNulls={false} />
                  <Line type="monotone" dataKey="Net income" stroke={COLORS[2]} strokeWidth={2.5} dot={{ r: 4 }} connectNulls={false} />
                </LineChart></ResponsiveContainer></div> : <Empty message="No compatible USD-million figures are available for the trend chart." />}
            </Panel>
            <Panel title="Company comparison" subtitle="Compare extracted USD-million values for the same fiscal year. Metrics are displayed individually, without combining percentages and currency.">
              <div className="mb-5 flex flex-wrap items-end gap-4"><label className="text-xs font-semibold text-slate-500">Compare against<select className={selectClass} value={compareCompany} onChange={e => setCompareCompany(e.target.value)} disabled={companies.length < 2}>{companies.filter(c => c !== company).map(c => <option key={c} value={c}>{c}</option>)}</select></label><span className="pb-2 text-xs text-slate-500">FY{year ?? '—'} · USD million</span></div>
              {!compareCompany ? <Empty message="Add another company with extracted KPIs to enable comparison." /> : <>
                {comparableRows.length ? <div className="h-[440px] w-full"><ResponsiveContainer width="100%" height="100%"><BarChart data={comparableRows} layout="vertical" margin={{ top: 8, right: 18, left: 12, bottom: 10 }} barGap={3}>
                  <CartesianGrid stroke={chartGrid} strokeDasharray="4 4" horizontal={false} /><XAxis type="number" tick={chartAxis} tickFormatter={fmt} /><YAxis type="category" dataKey="metric" width={135} tick={{ ...chartAxis, fontSize: 12 }} /><Tooltip contentStyle={chartTooltip} formatter={(v: number | string | undefined) => typeof v === 'number' ? `${fmt(v)} USD million` : 'N/A'} /><Legend wrapperStyle={{ fontSize: 12 }} /><Bar dataKey="primary" name={company} fill={COLORS[0]} radius={[0, 4, 4, 0]} /><Bar dataKey="secondary" name={compareCompany} fill={COLORS[1]} radius={[0, 4, 4, 0]} />
                </BarChart></ResponsiveContainer></div> : <Empty message="No comparable financial figures are available for the selected year." />}
                <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Metric</th><th className="px-4 py-3">{company}</th><th className="px-4 py-3">{compareCompany}</th></tr></thead><tbody>{comparison.map(r => <tr key={r.metric} className="border-t border-slate-100"><td className="px-4 py-3 font-medium text-slate-800">{r.metric}</td><td className="px-4 py-3 tabular-nums">{r.primary === null ? 'N/A' : fmt(r.primary)}</td><td className="px-4 py-3 tabular-nums">{r.secondary === null ? 'N/A' : fmt(r.secondary)}</td></tr>)}</tbody></table></div>
              </>}
            </Panel>
            <Panel title="Financial records and source references" subtitle="Every row is tied to an extracted financial record and its source PDF page.">
              {!current.length ? <Empty message="No KPI records exist for this company and year." /> : <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Metric</th><th className="px-4 py-3">Value</th><th className="px-4 py-3">PDF page</th><th className="px-4 py-3">Document ID</th></tr></thead><tbody>{current.map((k, i) => <tr key={`${k.doc_id}-${k.metric}-${k.page}-${i}`} className="border-t border-slate-100"><td className="px-4 py-3 font-medium text-slate-800">{k.source_label || title(k.metric)}</td><td className="px-4 py-3 tabular-nums">{money(k)}</td><td className="px-4 py-3">{k.page ?? 'N/A'}</td><td className="max-w-52 break-all px-4 py-3 font-mono text-xs text-slate-500">{k.doc_id || 'N/A'}</td></tr>)}</tbody></table></div>}
            </Panel>
          </>}
        </> : <>
          {coverageError && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">Knowledge-base analytics unavailable: {coverageError}</p>}
          {coverageLoading ? <Empty message="Loading knowledge-base coverage…" /> : coverageError ? <Empty message="The coverage endpoints are unavailable. Financial analytics can still be used." /> : <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Companies indexed" value={fmt(coverage.length)} detail="Knowledge-base metadata" />
              <Stat label="Indexed documents" value={fmt(coverage.reduce((n, c) => n + (Number(c.total_documents) || 0), 0))} detail="Across companies" />
              <Stat label="Text chunks" value={fmt(coverage.reduce((n, c) => n + (Number(c.total_chunks) || 0), 0))} detail="Searchable evidence" />
              <Stat label="Fiscal years" value={fmt(coverageYears)} detail="Metadata coverage" />
            </div>
            <Panel title="Knowledge-base document coverage" subtitle="Document counts show indexing coverage, not financial performance.">
              {coverage.length ? <div className="h-80 w-full"><ResponsiveContainer width="100%" height="100%"><BarChart data={coverage} margin={{ top: 8, right: 15, left: 5, bottom: 8 }}><CartesianGrid stroke={chartGrid} strokeDasharray="4 4" /><XAxis dataKey="company" tick={chartAxis} /><YAxis allowDecimals={false} tick={chartAxis} /><Tooltip contentStyle={chartTooltip} /><Legend /><Bar dataKey="total_documents" name="Documents" fill={COLORS[0]} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div> : <Empty message="No knowledge-base coverage records were returned." />}
            </Panel>
            <Panel title="Indexed text volume" subtitle="Chunk counts are shown separately from document counts to keep chart scales meaningful.">
              {coverage.length ? <div className="h-80 w-full"><ResponsiveContainer width="100%" height="100%"><BarChart data={coverage} margin={{ top: 8, right: 15, left: 5, bottom: 8 }}><CartesianGrid stroke={chartGrid} strokeDasharray="4 4" /><XAxis dataKey="company" tick={chartAxis} /><YAxis tick={chartAxis} /><Tooltip contentStyle={chartTooltip} /><Bar dataKey="total_chunks" name="Text chunks" fill={COLORS[1]} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div> : <Empty message="No indexed chunk records were returned." />}
            </Panel>
          </>}
        </>}
      </div>
    </div>
  </PageShell>;
}
