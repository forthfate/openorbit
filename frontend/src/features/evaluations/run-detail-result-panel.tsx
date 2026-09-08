import type { ReactNode } from "react";
import { intlLocales, type Locale } from "../../locales";

type Messages = Record<string, string | undefined>;
type RecordItem = Record<string, unknown>;
type BehaviorSummary = { iteration: number; recordedAt?: string; summary: string };
const time = (locale: Locale, value?: string) => value ? new Intl.DateTimeFormat(intlLocales[locale], { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value)) : "—";

function ResultList({ items, kind, locale, empty }: { items: RecordItem[]; kind: "improvement" | "issue"; locale: Locale; empty: string }) {
  return <div className="result-items">{items.length ? items.map((item, index) => {
    const status = String(item.status ?? "—"), severity = String(item.severity ?? "—"), reportedAt = typeof item.reported_at === "string" ? item.reported_at : undefined;
    return <article className="result-row" key={index}><time className="result-row__time">{time(locale, reportedAt)}</time><div className="result-row__body"><strong>{String(item.title ?? "—")}</strong><p>{String(kind === "improvement" ? (item.rationale ?? "—") : (item.evidence ?? "—"))}</p></div><div className="result-row__metrics"><span><small>Iteration</small><b>#{String(item.__iteration ?? "—")}</b></span>{kind === "improvement" ? <><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span><span><small>Score</small><b>{String(item.effect_score ?? item.score ?? "—")}</b></span><span><small>Attempted</small><b>{item.attempted === true || status === "adopted" ? "Yes" : "No"}</b></span></> : <><span><small>Severity</small><b className={`decision decision--${severity}`}>{severity}</b></span><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span></>}</div></article>;
  }) : <p className="hint result-empty">{empty}</p>}</div>;
}

export function EvaluationResultPanel({ error, records, summaries, improvements, issues, l, locale }: { error?: ReactNode; records: unknown[]; summaries: BehaviorSummary[]; improvements: RecordItem[]; issues: RecordItem[]; l: Messages; locale: Locale }) {
  return <>{error}{records.length ? <>{summaries.length > 0 && <section className="result-behavior-summaries"><h3>{l.observedBehavior}</h3><div className="result-items">{summaries.map((item) => <article className="result-row" key={item.iteration}><time className="result-row__time">{time(locale, item.recordedAt)}</time><div className="result-row__body"><p>{item.summary}</p></div><div className="result-row__metrics"><span><small>Iteration</small><b>#{item.iteration}</b></span></div></article>)}</div></section>}<section><h3>{l.proposals}</h3><ResultList locale={locale} kind="improvement" items={improvements} empty={l.noResults ?? ""} /></section><section><h3>{l.issues}</h3><ResultList locale={locale} kind="issue" items={issues} empty={l.noResults ?? ""} /></section></> : <p className="hint result-empty">{l.noMatchingResults}</p>}</>;
}
