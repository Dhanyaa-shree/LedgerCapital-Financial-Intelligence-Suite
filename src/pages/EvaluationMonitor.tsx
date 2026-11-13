
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  RefreshCw,
  Search,
  ShieldCheck,
  Target,
} from 'lucide-react';
import { PageShell } from '../components/ui';
import { getEvals } from '../services/api';
import { useTheme } from '../theme';

type MetricMap = Record<string, number | null | undefined>;

type EvalResult = {
  ground_truth_id: string;
  query: string;
  category?: string;
  status?: string;
  error?: string;
  answer?: string;
  evaluation?: {
    overall_score: number | null;
    diagnosis?: string;
    latency?: number;
    layer1_retrieval: MetricMap;
    layer2_context: MetricMap;
    layer3_generation: MetricMap;
  } | null;
};

type EvalStats = {
  total_evaluations?: number;
  total_cases?: number;
  failed_cases?: number;
  average_overall?: number | null;
  average_metrics?: MetricMap;
  diagnoses?: Record<string, number>;
};

type EvalData = {
  status: string;
  message?: string;
  note?: string;
  timestamp?: string;
  method?: string;
  latest?: EvalStats | null;
  results?: EvalResult[];
  history?: {
    timestamp: string;
    average_overall: number | null;
    total_evaluations?: number;
  }[];
};

const metricGroups = [
  {
    title: 'Retrieval quality',
    subtitle: 'Relevant source discovery and ranking',
    icon: Search,
    keys: ['recall_at_k', 'precision_at_k', 'mrr', 'ndcg'],
  },
  {
    title: 'Context quality',
    subtitle: 'Evidence relevance and coverage',
    icon: FileText,
    keys: [
      'context_recall',
      'context_precision',
      'context_relevance',
    ],
  },
  {
    title: 'Generation quality',
    subtitle: 'Answer correctness and grounding',
    icon: ShieldCheck,
    keys: [
      'faithfulness',
      'answer_relevancy',
      'answer_correctness',
      'semantic_similarity',
    ],
  },
];

const metricLabels: Record<string, string> = {
  recall_at_k: 'Recall @ K',
  precision_at_k: 'Precision @ K',
  mrr: 'Mean Reciprocal Rank',
  ndcg: 'Normalized DCG',
  context_recall: 'Context recall',
  context_precision: 'Context precision',
  context_relevance: 'Context relevance',
  faithfulness: 'Faithfulness',
  answer_relevancy: 'Answer relevancy',
  answer_correctness: 'Answer correctness',
  semantic_similarity: 'Semantic similarity',
};

const label = (value: string) =>
  metricLabels[value] ||
  value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());

const isMeasured = (
  value: number | null | undefined
): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const percentage = (
  value: number | null | undefined
): string =>
  isMeasured(value)
    ? `${(value * 100).toFixed(1)}%`
    : 'Not measured';

const progressValue = (
  value: number | null | undefined
): number =>
  isMeasured(value)
    ? Math.max(0, Math.min(100, value * 100))
    : 0;

const formatDate = (value?: string) => {
  if (!value) return 'Unknown';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Unknown'
    : date.toLocaleString();
};

const cardClass =
  'rounded-2xl border border-slate-200 bg-white shadow-sm ' +
  'dark:border-slate-800 dark:bg-slate-900 dark:shadow-none';

const mutedText =
  'text-slate-500 dark:text-slate-400';

const primaryText =
  'text-slate-900 dark:text-slate-100';

function MetricRow({
  name,
  value,
}: {
  name: string;
  value: number | null | undefined;
}) {
  const measured = isMeasured(value);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          {label(name)}
        </span>
        <span
          className={
            'shrink-0 text-xs font-semibold ' +
            (measured
              ? 'text-slate-800 dark:text-slate-100'
              : 'text-slate-400 dark:text-slate-500')
          }
        >
          {percentage(value)}
        </span>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div
          className={
            'h-full rounded-full transition-all duration-500 ' +
            (measured
              ? 'bg-blue-600 dark:bg-blue-400'
              : 'bg-transparent')
          }
          style={{ width: `${progressValue(value)}%` }}
        />
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string;
  value: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className={`${cardClass} p-5`}>
      <div className="flex items-start justify-between gap-3">
        <p className={`text-sm font-medium ${mutedText}`}>
          {title}
        </p>

        <div className="rounded-xl bg-blue-50 p-2.5 dark:bg-blue-500/10">
          <Icon className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
      </div>

      <p className={`mt-4 text-3xl font-bold tracking-tight ${primaryText}`}>
        {value}
      </p>

      <p className={`mt-2 text-xs ${mutedText}`}>
        {description}
      </p>
    </div>
  );
}

