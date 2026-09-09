import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Sparkles } from "lucide-react";
import type {
  Dashboard,
  ImprovementAnalytics,
  QuickStart,
} from "../../domain/models";
import { MetricCard, PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { StatusBadge } from "../../components/ui/status-badge";
import {
  intlLocales,
  localeMessages,
  locales,
  type Locale,
} from "../../locales";
import { api } from "../../services/api";
import { FeedbackTrends } from "./feedback-trends";

type HeroCopy = {
  title: string;
  description: string;
  quickStart: string;
  quickStartHint: string;
  quickStarts: string;
  quickStartsHint: string;
};
type OperationsCopy = {
  title: string;
  description: string;
  tooltip: string;
  feedback: string;
  accepted: string;
  issues: string;
  score: string;
  trend: string;
  none: string;
  previous: string;
};
type DashboardHelp = { trend: string };
type OverviewCopy = { title: string; description: string };

function relativeRunTime(value: string | undefined, locale: Locale) {
  if (!value) return "—";
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime()),
    minutes = Math.floor(elapsed / 60000);
  const [amount, unit] =
    minutes < 60
      ? ([minutes, "minute"] as const)
      : minutes < 1440
        ? ([Math.floor(minutes / 60), "hour"] as const)
        : ([Math.floor(minutes / 1440), "day"] as const);
  return new Intl.RelativeTimeFormat(intlLocales[locale], {
    numeric: "auto",
  }).format(-amount, unit);
}

function OperationalHealth({ locale }: { locale: Locale }) {
  const [analytics, setAnalytics] = useState<ImprovementAnalytics>();
  useEffect(() => {
    const refresh = () =>
      api<ImprovementAnalytics>("/api/improvement-analytics?hours=24")
        .then(setAnalytics)
        .catch(() => setAnalytics(undefined));
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => window.clearInterval(timer);
  }, []);
  const copy = localeMessages<OperationsCopy>(locale, "dashboardOperations"),
    help = localeMessages<DashboardHelp>(locale, "dashboardHelp"),
    summary = analytics?.operational_summary;
  const trend = useMemo(() => {
    const grouped = new Map<
      string,
      { time: string; feedback: number; accepted: number }
    >();
    for (const item of analytics?.iteration_trends ?? [])
      for (const point of item.points) {
        const time = new Date(point.recorded_at).toISOString().slice(0, 13);
        const row = grouped.get(time) ?? { time, feedback: 0, accepted: 0 };
        row.feedback += point.feedback_count;
        row.accepted += point.accepted_count;
        grouped.set(time, row);
      }
    return [...grouped.values()].sort((a, b) => a.time.localeCompare(b.time));
  }, [analytics]);
  const score =
    summary?.average_score === null || summary?.average_score === undefined
      ? "—"
      : `${summary.average_score}/10`;
  const delta =
    summary?.score_delta === null || summary?.score_delta === undefined
      ? ""
      : ` ${summary.score_delta > 0 ? "+" : ""}${summary.score_delta}`;
  return (
    <section className="panel dashboard-health">
      <div className="panel-head">
        <div>
          <p className="eyebrow">IMPROVEMENT RESULTS</p>
          <h2>
            <SectionInfo title={copy.title} description={copy.tooltip} />
          </h2>
          <p className="hint">{copy.description}</p>
        </div>
      </div>
      <div className="dashboard-health-metrics">
        <MetricCard label={copy.feedback} value={`${summary?.feedback ?? 0}`} />
        <MetricCard label={copy.accepted} value={`${summary?.accepted ?? 0}`} />
        <MetricCard label={copy.issues} value={`${summary?.issues ?? 0}`} />
        <MetricCard
          label={copy.score}
          value={score}
          detail={delta ? `${delta} ${copy.previous}` : undefined}
        />
      </div>
      <article className="dashboard-feedback-chart">
        <h3>
          <SectionInfo title={copy.trend} description={help.trend} />
        </h3>
        {trend.length ? (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={trend} margin={{ left: -20 }}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="time"
                tickFormatter={(value) =>
                  new Date(`${value}:00:00Z`).toLocaleTimeString(
                    intlLocales[locale],
                    { hour: "2-digit", minute: "2-digit" },
                  )
                }
              />
              <YAxis allowDecimals={false} />
              <Tooltip
                labelFormatter={(value) =>
                  new Date(`${String(value)}:00:00Z`).toLocaleString()
                }
              />
              <Legend />
              <Bar
                dataKey="feedback"
                name={copy.feedback}
                fill="#f1d292"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="accepted"
                name={copy.accepted}
                fill="#79c99e"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="hint">{copy.none}</p>
        )}
      </article>
    </section>
  );
}

