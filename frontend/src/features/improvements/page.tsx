import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
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
  Build,
  Run,
  RunnerState,
} from "../../domain/models";
import { Modal } from "../../components/ui/modal";
import { preferredBuildId, savePreferredBuildId } from "../../services/build-selection";
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
import { FeedbackTrends } from "../dashboard/feedback-trends";
import { SectionSkeleton } from "../../components/ui/section-skeleton";
import { DataTable, type Column } from "../../components/ui/data-table";
import { CircleStop, RotateCcw } from "lucide-react";
import { EvaluationsPage } from "../evaluations/page";
import { IssueManagementSection } from "../issues/page";

type ImprovementCopy = {
  improvement: string;
  trends: string;
  range: string;
  unlimited: string;
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
  acceptable: string;
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
  low: string;
  medium: string;
  high: string;
  critical: string;
  succeeded: string;
  failed: string;
  cancelled: string;
  running: string;
  selectBuild: string;
  storedState: string;
  storedStateHint: string;
  noStoredState: string;
  updated: string;
  rawState: string;
  buildState: string;
  runnerState: string;
  relatedRuns: string;
  relatedRunsHint: string;
  noRelatedRuns: string;
  personaJourneys: string;
  personaJourneysHint: string;
  noPersonaJourneys: string;
  personaGoal: string;
  currentAction: string;
  currentDecision: string;
  nextAction: string;
  started: string;
  currentPhase: string;
  stop: string;
  retry: string;
  retryWarning: string;
  restart: string;
  resume: string;
};
type ChartHints = {
  feedbackByBuild: string;
  activeRuns: string;
  iterationTrend: string;
  feedbackStatus: string;
  issueSeverity: string;
  runHealth: string;
};
const copy = localeMessageMap<ImprovementCopy>("improvementPage");
const tick = (value: string) =>
  new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
const timestamp = (locale: Locale, value?: string) =>
  value ? new Date(value).toLocaleString(intlLocales[locale]) : "—";
