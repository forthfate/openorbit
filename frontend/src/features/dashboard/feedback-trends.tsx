import { useEffect, useState, type ReactNode } from "react";
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
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ImprovementAnalytics } from "../../domain/models";
import { SectionInfo } from "../../components/ui/section-info";
import { api } from "../../services/api";
import { intlLocales, localeMessages, type Locale } from "../../locales";

type FeedbackTrendsCopy = {
  title: string; description?: string; range: string; evaluation: string; feedbackVolume: string;
  iterationTrend: string; activeTrend: string; feedbackStatus: string;
  issueSeverity: string; runHealth: string; accepted: string; score: string;
  feedbackCount: string; activeCount: string; noIterationFeedback: string;
  adopted: string; rejected: string; proposed: string; low: string; medium: string;
  high: string; critical: string; succeeded: string; failed: string;
  cancelled: string; running: string;
};

const tick = (value: string, locale: Locale) =>
  new Date(value).toLocaleTimeString(intlLocales[locale], {
    hour: "2-digit",
    minute: "2-digit",
  });

function Card({ title, locale, children }: { title: string; locale: Locale; children: ReactNode }) {
  const hints = localeMessages<Record<string, string>>(locale, "chartHints");
  return <article className="analytics-chart"><h3>{hints[title] ? <SectionInfo title={title} description={hints[title]} /> : title}</h3>{children}</article>;
}

export function FeedbackTrends({ locale, buildId, scope = "dashboard" }: { locale: Locale; buildId?: string; scope?: "dashboard" | "improvements" }) {
  const t = localeMessages<FeedbackTrendsCopy>(locale, scope === "dashboard" ? "dashboardFeedbackTrends" : "improvementEvaluationTrends"),
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails");
  const [hours, setHours] = useState(24), [build, setBuild] = useState(""), [data, setData] = useState<ImprovementAnalytics>();
  useEffect(() => {
    api<ImprovementAnalytics>(`/api/improvement-analytics?hours=${hours}`).then((next) => {
      setData(next);
      setBuild((current) => next.iteration_trends.some((item) => item.build_id === current) ? current : (next.iteration_trends.find((item) => item.points.length)?.build_id ?? next.iteration_trends[0]?.build_id ?? ""));
    }).catch(() => setData(undefined));
  }, [hours]);
  const selectedBuild = buildId || build,
    trend = data?.iteration_trends.find((item) => item.build_id === selectedBuild);
  const short = (value: string) => value.length > 18 ? `${value.slice(0, 18)}…` : value;
  return <section className={`panel improvement-trends ${scope === "dashboard" ? "dashboard-feedback-trends" : "evaluation-feedback-trends"}`}>
    <div className="trend-head"><div><h2><SectionInfo title={t.title} description={scope === "dashboard" ? sectionDetails.dashboardFeedbackTrends : sectionDetails.iterationImprovementTrend} /></h2>{t.description && <p className="hint section-description">{t.description}</p>}</div><label>{t.range}<select value={hours} onChange={(event) => setHours(Number(event.target.value))}><option value={24}>24h</option><option value={72}>3d</option><option value={168}>7d</option><option value={720}>30d</option></select></label></div>
    <div className="analytics-grid">
      {scope === "dashboard" && <Card title={t.feedbackVolume} locale={locale}><ResponsiveContainer width="100%" height={250}><BarChart data={data?.feedback_by_build ?? []} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="name" tickFormatter={short} /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="feedback_count" name={t.feedbackCount} fill="var(--accent)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></Card>}
      {scope === "dashboard" && <Card title={t.activeTrend} locale={locale}><ResponsiveContainer width="100%" height={250}><AreaChart data={data?.active_evaluations ?? []} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="time" tickFormatter={(value) => tick(String(value), locale)} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString(intlLocales[locale])} /><Area type="monotone" dataKey="count" name={t.activeCount} stroke="var(--accent)" fill="var(--surface-raised)" dot={{ r: 3, fill: "var(--accent)", stroke: "var(--surface)" }} /></AreaChart></ResponsiveContainer></Card>}
    </div>
    {scope === "improvements" && <Card title={t.iterationTrend} locale={locale}>{trend?.points.length ? <ResponsiveContainer width="100%" height={280}><ComposedChart data={trend.points} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="iteration" tickFormatter={(value) => `#${value}`} /><YAxis yAxisId="count" allowDecimals={false} /><YAxis yAxisId="score" orientation="right" domain={[0, 10]} /><Tooltip /><Legend /><Bar yAxisId="count" dataKey="accepted_count" name={t.accepted} fill="#79c99e" /><Line yAxisId="score" type="monotone" dataKey="score" name={t.score} stroke="#8fb8ff" strokeWidth={3} /></ComposedChart></ResponsiveContainer> : <p className="hint">{t.noIterationFeedback}</p>}</Card>}
    {scope === "dashboard" && <div className="analytics-grid"><Card title={t.feedbackStatus} locale={locale}><ResponsiveContainer width="100%" height={250}><BarChart data={data?.feedback_status ?? []} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="name" tickFormatter={short} /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Bar stackId="a" dataKey="proposed" name={t.proposed} fill="#f1d292" /><Bar stackId="a" dataKey="adopted" name={t.adopted} fill="#79c99e" /><Bar stackId="a" dataKey="rejected" name={t.rejected} fill="#eaa89f" /></BarChart></ResponsiveContainer></Card><Card title={t.issueSeverity} locale={locale}><ResponsiveContainer width="100%" height={250}><AreaChart data={data?.issue_severity ?? []} margin={{ left: -18 }}><XAxis dataKey="time" tickFormatter={(value) => tick(String(value), locale)} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString(intlLocales[locale])} /><Legend /><Area stackId="a" type="monotone" dataKey="low" name={t.low} fill="#79c99e" stroke="#79c99e" /><Area stackId="a" type="monotone" dataKey="medium" name={t.medium} fill="#f1d292" stroke="#f1d292" /><Area stackId="a" type="monotone" dataKey="high" name={t.high} fill="#e49a64" stroke="#e49a64" /><Area stackId="a" type="monotone" dataKey="critical" name={t.critical} fill="#eaa89f" stroke="#eaa89f" /></AreaChart></ResponsiveContainer></Card></div>}
    {scope === "dashboard" && <Card title={t.runHealth} locale={locale}><ResponsiveContainer width="100%" height={250}><BarChart data={data?.run_health ?? []} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="name" tickFormatter={short} /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Bar stackId="a" dataKey="succeeded" name={t.succeeded} fill="#79c99e" /><Bar stackId="a" dataKey="failed" name={t.failed} fill="#eaa89f" /><Bar stackId="a" dataKey="cancelled" name={t.cancelled} fill="#9ca7b8" /><Bar stackId="a" dataKey="running" name={t.running} fill="#8fb8ff" /></BarChart></ResponsiveContainer></Card>}
  </section>;
}
