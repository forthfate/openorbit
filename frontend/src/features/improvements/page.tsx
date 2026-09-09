import { Check, Copy } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  ImprovementAnalytics,
  ImprovementIterationData,
  Build,
  ProposalLifecycle,
  SavedDataFile,
} from "../../domain/models";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { StatusBadge } from "../../components/ui/status-badge";
import { api } from "../../services/api";
import {
  localeMessageMap,
  localeMessages,
  locales,
  intlLocales,
  resolveLocale,
  type Locale,
} from "../../locales";
import "./saved-data-files.css";
import { FeedbackTrends } from "../dashboard/feedback-trends";

type ImprovementCopy = {
  improvement: string;
  trends: string;
  range: string;
  evaluation: string;
  feedbackVolume: string;
  iterationTrend: string;
  activeTrend: string;
  feedbackStatus: string;
  issueSeverity: string;
  runHealth: string;
  accepted: string;
  score: string;
  history: string;
  historyHint: string;
  allBuilds: string;
  allStates: string;
  rejected: string;
  proposed: string;
  decisionReason: string;
  timeline: string;
  noProposals: string;
  savedDataFiles: string;
  fileName: string;
  copyFileName: string;
  copyPath: string;
  iteration: string;
  run: string;
  feedbackCount: string;
  activeCount: string;
  noIterationFeedback: string;
  adopted: string;
  low: string;
  medium: string;
  high: string;
  critical: string;
  succeeded: string;
  failed: string;
  cancelled: string;
  running: string;
  selectBuild: string;
};
const copy = localeMessageMap<ImprovementCopy>("improvementPage");
const tick = (value: string) =>
  new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
const timestamp = (locale: Locale, value?: string) =>
  value ? new Date(value).toLocaleString(intlLocales[locale]) : "—";
function Card({ title, children }: { title: string; children: ReactNode }) {
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    chartHints = localeMessages<Record<string, string>>(locale, "chartHints"),
    description = chartHints[title];
  return (
    <article className="analytics-chart">
      <h3>
        {description ? (
          <SectionInfo title={title} description={description} />
        ) : (
          title
        )}
      </h3>
      {children}
    </article>
  );
}