const compactTimestamp = (locale: Locale, value?: string) =>
  value
    ? new Intl.DateTimeFormat(intlLocales[locale], {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "—";
const lastRunTimestamp = (build: Build) =>
  build.last_run_at ? Date.parse(build.last_run_at) || 0 : 0;
const terminalRun = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);

function RelatedRuns({
  buildId, runs, locale, t, hours, onStop, onRetryRequest, onSelect,
}: {
  buildId: string;
  runs: Run[];
  locale: Locale;
  t: (typeof copy)["en"];
  hours: number;
  onStop: (id: string) => void;
  onRetryRequest: (run: Run) => void;
  onSelect: (run: Run) => void;
}) {
  const [rangeStart] = useState(() => hours ? Date.now() - hours * 60 * 60 * 1000 : 0);
  const related = useMemo(
    () => runs.filter((run) =>
      run.build_id === buildId && (rangeStart === 0 || !run.created_at || (Date.parse(run.created_at) || 0) >= rangeStart),
    ).sort(
      (left, right) => (Date.parse(right.created_at ?? "") || 0) - (Date.parse(left.created_at ?? "") || 0),
    ),
    [buildId, rangeStart, runs],
  );
  const active = related.filter((run) => !terminalRun(run.status));
  const completed = related.filter((run) => terminalRun(run.status));
  const visible = [...active, ...completed.slice(0, 5)];
  const runUi = locales[locale].runUi;
  const statusLabel = (status: string) => ({
    succeeded: t.succeeded, failed: t.failed, cancelled: t.cancelled, running: t.running,
    queued: runUi.queued,
    awaiting_approval: runUi.awaitingApproval,
  } as Record<string, string>)[status] ?? status;
  const iteration = (run: Run) => {
    const current = Math.max(0, ...(run.step_results ?? []).map((step) => step.loop_index ?? 0));
    return run.loop_limit ? `${Math.min(current, run.loop_limit)}/${run.loop_limit}` : "—";
  };
  const columns: Column<Run>[] = [
    { id: "run", header: t.run, render: (run) => <span className="related-run-id"><code>{run.id}</code><StatusBadge value={run.status} label={statusLabel(run.status)} /></span>, sortValue: (run) => run.id },
    { id: "started", header: t.started, render: (run) => compactTimestamp(locale, run.created_at), sortValue: (run) => run.created_at },
    { id: "iteration", header: t.iteration, render: iteration, sortValue: iteration },
    { id: "phase", header: t.currentPhase, render: (run) => run.current_phase ?? "—", sortValue: (run) => run.current_phase },
    { id: "actions", header: locales[locale].evaluation.action, render: (run) => {
      const canRetry = terminalRun(run.status) && run.execution_type === "pipeline";
      return <span className="build-actions">
        {!terminalRun(run.status) && <button className="icon-button danger" title={t.stop} aria-label={t.stop} onClick={() => onStop(run.id)}><CircleStop size={16} /></button>}
        {canRetry && <button className="icon-button" title={t.retry} aria-label={t.retry} onClick={() => onRetryRequest(run)}><RotateCcw size={16} /></button>}
      </span>;
    } },
  ];
  return (
    <section className="panel related-runs" aria-labelledby="related-runs-title">
      <div className="related-runs__heading">
        <div>
          <h2 id="related-runs-title">{t.relatedRuns}</h2>
          <p>{t.relatedRunsHint}</p>
        </div>
        <div className="related-runs__counts">
          <span>{t.running} <b>{active.length}</b></span>
          <span>{t.succeeded} <b>{completed.filter((run) => run.status === "succeeded").length}</b></span>
          <span>{t.failed} <b>{completed.filter((run) => run.status === "failed").length}</b></span>
          <span>{t.cancelled} <b>{completed.filter((run) => run.status === "cancelled").length}</b></span>
        </div>
      </div>
      <DataTable columns={columns} rows={visible} onRowClick={onSelect} className="related-runs-table" gridTemplateColumns="minmax(190px,1.4fr) minmax(118px,.85fr) 90px minmax(105px,1fr) minmax(145px,.9fr)" empty={t.noRelatedRuns} />
    </section>
  );
}

type PersonaJourneyEvent = {
  id: string;
  persona: string;
  run: Run;
  iteration: number;
  recordedAt?: string;
  goal?: string;
  action?: string;
  decision?: string;
  nextAction?: string;
};

function PersonaJourneyTimeline({
  buildId, runs, locale, t, hours, onSelect,
}: {
  buildId: string;
  runs: Run[];
  locale: Locale;
  t: (typeof copy)["en"];
  hours: number;
  onSelect: (run: Run) => void;
}) {
  const [rangeStart] = useState(() => hours ? Date.now() - hours * 60 * 60 * 1000 : 0);
  const drag = useRef<{ pointerId: number; startX: number; startScroll: number; moved: boolean } | null>(null);
  const lanes = useMemo(() => {
    const groups = new Map<string, PersonaJourneyEvent[]>();
    for (const run of runs) {
      if (run.build_id !== buildId) continue;
      for (const record of run.supervisor_results ?? []) {
        const recordedAt = record.recorded_at ?? run.updated_at ?? run.created_at;
        if (rangeStart && recordedAt && (Date.parse(recordedAt) || 0) < rangeStart) continue;
        const journeys = record.response?.persona_journeys ?? [];
        if (journeys.length) {
          for (const [index, journey] of journeys.entries()) {
            const trace = journey.behavior_trace;
            const event = {
              id: `${run.id}:${record.iteration}:${index}`,
              persona: journey.persona_id,
              run,
              iteration: record.iteration,
              recordedAt,
              goal: trace.persona_goal,
              action: trace.current_action,
              decision: trace.decision,
              nextAction: trace.next_action,
            };
            groups.set(journey.persona_id, [...(groups.get(journey.persona_id) ?? []), event]);
          }
          continue;
        }
        // Retain existing timelines from evaluations created before persona_journeys.
        const trace = record.response?.evaluation?.behavior_trace;
        if (!trace || !Object.values(trace).some(Boolean)) continue;
        const personas = new Set<string>();
        for (const step of run.step_results ?? []) {
          if (step.loop_index !== record.iteration || step.phase !== "before_each") continue;
          const cycle = step.result?.insighta_persona_simulator ?? step.result?.persona_cycle;
          if (!cycle || typeof cycle !== "object") continue;
          const active = (cycle as { active_personas?: unknown }).active_personas;
          if (Array.isArray(active)) active.forEach((persona) => {
            if (typeof persona === "string" && persona) personas.add(persona);
          });
        }
        const persona = [...personas].join(" · ") || "—";
        const event = {
          id: `${run.id}:${record.iteration}`,
          persona,
          run,
          iteration: record.iteration,
          recordedAt,
          goal: trace.persona_goal,
          action: trace.current_action,
          decision: trace.decision,
          nextAction: trace.next_action,
        };
        groups.set(persona, [...(groups.get(persona) ?? []), event]);
      }
    }
    return [...groups.entries()]
      .map(([persona, events]) => ({
        persona,
        events: events.sort((left, right) => (Date.parse(left.recordedAt ?? "") || 0) - (Date.parse(right.recordedAt ?? "") || 0)),
      }))
      .sort((left, right) => left.persona.localeCompare(right.persona));
  }, [buildId, rangeStart, runs]);
  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startScroll: event.currentTarget.scrollLeft, moved: false };
  };
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const distance = event.clientX - active.startX;
    if (Math.abs(distance) > 4) active.moved = true;
    event.currentTarget.scrollLeft = active.startScroll - distance;
  };
  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId === event.pointerId) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <section className="panel persona-journeys">
    <h3><SectionInfo title={t.personaJourneys} description={t.personaJourneysHint} /></h3>
    <p className="hint">{t.personaJourneysHint}</p>
    {lanes.length ? <div className="persona-journeys__lanes">
      {lanes.map((lane) => <section className="persona-journeys__lane" key={lane.persona}>
        <header><strong>{lane.persona}</strong><small>{lane.events.length}</small></header>
        <div className="persona-journeys__events" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onClickCapture={(event) => {
          if (!drag.current?.moved) return;
          event.preventDefault();
          event.stopPropagation();
          drag.current = null;
        }}>
          {lane.events.map((event) => <button className="persona-journeys__event" key={event.id} onClick={() => onSelect(event.run)}>
            <time>{compactTimestamp(locale, event.recordedAt)}</time>
            <small>{t.run} {event.run.id} · {t.iteration} #{event.iteration}</small>
            <dl>
              {event.goal && <div><dt>{t.personaGoal}</dt><dd>{event.goal}</dd></div>}
              {event.action && <div><dt>{t.currentAction}</dt><dd>{event.action}</dd></div>}
              {event.decision && <div><dt>{t.currentDecision}</dt><dd>{event.decision}</dd></div>}
              {event.nextAction && <div><dt>{t.nextAction}</dt><dd>{event.nextAction}</dd></div>}
            </dl>
          </button>)}
        </div>
      </section>)}
    </div> : <p className="catalog-empty">{t.noPersonaJourneys}</p>}
  </section>;
}
function Card({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <article className="analytics-chart">
      <h3>
        <SectionInfo title={title} description={description} />
      </h3>
      {children}
    </article>
  );
}

