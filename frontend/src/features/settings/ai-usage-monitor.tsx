import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Locale } from "../../locales";
import { intlLocales, localeMessages } from "../../locales";
import { DataTable, type Column } from "../../components/ui/data-table";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { api } from "../../services/api";

type UsageEvent = { id: string; time: string; model: string; request_mode: string; status: number; failed: boolean; input_tokens: number; output_tokens: number; total_tokens: number; input_chars: number; output_chars: number; tool_count: number; duration_ms: number; error: string; limit_requests?: string; remaining_requests?: string; limit_tokens?: string; remaining_tokens?: string; retry_after?: string };
type AiUsage = { minutes: number; summary: { requests: number; tokens: number; errors: number; success_rate: number; average_duration_ms: number; rpm: number; tpm: number; rate_interval_seconds: number }; limits: Record<string, string | undefined>; timeline: ({ time: string; requests: number; tokens: number } & Record<string, string | number>)[]; profiles: string[]; events: UsageEvent[] };
type Copy = { title: string; description: string; range: string; refresh: string; rpm: string; tpm: string; successRate: string; averageLatency: string; requests: string; tokens: string; limits: string; remainingRequests: string; remainingTokens: string; retryAfter: string; requestTrend: string; tokenTrend: string; recentCalls: string; time: string; model: string; status: string; usage: string; characters: string; latency: string; details: string; requestType: string; promptRequest: string; toolResultRequest: string; input: string; output: string; tools: string; empty: string; unavailable: string; noLimitData: string };

const format = (value: number) => new Intl.NumberFormat().format(value);
const tick = (value: string, locale: Locale) => new Date(value).toLocaleTimeString(intlLocales[locale], { hour: "2-digit", minute: "2-digit" });
const duration = (seconds: number) => seconds >= 3600 ? `${seconds / 3600}h` : `${seconds / 60}m`;
const profileColors = ["#8fb8ff", "#79c99e", "#f1d292", "#d7b7ff", "#eaa89f"];