export function Trends({ t }: { t: (typeof copy)["en"] }) {
  const [hours, setHours] = useState(24),
    [build, setBuild] = useState(""),
    [data, setData] = useState<ImprovementAnalytics>();
  useEffect(() => {
    api<ImprovementAnalytics>(`/api/improvement-analytics?hours=${hours}`)
      .then((next) => {
        setData(next);
        setBuild((current) =>
          next.iteration_trends.some((x) => x.build_id === current)
            ? current
            : (next.iteration_trends.find((x) => x.points.length)?.build_id ??
              next.iteration_trends[0]?.build_id ??
              ""),
        );
      })
      .catch(() => setData(undefined));
  }, [hours]);
  const trend = data?.iteration_trends.find((x) => x.build_id === build),
    short = (value: string) =>
      value.length > 18 ? `${value.slice(0, 18)}…` : value;
  return (
    <section className="panel improvement-trends">
      <div className="trend-head">
        <PanelHeader title={t.trends} />
        <label>
          {t.range}
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={24}>24h</option>
            <option value={72}>3d</option>
            <option value={168}>7d</option>
            <option value={720}>30d</option>
          </select>
        </label>
      </div>
      <div className="analytics-grid">
        <Card title={t.feedbackVolume}>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart
              data={data?.feedback_by_build ?? []}
              margin={{ left: -18 }}
            >
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" tickFormatter={short} />
              <YAxis allowDecimals={false} />
              <ChartTooltip />
              <Bar
                dataKey="feedback_count"
                name={t.feedbackCount}
                fill="var(--accent)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title={t.activeTrend}>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart
              data={data?.active_evaluations ?? []}
              margin={{ left: -18 }}
            >
              <CartesianGrid vertical={false} />
              <XAxis dataKey="time" tickFormatter={tick} />
              <YAxis allowDecimals={false} />
              <ChartTooltip
                labelFormatter={(v) => new Date(String(v)).toLocaleString()}
              />
              <Area
                type="monotone"
                dataKey="count"
                name={t.activeCount}
                stroke="var(--accent)"
                fill="var(--surface-raised)"
                dot={{ r: 3, fill: "var(--accent)", stroke: "var(--surface)" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>
      <Card title={t.iterationTrend}>
        <div className="chart-select">
          <label>
            {t.evaluation}
            <select value={build} onChange={(e) => setBuild(e.target.value)}>
              {data?.iteration_trends.map((x) => (
                <option key={x.build_id} value={x.build_id}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {trend?.points.length ? (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={trend.points} margin={{ left: -18 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="iteration" tickFormatter={(v) => `#${v}`} />
              <YAxis yAxisId="count" allowDecimals={false} />
              <YAxis yAxisId="score" orientation="right" domain={[0, 10]} />
              <ChartTooltip />
              <Legend />
              <Bar
                yAxisId="count"
                dataKey="accepted_count"
                name={t.accepted}
                fill="#79c99e"
              />
              <Line
                yAxisId="score"
                type="monotone"
                dataKey="score"
                name={t.score}
                stroke="#8fb8ff"
                strokeWidth={3}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <p className="hint">{t.noIterationFeedback}</p>
        )}
      </Card>
      <div className="analytics-grid">
        <Card title={t.feedbackStatus}>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data?.feedback_status ?? []} margin={{ left: -18 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" tickFormatter={short} />
              <YAxis allowDecimals={false} />
              <ChartTooltip />
              <Legend />
              <Bar stackId="a" dataKey="proposed" name={t.proposed} fill="#f1d292" />
              <Bar stackId="a" dataKey="adopted" name={t.adopted} fill="#79c99e" />
              <Bar stackId="a" dataKey="rejected" name={t.rejected} fill="#eaa89f" />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title={t.issueSeverity}>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={data?.issue_severity ?? []} margin={{ left: -18 }}>
              <XAxis dataKey="time" tickFormatter={tick} />
              <YAxis allowDecimals={false} />
              <ChartTooltip
                labelFormatter={(v) => new Date(String(v)).toLocaleString()}
              />
              <Legend />
              <Area
                stackId="a"
                type="monotone"
                dataKey="low"
                name={t.low}
                fill="#79c99e"
                stroke="#79c99e"
              />
              <Area
                stackId="a"
                type="monotone"
                dataKey="medium"
                name={t.medium}
                fill="#f1d292"
                stroke="#f1d292"
              />
              <Area
                stackId="a"
                type="monotone"
                dataKey="high"
                name={t.high}
                fill="#e49a64"
                stroke="#e49a64"
              />
              <Area
                stackId="a"
                type="monotone"
                dataKey="critical"
                name={t.critical}
                fill="#eaa89f"
                stroke="#eaa89f"
              />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>
      <Card title={t.runHealth}>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data?.run_health ?? []} margin={{ left: -18 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="name" tickFormatter={short} />
            <YAxis allowDecimals={false} />
            <ChartTooltip />
            <Legend />
            <Bar stackId="a" dataKey="succeeded" name={t.succeeded} fill="#79c99e" />
            <Bar stackId="a" dataKey="failed" name={t.failed} fill="#eaa89f" />
            <Bar stackId="a" dataKey="cancelled" name={t.cancelled} fill="#9ca7b8" />
            <Bar stackId="a" dataKey="running" name={t.running} fill="#8fb8ff" />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </section>
  );
}

function SavedDataFiles({
  files,
  t,
}: {
  files: SavedDataFile[];
  t: (typeof copy)["en"];
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const displayedFiles = [...new Map(files.map((file) => [file.path, file])).values()];
  if (!displayedFiles.length) return null;
  const copyValue = async (value: string, key: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(
        () => setCopied((current) => (current === key ? null : current)),
        1_500,
      );
    } catch {
      setCopied(null);
    }
  };
  return (
    <section className="saved-data-files">
      <strong>{t.savedDataFiles}</strong>
      <div className="saved-data-files__list">
        {displayedFiles.map((file, index) => (
          <article key={`${file.path}-${index}`}>
            <strong>{file.label || file.filename}</strong>
            {file.label && (
              <small>
                {t.fileName}: {file.filename}
              </small>
            )}
            <div>
              <code>{file.path}</code>
              <button
                className="ghost icon-button"
                type="button"
                onClick={() => copyValue(file.path, `path-${index}`)}
                aria-label={t.copyPath}
                title={t.copyPath}
              >
                {copied === `path-${index}` ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
            <button
              className="ghost saved-data-files__copy-name"
              type="button"
              onClick={() => copyValue(file.filename, `name-${index}`)}
            >
              {copied === `name-${index}` ? <Check size={14} /> : <Copy size={14} />}
              {t.copyFileName}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function iterationDataFiles(items: ProposalLifecycle[]): SavedDataFile[] {
  return [
    ...new Map(
      items
        .flatMap((item) => item.data_files ?? [])
        .map((file) => [file.path, file]),
    ).values(),
  ];
}

function ProposalHistory({
  t,
  locale,
  buildId,
}: {
  t: (typeof copy)["en"];
  locale: Locale;
  buildId?: string;
}) {
  const [items, setItems] = useState<ProposalLifecycle[]>([]),
    [iterationData, setIterationData] = useState<ImprovementIterationData[]>([]),
    [selected, setSelected] = useState<ProposalLifecycle | null>(null);
  useEffect(() => {
    api<ProposalLifecycle[]>("/api/v1/improvements/proposals")
      .then(setItems)
      .catch(() => setItems([]));
    api<ImprovementIterationData[]>("/api/v1/improvements/iterations")
      .then(setIterationData)
      .catch(() => setIterationData([]));
  }, []);
  const tree = useMemo(() => {
    const builds = new Map<
      string,
      {
        name: string;
        runs: Map<
          string,
          {
            iterations: Map<
              number,
              { items: ProposalLifecycle[]; dataFiles: SavedDataFile[]; recordedAt?: string }
            >;
          }
        >;
      }
    >();
    const iteration = (
      evaluationBuildId: string | undefined,
      evaluationBuildName: string | undefined,
      runId: string | undefined,
      value: number | undefined,
      recordedAt?: string,
    ) => {
      const resolvedBuildId = evaluationBuildId || "unassigned";
      const build = builds.get(resolvedBuildId) || {
        name: evaluationBuildName || resolvedBuildId,
        runs: new Map(),
      };
      const resolvedRunId = runId || "unknown-run";
      const run = build.runs.get(resolvedRunId) || { iterations: new Map() };
      const resolvedIteration = value ?? 0;
      const group = run.iterations.get(resolvedIteration) || {
        items: [],
        dataFiles: [],
        recordedAt,
      };
      if (!group.recordedAt && recordedAt) group.recordedAt = recordedAt;
      run.iterations.set(resolvedIteration, group);
      build.runs.set(resolvedRunId, run);
      builds.set(resolvedBuildId, build);
      return group;
    };
    for (const item of items.filter((item) => !buildId || item.evaluation_build_id === buildId)) {
      iteration(
        item.evaluation_build_id,
        item.evaluation_build_name,
        item.run_id,
        item.iteration,
        item.recorded_at,
      ).items.push(item);
    }
    for (const item of iterationData.filter(
      (item) => !buildId || item.evaluation_build_id === buildId,
    )) {
      iteration(
        item.evaluation_build_id,
        item.evaluation_build_name,
        item.run_id,
        item.iteration,
        item.recorded_at,
      ).dataFiles.push(...item.data_files);
    }
    return [...builds.entries()].map(([id, build]) => ({
      id,
      ...build,
      runs: [...build.runs.entries()]
        .map(([runId, run]) => ({
          runId,
          iterations: [...run.iterations.entries()]
            .map(([iteration, group]) => ({ iteration, ...group }))
            .sort((a, b) => a.iteration - b.iteration),
        }))
        .sort(
          (a, b) =>
            b.iterations
              .at(-1)
              ?.recordedAt?.localeCompare(a.iterations.at(-1)?.recordedAt || "") || 0,
        ),
    }));
  }, [items, iterationData, buildId]);
  const statusLabel = (value: string) =>
    value === "rejected"
      ? t.rejected
      : value === "proposed"
        ? t.proposed
        : t.accepted;
  const proposalText = (key: string) =>
    typeof selected?.proposal[key] === "string"
      ? String(selected.proposal[key])
      : "";
  return (
    <section className="cycle-proposal-history">
      <h3>
        <SectionInfo title={t.history} description={t.historyHint} />
      </h3>
      <p className="hint">{t.historyHint}</p>
      {tree.length ? (
        <div className="proposal-tree">
          {tree.map((build) => (
            <details className="proposal-tree__build" key={build.id} open>
              <summary>
                <strong>{build.name}</strong>
                <small>
                  {build.runs.length} {t.run}
                </small>
              </summary>
              {build.runs.map((run) => (
                <details className="proposal-tree__run" key={run.runId} open>
                  <summary>
                    <span>
                      <strong>{t.run}</strong>
                      <small>{run.runId}</small>
                    </span>
                  </summary>
                  {run.iterations.map((group) => (
                    <details
                      className="proposal-tree__iteration"
                      key={group.iteration}
                      open
                    >
                      <summary>
                        <span>
                          <strong>
                            {t.iteration} #{group.iteration}
                          </strong>
                          <small>
                            {timestamp(locale, group.recordedAt)}
                          </small>
                        </span>
                        <span className="proposal-tree__iteration-meta">
                          <small>{group.items.length}</small>
                        </span>
                      </summary>
                      <div>
                        {group.items.map((item) => (
                          <button
                            className="proposal-tree__item"
                            key={item.proposal_id}
                            onClick={() => setSelected(item)}
                          >
                            <span>
                              <strong>{item.title}</strong>
                              <small>{item.target}</small>
                            </span>
                            <span className="proposal-tree__item-meta">
                              {item.score !== undefined &&
                                item.score !== null && (
                                  <b className="proposal-tree__score">
                                    {t.score} {item.score}/10
                                  </b>
                                )}
                              <StatusBadge
                                value={item.status}
                                label={statusLabel(item.status)}
                              />
                            </span>
                          </button>
                        ))}
                        <SavedDataFiles
                          files={[
                            ...group.dataFiles,
                            ...iterationDataFiles(group.items),
                          ]}
                          t={t}
                        />
                      </div>
                    </details>
                  ))}
                </details>
              ))}
            </details>
          ))}
        </div>
      ) : (
        <p className="catalog-empty">{t.noProposals}</p>
      )}
      <Modal
        open={!!selected}
        title={selected?.title || t.history}
        onClose={() => setSelected(null)}
        className="modal--proposal-detail"
      >
        {selected && (
          <div className="proposal-detail">
            <div className="proposal-detail__summary">
              <StatusBadge
                value={selected.status}
                label={statusLabel(selected.status)}
              />
              <span>
                {selected.evaluation_build_name ||
                  selected.evaluation_build_id ||
                  "—"}{" "}
                · {t.iteration} #{selected.iteration ?? "—"}
              </span>
              <span>
                {t.run}: {selected.run_id || "—"}
              </span>
            </div>
            <section>
              <h3>{t.decisionReason}</h3>
              <p>{selected.decision_rationale || "—"}</p>
            </section>
            {proposalText("proposed_change") && (
              <section>
                <h3>{t.improvement}</h3>
                <pre>{proposalText("proposed_change")}</pre>
              </section>
            )}
            <section>
              <h3>{t.timeline}</h3>
              <ol className="proposal-timeline">
                {selected.events.map((event) => (
                  <li key={event.id}>
                    <StatusBadge
                      value={
                        event.decision === "pending"
                          ? "proposed"
                          : event.decision || "proposed"
                      }
                      label={statusLabel(
                        event.decision === "pending"
                          ? "proposed"
                          : event.decision || "proposed",
                      )}
                    />
                    <div>
                      <strong>{timestamp(locale, event.recorded_at)}</strong>
                      <small>
                        {t.iteration} #{event.iteration ?? "—"} ·{" "}
                        {event.phase || "—"}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </div>
        )}
      </Modal>
    </section>
  );
}

function CycleImprovementAI({
  locale,
  build,
}: {
  locale: Locale;
  build: string;
}) {
  const [data, setData] = useState<ImprovementAnalytics>(),
    [analysis, setAnalysis] = useState(""),
    [loading, setLoading] = useState(false),
    t = locales[locale].cycle;
  useEffect(() => {
    api<ImprovementAnalytics>("/api/improvement-analytics?hours=720")
      .then((next) => {
        setData(next);
      })
      .catch(() => setData(undefined));
  }, []);
  const trend = data?.iteration_trends.find((item) => item.build_id === build),
    scores = (trend?.points ?? [])
      .map((item) => item.score)
      .filter((score): score is number => score !== null),
    health =
      scores.length === 0
        ? t.noScoreEvidence
        : scores.length === 1
          ? t.initialObservation
          : scores.at(-1)! >= scores[0]
            ? t.healthyLoop
            : t.needsAttention;
  const request = () => {
    setLoading(true);
    api<{ response: string }>("/api/cycle-improvements/analyze", "POST", {
      evaluation_build_id: build,
      locale,
    })
      .then((result) => setAnalysis(result.response))
      .catch((error) => setAnalysis(error.message))
      .finally(() => setLoading(false));
  };
  return (
    <section className="panel cycle-interventions">
      <div className="cycle-interventions__head">
        <PanelHeader
          title={<SectionInfo title={t.title} description={t.titleHint} />}
        />
      </div>
      <p className="hint">{t.description}</p>
      {build && (
        <>
          <div className="cycle-health">
            <article>
              <small>
                <SectionInfo title={t.health} description={t.healthHint} />
              </small>
              <strong>{health}</strong>
            </article>
            <article>
              <small>
                <SectionInfo title={t.score} description={t.scoreHint} />
              </small>
              <strong>{scores.at(-1) ?? "—"}</strong>
            </article>
            <article>
              <small>
                <SectionInfo
                  title={t.iterations}
                  description={t.iterationsHint}
                />
              </small>
              <strong>{trend?.points.length ?? 0}</strong>
            </article>
          </div>
          <div className="cycle-ai-action">
            <button className="approve" disabled={loading} onClick={request}>
              {loading ? t.analyzing : t.analyze}
            </button>
            {analysis && (
              <div className="cycle-ai-response">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {analysis}
                </ReactMarkdown>
              </div>
            )}
          </div>
          <ProposalHistory t={copy[locale]} locale={locale} buildId={build} />
        </>
      )}
    </section>
  );
}
export function ImprovementsPage() {
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    t = copy[locale],
    [build, setBuild] = useState(""),
    [builds, setBuilds] = useState<Build[]>([]);
  useEffect(() => {
    api<Build[]>("/api/evaluation-builds")
      .then((next) => {
        setBuilds(next);
        setBuild((current) => current || next[0]?.id || "");
      })
      .catch(() => setBuilds([]));
  }, []);
  return (
    <>
      <section className="improvements-build-selector">
        <label>
          {t.selectBuild}
          <select value={build} onChange={(event) => setBuild(event.target.value)}>
            {builds.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
      </section>
      {build && <FeedbackTrends locale={locale} buildId={build} scope="improvements" />}
      <CycleImprovementAI locale={locale} build={build} />
    </>
  );
}