export function Trends({ t }: { t: (typeof copy)["en"] }) {
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    chartHints = localeMessages<ChartHints>(locale, "chartHints"),
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails"),
    [hours, setHours] = useState(24),
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
        <PanelHeader
          title={t.trends}
          description={sectionDetails.iterationImprovementTrend}
        />
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
        <Card title={t.feedbackVolume} description={chartHints.feedbackByBuild}>
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
        <Card title={t.activeTrend} description={chartHints.activeRuns}>
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
      <Card title={t.iterationTrend} description={chartHints.iterationTrend}>
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
                dataKey="acceptable_count"
                name={t.acceptable}
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
        <Card title={t.feedbackStatus} description={chartHints.feedbackStatus}>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data?.feedback_status ?? []} margin={{ left: -18 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" tickFormatter={short} />
              <YAxis allowDecimals={false} />
              <ChartTooltip />
              <Legend />
              <Bar stackId="a" dataKey="proposed" name={t.proposed} fill="#f1d292" />
              <Bar stackId="a" dataKey="acceptable" name={t.acceptable} fill="#79c99e" />
              <Bar stackId="a" dataKey="rejected" name={t.rejected} fill="#eaa89f" />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title={t.issueSeverity} description={chartHints.issueSeverity}>
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
      <Card title={t.runHealth} description={chartHints.runHealth}>
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

function CycleImprovementAI({
  locale,
  build,
  hours,
}: {
  locale: Locale;
  build: string;
  hours: number;
}) {
  const [data, setData] = useState<ImprovementAnalytics>(),
    [analysis, setAnalysis] = useState(""),
    [loading, setLoading] = useState(false),
    t = locales[locale].cycle;
  useEffect(() => {
    api<ImprovementAnalytics>(`/api/improvement-analytics?hours=${hours}`)
      .then((next) => {
        setData(next);
      })
      .catch(() => setData(undefined));
  }, [hours]);
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
      build_id: build,
      locale,
      hours,
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
        </>
      )}
    </section>
  );
}

