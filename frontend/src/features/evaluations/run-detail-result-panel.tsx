import { useState, type ReactNode } from "react";
import { FileSearch } from "lucide-react";
import { intlLocales, type Locale } from "../../locales";

type Messages = Record<string, string | undefined>;
type RecordItem = Record<string, unknown>;
type BehaviorTrace = {
  iteration: number;
  recordedAt?: string;
  summary?: string;
  trace?: { persona_goal?: string; current_action?: string; decision?: string; next_action?: string; evidence?: string; expectation?: string; interpretation?: string; impact?: string; next_step?: string; purpose?: string; rationale?: string; observation?: string };
};
const time = (locale: Locale, value?: string) => value ? new Intl.DateTimeFormat(intlLocales[locale], { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value)) : "—";

function ResultList({ items, kind, locale, empty }: { items: RecordItem[]; kind: "improvement" | "issue"; locale: Locale; empty: string }) {
  return <div className="result-items result-items--scrollable">{items.length ? items.map((item, index) => {
    const status = String(item.status ?? "—"), severity = String(item.severity ?? "—"), reportedAt = typeof item.reported_at === "string" ? item.reported_at : undefined;
    return <article className="result-row" key={index}><time className="result-row__time">{time(locale, reportedAt)}</time><div className="result-row__body"><strong>{String(item.title ?? "—")}</strong><p>{String(kind === "improvement" ? (item.rationale ?? "—") : (item.evidence ?? "—"))}</p></div><div className="result-row__metrics"><span><small>Iteration</small><b>#{String(item.__iteration ?? "—")}</b></span>{kind === "improvement" ? <><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span><span><small>Score</small><b>{String(item.effect_score ?? item.score ?? "—")}</b></span><span><small>Attempted</small><b>{item.attempted === true || status === "adopted" ? "Yes" : "No"}</b></span></> : <><span><small>Severity</small><b className={`decision decision--${severity}`}>{severity}</b></span><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span></>}</div></article>;
  }) : <p className="hint result-empty">{empty}</p>}</div>;
}

export function EvaluationResultPanel({ error, records, summaries, improvements, issues, l, locale }: { error?: ReactNode; records: unknown[]; summaries: BehaviorTrace[]; improvements: RecordItem[]; issues: RecordItem[]; l: Messages; locale: Locale }) {
  const [evidenceIteration, setEvidenceIteration] = useState<number | null>(null);
  const traceFields = (item: BehaviorTrace) => {
    if (!item.trace) return [];
    const trace = item.trace;
    const fields = trace.current_action && trace.decision ? [
      [l.tracePersonaGoal, trace.persona_goal],
      [l.traceSessionAction, trace.current_action],
      [l.traceCurrentDecision, trace.decision],
      [l.traceNextAction, trace.next_action],
    ] : trace.current_action ? [
      [l.tracePersonaGoal, trace.persona_goal],
      [l.traceCurrentAction, trace.current_action],
      [l.traceNextAction, trace.next_action],
    ] : trace.persona_goal ? [
      [l.tracePersonaGoal, trace.persona_goal],
      [l.traceExpectation, trace.expectation],
      [l.traceInterpretation, trace.interpretation],
      [l.traceEvidence, trace.evidence],
      [l.traceImpact, trace.impact],
      [l.traceNextStep, trace.next_step],
    ] : [
      [l.tracePurpose, trace.purpose],
      [l.traceRationale, trace.rationale],
      [l.traceObservation, trace.observation],
      [l.traceDecision, trace.decision],
      [l.traceNextAction, trace.next_action],
    ];
    return fields.filter((field): field is [string | undefined, string] => Boolean(field[1]));
  };
  return <>{error}{records.length ? <>{summaries.length > 0 && <section className="result-behavior-summaries"><h3>{l.observedBehavior}</h3><div className="result-items result-items--scrollable">{summaries.map((item) => <article className="result-row result-behavior-trace" key={item.iteration}><time className="result-row__time">{time(locale, item.recordedAt)}</time><div className="result-row__body">{traceFields(item).length ? <><dl>{traceFields(item).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{evidenceIteration === item.iteration && item.trace?.evidence && <section className="result-trace-evidence"><strong>{l.traceEvidence}</strong><p>{item.trace.evidence}</p></section>}</> : <p>{item.summary}</p>}</div><div className="result-row__metrics"><span><small>Iteration</small><b>#{item.iteration}</b></span>{item.trace?.evidence && <button className="ghost icon-button" type="button" aria-label={evidenceIteration === item.iteration ? l.hideEvidence : l.viewEvidence} title={evidenceIteration === item.iteration ? l.hideEvidence : l.viewEvidence} onClick={() => setEvidenceIteration((current) => current === item.iteration ? null : item.iteration)}><FileSearch size={16} /></button>}</div></article>)}</div></section>}<section><h3>{l.proposals}</h3><ResultList locale={locale} kind="improvement" items={improvements} empty={l.noResults ?? ""} /></section><section><h3>{l.issues}</h3><ResultList locale={locale} kind="issue" items={issues} empty={l.noResults ?? ""} /></section></> : <p className="hint result-empty">{l.noMatchingResults}</p>}</>;
}