function ResultCard({
  result,
  expanded,
  onToggle,
}: {
  result: EvalResult;
  expanded: boolean;
  onToggle: () => void;
}) {
  const failed = result.status === 'error';

  const layers = [
    {
      title: 'Retrieval',
      values: result.evaluation?.layer1_retrieval || {},
    },
    {
      title: 'Context',
      values: result.evaluation?.layer2_context || {},
    },
    {
      title: 'Generation',
      values: result.evaluation?.layer3_generation || {},
    },
  ];

  return (
    <div className="border-b border-slate-100 last:border-b-0 dark:border-slate-800">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60"
      >
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-semibold leading-6 ${primaryText}`}>
            {result.query}
          </p>

          <div className={`mt-1.5 flex flex-wrap items-center gap-2 text-xs ${mutedText}`}>
            <span>{result.ground_truth_id}</span>
            <span>·</span>

            <span
              className={
                failed
                  ? 'font-medium text-red-600 dark:text-red-400'
                  : 'font-medium text-emerald-600 dark:text-emerald-400'
              }
            >
              {failed ? 'Failed' : result.status || 'Completed'}
            </span>

            <span>·</span>
            <span>
              {result.evaluation?.diagnosis
                ? label(result.evaluation.diagnosis)
                : 'No diagnosis'}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {percentage(result.evaluation?.overall_score)}
          </span>

          {expanded ? (
            <ChevronUp className={`h-4 w-4 ${mutedText}`} />
          ) : (
            <ChevronDown className={`h-4 w-4 ${mutedText}`} />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-5">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950/60">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h4 className={`text-sm font-semibold ${primaryText}`}>
                {failed ? 'Execution error' : 'Generated answer'}
              </h4>

              {isMeasured(result.evaluation?.latency) && (
                <span className={`flex items-center gap-1 text-xs ${mutedText}`}>
                  <Clock3 className="h-3.5 w-3.5" />
                  {result.evaluation!.latency!.toFixed(2)}s
                </span>
              )}
            </div>

            <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-slate-600 dark:text-slate-300">
              {result.error ||
                result.answer ||
                'No answer returned.'}
            </p>

            {result.evaluation && (
              <div className="mt-5 grid gap-3 lg:grid-cols-3">
                {layers.map((layer) => (
                  <div
                    key={layer.title}
                    className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
                  >
                    <h5 className={`mb-3 text-xs font-bold uppercase tracking-wider ${primaryText}`}>
                      {layer.title}
                    </h5>

                    <div className="space-y-3">
                      {Object.entries(layer.values).map(
                        ([key, value]) => (
                          <div
                            key={key}
                            className="flex items-center justify-between gap-3 text-xs"
                          >
                            <span className={mutedText}>
                              {label(key)}
                            </span>
                            <span className={`font-semibold ${primaryText}`}>
                              {percentage(value)}
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function EvaluationMonitor() {
  const { isDark } = useTheme();
  const [data, setData] = useState<EvalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const response = await getEvals();
      setData(response.data as EvalData);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to load evaluation results'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stats = data?.latest;
  const averageMetrics = stats?.average_metrics || {};

  const results = useMemo(() => {
    return (data?.results || []).filter((result) => {
      if (filter === 'all') return true;
      if (filter === 'errors') return result.status === 'error';
      return result.status !== 'error';
    });
  }, [data, filter]);

  const history = useMemo(() => {
    return (data?.history || [])
      .slice()
      .reverse()
      .filter((item) => isMeasured(item.average_overall))
      .map((item, index) => ({
        run: `Run ${index + 1}`,
        score: Number((item.average_overall! * 100).toFixed(1)),
      }));
  }, [data]);

  const completedCount =
    (stats?.total_evaluations ?? 0) -
    (stats?.failed_cases ?? 0);

  return (
    <PageShell>
      <div className={`lc-dashboard lc-evaluation ${isDark ? "lc-mode-dark" : "lc-mode-light"} h-full min-h-0 overflow-y-auto`}>
        <div className="mx-auto w-full max-w-[1600px] px-5 py-7 sm:px-7 lg:px-9">
          {/* PAGE HEADER */}
          <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-400">
                LedgerCapital / Model Assurance
              </p>

              <h1 className={`text-2xl font-bold tracking-tight md:text-3xl ${primaryText}`}>
                RAG Evaluation
              </h1>

              <p className={`mt-2 max-w-2xl text-sm leading-6 ${mutedText}`}>
                Monitor evidence retrieval, context quality and
                answer correctness across financial records.
              </p>
            </div>

            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RefreshCw
                className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}
              />
              {loading ? 'Refreshing...' : 'Refresh results'}
            </button>
          </header>

          {/* ERROR */}
          {error && (
            <div
              role="alert"
              className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
            >
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-semibold">
                  Unable to load evaluation results
                </p>
                <p className="mt-1">
                  {error}. Ensure the Flask backend is running on
                  port 5001.
                </p>
              </div>
            </div>
          )}

          {/* INITIAL LOADING */}
          {loading && !data && (
            <div className={`${cardClass} flex min-h-64 flex-col items-center justify-center p-10`}>
              <RefreshCw className="h-7 w-7 animate-spin text-blue-600 dark:text-blue-400" />
              <p className={`mt-4 text-sm ${mutedText}`}>
                Loading evaluation results...
              </p>
            </div>
          )}

          {/* EMPTY STATE */}
          {!loading && !error && !stats && (
            <div className={`${cardClass} p-10 text-center`}>
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800">
                <BarChart3 className="h-6 w-6 text-slate-500 dark:text-slate-400" />
              </div>

              <h2 className={`mt-5 text-lg font-semibold ${primaryText}`}>
                No evaluation run found
              </h2>

              <p className={`mx-auto mt-2 max-w-lg text-sm leading-6 ${mutedText}`}>
                {data?.message ||
                  'No saved evaluation results are available.'}
              </p>

              <code className="mt-5 inline-block rounded-lg bg-slate-100 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                python evals/run_evals.py
              </code>
            </div>
          )}

          {/* EVALUATION DASHBOARD */}
          {stats && (
            <>
              {/* KPI SUMMARY */}
              <section className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard
                  title="Evaluated queries"
                  value={String(stats.total_evaluations ?? 0)}
                  description="Total evaluated test cases"
                  icon={Activity}
                />

                <StatCard
                  title="Available-metric average"
                  value={percentage(stats.average_overall)}
                  description="Average of measured proxy metrics"
                  icon={Target}
                />

                <StatCard
                  title="Failed cases"
                  value={String(stats.failed_cases ?? 0)}
                  description="Execution errors"
                  icon={AlertCircle}
                />

                <StatCard
                  title="Numeric matches"
                  value={String(stats.diagnoses?.numeric_match ?? 0)}
                  description="KPI reference matches"
                  icon={CheckCircle2}
                />
              </section>

              {/* EVALUATION NOTE */}
              {data?.note && (
                <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />

                  <div>
                    <span className="font-semibold">
                      Evaluation methodology
                    </span>
                    <p className="mt-1">{data.note}</p>
                  </div>
                </div>
              )}

              {/* QUALITY METRICS */}
              <section className="mb-5 grid gap-4 xl:grid-cols-3">
                {metricGroups.map((group, index) => {
                  const Icon = group.icon;

                  return (
                    <div
                      key={group.title}
                      className={`${cardClass} p-5`}
                    >
                      <div className="mb-6 flex items-start gap-3">
                        <div className="rounded-xl bg-blue-50 p-2.5 dark:bg-blue-500/10">
                          <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                        </div>

                        <div>
                          <p className={`text-sm font-bold ${primaryText}`}>
                            {String(index + 1).padStart(2, '0')} ·{' '}
                            {group.title}
                          </p>

                          <p className={`mt-1 text-xs leading-5 ${mutedText}`}>
                            {group.subtitle}
                          </p>
                        </div>
                      </div>

                      <div className="space-y-5">
                        {group.keys.map((key) => (
                          <MetricRow
                            key={key}
                            name={key}
                            value={averageMetrics[key]}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </section>

              {/* HISTORY */}
              {history.length > 1 && (
                <section className={`${cardClass} mb-5 p-5`}>
                  <div className="mb-5">
                    <h2 className={`text-base font-semibold ${primaryText}`}>
                      Evaluation history
                    </h2>
                    <p className={`mt-1 text-xs ${mutedText}`}>
                      Available-metric averages across saved runs
                    </p>
                  </div>

                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={history}
                        margin={{
                          top: 8,
                          right: 12,
                          left: -15,
                          bottom: 5,
                        }}
                      >
                        <CartesianGrid
                          stroke="currentColor"
                          strokeOpacity={0.12}
                          strokeDasharray="3 3"
                        />

                        <XAxis
                          dataKey="run"
                          tick={{ fontSize: 12 }}
                          stroke="#94a3b8"
                          tickLine={false}
                          axisLine={false}
                        />

                        <YAxis
                          domain={[0, 100]}
                          unit="%"
                          tick={{ fontSize: 12 }}
                          stroke="#94a3b8"
                          tickLine={false}
                          axisLine={false}
                        />

                        <Tooltip
                          contentStyle={{
                            backgroundColor: '#1e293b',
                            color: '#f8fafc',
                            border: '1px solid #475569',
                            borderRadius: '12px',
                          }}
                          formatter={(value) => [
                            `${Number(value).toFixed(1)}%`,
                            'Available-metric average',
                          ]}
                        />

                        <Line
                          type="monotone"
                          dataKey="score"
                          name="Average score"
                          stroke="#3b82f6"
                          strokeWidth={3}
                          dot={{ r: 4 }}
                          activeDot={{ r: 6 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              )}

              {/* QUERY RESULTS */}
              <section className={`${cardClass} overflow-hidden`}>
                <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 p-5 dark:border-slate-800">
                  <div>
                    <h2 className={`text-base font-semibold ${primaryText}`}>
                      Query-level results
                    </h2>

                    <p className={`mt-1 text-xs ${mutedText}`}>
                      {results.length} results shown ·{' '}
                      {completedCount} completed without execution errors
                    </p>
                  </div>

                  <select
                    aria-label="Filter evaluation results"
                    value={filter}
                    onChange={(event) => setFilter(event.target.value)}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    <option value="all">All results</option>
                    <option value="completed">Completed</option>
                    <option value="errors">Errors</option>
                  </select>
                </div>

                {results.length === 0 ? (
                  <div className="px-5 py-12 text-center">
                    <p className={`text-sm ${mutedText}`}>
                      No results match the selected filter.
                    </p>
                  </div>
                ) : (
                  <div>
                    {results.map((result, index) => (
                      <ResultCard
                        key={`${result.ground_truth_id}-${index}`}
                        result={result}
                        expanded={
                          expanded === result.ground_truth_id
                        }
                        onToggle={() =>
                          setExpanded((previous) =>
                            previous === result.ground_truth_id
                              ? null
                              : result.ground_truth_id
                          )
                        }
                      />
                    ))}
                  </div>
                )}
              </section>

              {/* FOOTER */}
              <footer className={`mt-5 flex flex-wrap items-center justify-between gap-3 text-xs ${mutedText}`}>
                <span className="flex items-center gap-2">
                  <Clock3 className="h-3.5 w-3.5" />
                  Last evaluation: {formatDate(data?.timestamp)}
                </span>

                <span>
                  {data?.method === 'silver_reference_kpi'
                    ? 'Silver-reference KPI evaluation'
                    : data?.method || 'Evaluation results'}
                  {' · '}
                  Read-only results
                </span>
              </footer>
            </>
          )}
        </div>
      </div>
    </PageShell>
  );
}