function StoredState({
  buildId,
  locale,
  t,
}: {
  buildId: string;
  locale: Locale;
  t: (typeof copy)["en"];
}) {
  const [states, setStates] = useState<RunnerState[]>([]);
  useEffect(() => {
    api<RunnerState[]>(`/api/builds/${encodeURIComponent(buildId)}/state`)
      .then(setStates)
      .catch(() => setStates([]));
  }, [buildId]);
  const renderStateValue = (value: unknown, label?: string): ReactNode => {
    if (Array.isArray(value)) {
      return <details className="stored-state__tree-node" open={label === "journey_handoff"}><summary>{label ?? "Array"}<small>{value.length} items</small></summary><ul>{value.map((item, index) => <li key={index}>{renderStateValue(item, String(index))}</li>)}</ul></details>;
    }
    if (value && typeof value === "object") {
      return <details className="stored-state__tree-node" open={label === "journey_handoff"}><summary>{label ?? "Object"}<small>{Object.keys(value as Record<string, unknown>).length} fields</small></summary><ul>{Object.entries(value as Record<string, unknown>).map(([key, item]) => <li key={key}>{renderStateValue(item, key)}</li>)}</ul></details>;
    }
    return <span className="stored-state__tree-leaf"><strong>{label}</strong><code>{value === null ? "null" : String(value)}</code></span>;
  };
  return (
    <section className="panel stored-state">
      <PanelHeader title={t.storedState} description={t.storedStateHint} />
      {states.length ? (
        <div className="stored-state__list">
          {states.map((state) => {
            const personas =
              state.value && typeof state.value === "object" && !Array.isArray(state.value)
                ? (state.value as { personas?: Record<string, unknown> }).personas
                : undefined;
            return (
              <article key={state.name}>
                <header>
                  <span className="stored-state__name">
                    <strong>{state.name}</strong>
                    <em>{state.scope === "build" ? t.buildState : `${t.runnerState}: ${state.runner_id ?? "—"}`}</em>
                  </span>
                  <small>{t.updated} {timestamp(locale, state.updated_at)}</small>
                </header>
                {personas && Object.keys(personas).length > 0 && (
                  <div className="stored-state__personas">
                    {Object.entries(personas).map(([persona, value]) => {
                      const record = value && typeof value === "object" && !Array.isArray(value)
                        ? value as Record<string, unknown>
                        : {};
                      return (
                        <details className="stored-state__persona" key={persona}>
                          <summary><strong>{persona}</strong><span>{String(record.last_action_at ?? "—")}</span><span>{String(record.active ?? "—")}</span></summary>
                          <div className="stored-state__tree"><ul className="stored-state__tree-root">{Object.entries(record).map(([key, item]) => <li key={key}>{renderStateValue(item, key)}</li>)}</ul></div>
                        </details>
                      );
                    })}
                  </div>
                )}
                <details>
                  <summary>{t.rawState}</summary>
                  <pre>{JSON.stringify(state.value, null, 2)}</pre>
                </details>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="catalog-empty">{t.noStoredState}</p>
      )}
    </section>
  );
}
function ImprovementBuildContent({
  runs,
  onStop,
  onRetry,
  onApprove,
  onReject,
  buildId,
  hours,
  onHoursChange,
  onNotice,
}: {
  runs: Run[];
  onStop: (id: string) => void;
  onRetry: (id: string, restartFromFirst: boolean) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  buildId: string;
  hours: number;
  onHoursChange: (hours: number) => void;
  onNotice: (message: string, tone?: "success" | "warning") => void;
}) {
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    t = copy[locale],
    [selectedRun, setSelectedRun] = useState<Run | null>(null),
    [retryingRun, setRetryingRun] = useState<Run | null>(null);
  return (
    <>
      <CycleImprovementAI locale={locale} build={buildId} hours={hours} />
      <FeedbackTrends locale={locale} buildId={buildId} scope="improvements" hours={hours} onHoursChange={onHoursChange} />
      <RelatedRuns
        key={`${buildId}:${hours}`}
        buildId={buildId}
        runs={runs}
        locale={locale}
        t={t}
        hours={hours}
        onStop={onStop}
        onRetryRequest={setRetryingRun}
        onSelect={setSelectedRun}
      />
      <PersonaJourneyTimeline key={`${buildId}:${hours}`} buildId={buildId} runs={runs} locale={locale} t={t} hours={hours} onSelect={setSelectedRun} />
      <IssueManagementSection key={buildId} buildId={buildId} locale={locale} onNotice={onNotice} />
      <StoredState buildId={buildId} locale={locale} t={t} />
      {selectedRun && <EvaluationsPage
        detailOnly
        locale={locale}
        runs={runs}
        initialSelectedRun={selectedRun}
        onSelectedRunClose={() => setSelectedRun(null)}
        onStop={onStop}
        onRetry={onRetry}
        onApprove={onApprove}
        onReject={onReject}
        onEmergencyStop={() => undefined}
        onDeleteRuns={() => Promise.resolve()}
      />}
      <Modal open={Boolean(retryingRun)} title={t.retry} onClose={() => setRetryingRun(null)} className="modal--confirm">
        <div className="modal-form retry-confirmation">
          <p className="confirm-description">{t.retryWarning}</p>
          <div className="modal-actions">
            <button className="reject" onClick={() => { if (retryingRun) onRetry(retryingRun.id, false); setRetryingRun(null); }}>{t.resume}</button>
            <button className="approve" onClick={() => { if (retryingRun) onRetry(retryingRun.id, true); setRetryingRun(null); }}>{t.restart}</button>
          </div>
        </div>
      </Modal>
    </>
  );
}

export function ImprovementsPage({
  runs,
  onStop,
  onRetry,
  onApprove,
  onReject,
  onNotice,
}: {
  runs: Run[];
  onStop: (id: string) => void;
  onRetry: (id: string, restartFromFirst: boolean) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onNotice: (message: string, tone?: "success" | "warning") => void;
}) {
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    t = copy[locale],
    [builds, setBuilds] = useState<Build[]>([]),
    [buildId, setBuildId] = useState(""),
    [hours, setHours] = useState(24),
    [initialLoading, setInitialLoading] = useState(true);
  const sortedBuilds = useMemo(
    () =>
      [...builds].sort(
        (left, right) =>
          Number(right.starred) - Number(left.starred) ||
          lastRunTimestamp(right) - lastRunTimestamp(left) ||
          left.name.localeCompare(right.name),
      ),
    [builds],
  );
  useEffect(() => {
    api<Build[]>("/api/builds")
      .then((next) => {
        setBuilds(next);
        const fallback = [...next].sort(
          (left, right) => Number(right.starred) - Number(left.starred) || lastRunTimestamp(right) - lastRunTimestamp(left) || left.name.localeCompare(right.name),
        )[0]?.id || "";
        setBuildId((current) => current || preferredBuildId("improvements", next, fallback));
      })
      .catch(() => setBuilds([]))
      .finally(() => setInitialLoading(false));
  }, []);
  useEffect(() => savePreferredBuildId("improvements", buildId), [buildId]);
  if (initialLoading) return <>
    <SectionSkeleton rows={1} />
    <SectionSkeleton rows={3} />
    <SectionSkeleton rows={3} />
    <SectionSkeleton rows={4} />
    <SectionSkeleton rows={4} />
    <SectionSkeleton rows={3} />
  </>;
  return (
    <>
      <section className="improvements-build-selector">
        <label>
          {t.selectBuild}
          <select value={buildId} onChange={(event) => setBuildId(event.target.value)}>
            {sortedBuilds.map((item) => (
              <option key={item.id} value={item.id}>
                {item.starred ? "★ " : ""}{item.name} ({compactTimestamp(locale, item.last_run_at)})
              </option>
            ))}
          </select>
        </label>
        <label>
          {t.range}
          <select value={hours} onChange={(event) => setHours(Number(event.target.value))}>
            <option value={24}>24h</option>
            <option value={72}>3d</option>
            <option value={168}>7d</option>
            <option value={720}>30d</option>
            <option value={0}>{t.unlimited}</option>
          </select>
        </label>
      </section>
      {buildId && <ImprovementBuildContent
        key={buildId}
        runs={runs}
        onStop={onStop}
        onRetry={onRetry}
        onApprove={onApprove}
        onReject={onReject}
        buildId={buildId}
        hours={hours}
        onHoursChange={setHours}
        onNotice={onNotice}
      />}
    </>
  );
}