export function DashboardPage({
  data,
  onOpenBuild,
  onOpenQuickStart,
  onOpenRun,
  locale,
}: {
  data: Dashboard | null;
  onOpenBuild: (id?: string) => void;
  onOpenQuickStart: (id?: string) => void;
  onOpenRun: () => void;
  locale: Locale;
}) {
  const t = locales[locale].common,
    h = localeMessages<HeroCopy>(locale, "dashboardHero"),
    overview = localeMessages<OverviewCopy>(locale, "dashboardOverview"),
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails"),
    dashboard = locales[locale].dashboardUi,
    quickStartLabels = localeMessages<
      Record<string, { name: string; description: string }>
    >(locale, "quickStartLabels"),
    recent = data?.recent_runs ?? [],
    errors = recent.filter((run) => run.status === "failed").length,
    [quickStarts, setQuickStarts] = useState<QuickStart[]>([]);
  useEffect(() => {
    api<QuickStart[]>("/api/quick-starts")
      .then((items) => setQuickStarts(items.slice(0, 4)))
      .catch(() => setQuickStarts([]));
  }, []);
  const openBuild = (id?: string) => {
    if (id) sessionStorage.setItem("orbit.selectedBuild", id);
    onOpenBuild(id);
  };
  return (
    <>
      <section className="dashboard-hero">
        <p>ORBIT CONTROL PLANE</p>
        <strong>{h.title}</strong>
        <span>{h.description}</span>
        <small>{h.quickStartHint}</small>
        <div className="dashboard-hero-actions">
          <button className="approve" onClick={() => onOpenQuickStart()}>
            {h.quickStart}
          </button>
        </div>
      </section>
      {quickStarts.length > 0 && (
        <section className="dashboard-quick-starts">
          <div className="panel-head">
            <div>
              <h2>{h.quickStarts}</h2>
              <p className="hint">{h.quickStartsHint}</p>
            </div>
          </div>
          <div className="dashboard-quick-starts__grid">
            {quickStarts.map((item) => (
              <button
                key={item.id}
                className="dashboard-quick-start"
                onClick={() => onOpenQuickStart(item.id)}
              >
                <Sparkles size={16} />
                <span>
                  <strong>
                    {quickStartLabels[item.id]?.name ?? item.name}
                  </strong>
                  <small>
                    {quickStartLabels[item.id]?.description ?? item.description}
                  </small>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="panel dashboard-overview">
        <PanelHeader title={overview.title} description={sectionDetails.dashboardOverview} />
        <p className="hint">{overview.description}</p>
        <div className="metrics">
        <MetricCard
          label={t.totalEval}
          value={`${data?.metrics.evaluation_builds ?? 0}`}
        />
        <MetricCard
          label={t.completedEval}
          value={`${data?.metrics.completed_evaluations ?? 0}`}
        />
        <MetricCard
          label={t.totalRunning}
          value={`${data?.active_runs.length ?? 0}`}
        />
        <MetricCard label={t.totalError} value={`${errors}`} />
        </div>
      </section>
      <section className="recent-evaluations">
        {recent.map((run) => {
          const active = ["queued", "running", "awaiting_approval"].includes(
              run.status,
            ),
            completed = ["succeeded", "failed", "cancelled"].includes(
              run.status,
            ),
            eventTime = completed ? run.finished_at : run.created_at,
            eventLabel = completed ? dashboard.completed : dashboard.created;
          return (
            <button
              className="evaluation-card"
              key={run.id}
              onClick={() =>
                active ? onOpenRun() : openBuild(run.evaluation_build_id)
              }
            >
              <small>{`${eventLabel} · ${relativeRunTime(eventTime, locale)}`}</small>
              <strong>{run.evaluation_build_name ?? run.workflow_name}</strong>
              <span>{run.current_phase ?? run.status}</span>
              <StatusBadge value={run.status} />
            </button>
          );
        })}
      </section>
      <OperationalHealth locale={locale} />
      <FeedbackTrends locale={locale} />
    </>
  );
}