export function AiUsageMonitor({ locale }: { locale: Locale }) {
  const t = localeMessages<Copy>(locale, "aiUsage");
  const [minutes, setMinutes] = useState(60), [data, setData] = useState<AiUsage>(), [selected, setSelected] = useState<UsageEvent>(), [loading, setLoading] = useState(false);
  const load = () => {
    setLoading(true);
    api<AiUsage>(`/api/ai-usage?minutes=${minutes}`).then(setData).catch(() => setData(undefined)).finally(() => setLoading(false));
  };
  useEffect(() => {
    const refresh = () => {
      api<AiUsage>(`/api/ai-usage?minutes=${minutes}`).then(setData).catch(() => setData(undefined));
    };
    const start = window.setTimeout(refresh, 0);
    const id = window.setInterval(refresh, 15_000);
    return () => { window.clearTimeout(start); window.clearInterval(id); };
  }, [minutes]);
  const columns = useMemo<Column<UsageEvent>[]>(() => [
    { id: "time", header: t.time, render: (row) => new Date(row.time).toLocaleTimeString(intlLocales[locale]), sortValue: (row) => row.time },
    { id: "model", header: t.model, render: (row) => row.model || "—", sortValue: (row) => row.model },
    { id: "status", header: t.status, render: (row) => <span className={row.failed || row.status >= 400 ? "ai-usage-error" : ""}>{row.status || (row.failed ? "Error" : "—")}</span>, sortValue: (row) => row.status },
    { id: "usage", header: t.usage, render: (row) => `${format(row.input_tokens)} / ${format(row.output_tokens)}`, sortValue: (row) => row.total_tokens },
    { id: "characters", header: t.characters, render: (row) => `${format(row.input_chars)} / ${format(row.output_chars)}`, sortValue: (row) => row.input_chars + row.output_chars },
    { id: "latency", header: t.latency, render: (row) => `${format(row.duration_ms)} ms`, sortValue: (row) => row.duration_ms },
  ], [locale, t]);
  const limits = data?.limits;
  const rateDetail = data ? `${duration(data.summary.rate_interval_seconds)} aggregation · ${duration(data.minutes * 60)} window` : "";
  return <section className="panel app-settings ai-usage-monitor">
    <PanelHeader title={<SectionInfo title={t.title} description={t.description} />} action={<div className="setting-actions"><label>{t.range}<select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}><option value={15}>15m</option><option value={60}>1h</option><option value={1440}>24h</option></select></label><button className="ghost" type="button" onClick={load} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} />{t.refresh}</button></div>} />
    {!data ? <p className="hint section-description">{t.unavailable}</p> : <>
      <div className="ai-usage-metrics">
        <Metric label={t.rpm} value={format(data.summary.rpm)} detail={rateDetail} /><Metric label={t.tpm} value={format(data.summary.tpm)} detail={rateDetail} />
        <Metric label={t.successRate} value={`${data.summary.success_rate}%`} warning={data.summary.errors > 0} /><Metric label={t.averageLatency} value={`${format(data.summary.average_duration_ms)} ms`} />
      </div>
      {data.summary.errors > 0 && <p className="operational-prompt-warning ai-usage-warning"><AlertTriangle size={16} />{data.summary.errors} {t.requests}</p>}
      <div className="analytics-grid">
        <article className="analytics-chart"><h3>{t.requestTrend}</h3><ResponsiveContainer width="100%" height={190}><AreaChart data={data.timeline} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="time" tickFormatter={(value) => tick(String(value), locale)} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString(intlLocales[locale])} /><Legend />{data.profiles.map((profile, index) => <Area key={profile} type="monotone" dataKey={profile} name={profile} stroke={profileColors[index % profileColors.length]} fill={`${profileColors[index % profileColors.length]}33`} />)}</AreaChart></ResponsiveContainer></article>
        <article className="analytics-chart"><h3>{t.tokenTrend}</h3><ResponsiveContainer width="100%" height={190}><AreaChart data={data.timeline} margin={{ left: -18 }}><CartesianGrid vertical={false} /><XAxis dataKey="time" tickFormatter={(value) => tick(String(value), locale)} /><YAxis allowDecimals={false} /><Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString(intlLocales[locale])} /><Legend />{data.profiles.map((profile, index) => <Area key={profile} type="monotone" dataKey={`tokens:${profile}`} name={profile} stroke={profileColors[index % profileColors.length]} fill={`${profileColors[index % profileColors.length]}33`} />)}</AreaChart></ResponsiveContainer></article>
      </div>
      {limits?.remaining_requests || limits?.remaining_tokens ? <div className="ai-usage-limits"><strong>{t.limits}</strong><span>{t.remainingRequests}: {limits.remaining_requests ?? "—"}{limits.limit_requests ? ` / ${limits.limit_requests}` : ""} · {t.remainingTokens}: {limits.remaining_tokens ?? "—"}{limits.limit_tokens ? ` / ${limits.limit_tokens}` : ""}{limits.retry_after ? ` · ${t.retryAfter}: ${limits.retry_after}s` : ""}</span></div> : <p className="hint section-description">{t.noLimitData}</p>}
      <div className="ai-usage-table"><h3>{t.recentCalls}</h3><div className="ai-usage-table-scroll"><DataTable columns={columns} rows={data.events} empty={t.empty} onRowClick={setSelected} gridTemplateColumns="minmax(100px,.8fr) minmax(130px,1.2fr) 76px minmax(110px,1fr) minmax(110px,1fr) 100px" /></div></div>
      {selected && <div className="ai-usage-detail"><strong>{t.details}</strong><span>{t.requestType}: {selected.request_mode === "tool_result" ? t.toolResultRequest : t.promptRequest} · {t.input}: {format(selected.input_tokens)} tokens / {format(selected.input_chars)} chars · {t.output}: {format(selected.output_tokens)} tokens / {format(selected.output_chars)} chars · {t.tools}: {selected.tool_count}</span>{selected.error && <span className="ai-usage-error">{selected.error}</span>}</div>}
    </>}
  </section>;
}

function Metric({ label, value, detail, warning = false }: { label: string; value: string; detail?: string; warning?: boolean }) { return <div><span>{label}</span><strong className={warning ? "ai-usage-error" : ""}>{value}</strong>{detail && <small>{detail}</small>}</div>; }
