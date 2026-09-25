import { type ReactNode } from "react";
import type { RunStepResult } from "../../domain/models";
import { EvidenceViewer, type EvidenceArtifact, visualEvidenceArtifacts } from "../../components/ui/evidence-viewer";
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

function browserJourney(result?: Record<string, unknown>) {
  if (!result) return undefined;
  const direct = result.browser_journey;
  if (direct && typeof direct === "object") return direct as { results?: EvidenceArtifact[] };
  for (const key of ["user_journey", "improvement_cycle"]) {
    const cycle = result[key];
    if (!cycle || typeof cycle !== "object") continue;
    const evidence = (cycle as { evidence?: unknown }).evidence;
    if (evidence && typeof evidence === "object") return evidence as { results?: EvidenceArtifact[] };
  }
  return undefined;
}

function ResultList({ items, kind, locale, empty, l }: { items: RecordItem[]; kind: "improvement" | "issue"; locale: Locale; empty: string; l: Messages }) {
  return <div className="result-items result-items--scrollable">{items.length ? items.map((item, index) => {
    const status = String(item.status ?? "—"), severity = String(item.severity ?? "—"), reportedAt = typeof item.reported_at === "string" ? item.reported_at : undefined;
    return <article className="result-row" key={index}><time className="result-row__time">{time(locale, reportedAt)}</time><div className="result-row__body"><strong>{String(item.title ?? "—")}</strong><p>{String(kind === "improvement" ? (item.rationale ?? "—") : (item.evidence ?? "—"))}</p></div><div className="result-row__metrics"><span><small>{l.resultIteration}</small><b>#{String(item.__iteration ?? "—")}</b></span>{kind === "improvement" ? <><span><small>{l.resultStatus}</small><b className={`decision decision--${status}`}>{status}</b></span><span><small>{l.resultScore}</small><b>{String(item.effect_score ?? item.score ?? "—")}</b></span><span><small>{l.resultAttempted}</small><b>{item.attempted === true || ["adopted", "accepted"].includes(status) ? l.resultYes : l.resultNo}</b></span></> : <><span><small>{l.resultSeverity}</small><b className={`decision decision--${severity}`}>{severity}</b></span><span><small>{l.resultStatus}</small><b className={`decision decision--${status}`}>{status}</b></span></>}</div></article>;
  }) : <p className="hint result-empty">{empty}</p>}</div>;
}

export function EvaluationResultPanel({ error, records, summaries, steps, runId, improvements, issues, l, locale }: { error?: ReactNode; records: unknown[]; summaries: BehaviorTrace[]; steps: RunStepResult[]; runId: string; improvements: RecordItem[]; issues: RecordItem[]; l: Messages; locale: Locale }) {
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
  const artifactsFor = (iteration: number) => steps
    .filter((step) => step.loop_index === iteration)
    .flatMap((step) => [...(browserJourney(step.result)?.results ?? []), ...visualEvidenceArtifacts(step.data_files ?? [])]);
  return <>{error}{records.length ? <>{summaries.length > 0 && <section className="result-behavior-summaries"><h3>{l.observedBehavior}</h3><div className="result-items result-items--scrollable">{summaries.map((item) => { const artifacts = artifactsFor(item.iteration); return <article className="result-row result-behavior-trace" key={item.iteration}><time className="result-row__time">{time(locale, item.recordedAt)}</time><div className="result-row__body">{traceFields(item).length ? <dl>{traceFields(item).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p>{item.summary}</p>}</div><div className="result-row__metrics"><span className="result-row__iteration"><small>{l.resultIteration}</small><b>#{item.iteration}</b></span><EvidenceViewer className="result-row__evidence" runId={runId} iteration={item.iteration} artifacts={artifacts} imageLabel={l.viewImageEvidence ?? ""} htmlLabel={l.viewHtmlEvidence ?? ""} imageTitle={l.imageEvidence ?? ""} htmlTitle={l.htmlEvidence ?? ""} /></div></article>; })}</div></section>}<section><h3>{l.proposals}</h3><ResultList locale={locale} kind="improvement" items={improvements} empty={l.noResults ?? ""} l={l} /></section><section><h3>{l.issues}</h3><ResultList locale={locale} kind="issue" items={issues} empty={l.noResults ?? ""} l={l} /></section></> : <p className="hint result-empty">{l.noMatchingResults}</p>}</>;
}
