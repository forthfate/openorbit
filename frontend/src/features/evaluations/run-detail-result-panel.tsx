import { useEffect, useState, type ReactNode } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { html } from "@codemirror/lang-html";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { CodeXml, Image } from "lucide-react";
import type { RunStepResult } from "../../domain/models";
import { Modal } from "../../components/ui/modal";
import { intlLocales, type Locale } from "../../locales";

type Messages = Record<string, string | undefined>;
type RecordItem = Record<string, unknown>;
type BehaviorTrace = {
  iteration: number;
  recordedAt?: string;
  summary?: string;
  trace?: { persona_goal?: string; current_action?: string; decision?: string; next_action?: string; evidence?: string; expectation?: string; interpretation?: string; impact?: string; next_step?: string; purpose?: string; rationale?: string; observation?: string };
};
type EvidenceArtifact = { id?: string; name?: string; screenshot?: string; html?: string };
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

function visualDataFiles(step: RunStepResult): EvidenceArtifact[] {
  return (step.data_files ?? []).reduce<EvidenceArtifact[]>((artifacts, file, index) => {
    const path = file.relative_path ?? file.path;
    if (!path) return artifacts;
    const name = file.label || file.filename || `#${index + 1}`;
    if (file.content_type?.startsWith("image/")) artifacts.push({ id: path, name, screenshot: path });
    if (file.content_type === "text/html") artifacts.push({ id: path, name, html: path });
    return artifacts;
  }, []);
}

function artifactUrl(runId: string, iteration: number, path: string) {
  const normalized = path.replaceAll("\\", "/"), marker = `/loop-${iteration}/`;
  const relative = normalized.includes(marker) ? normalized.split(marker).at(-1)! : normalized;
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${iteration}/${relative.split("/").map(encodeURIComponent).join("/")}`;
}

function HtmlEvidenceViewer({ url }: { url: string }) {
  const [result, setResult] = useState<{ url: string; source?: string; error?: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((source) => setResult({ url, source }))
      .catch((reason: unknown) => {
        if ((reason as { name?: string }).name !== "AbortError") setResult({ url, error: String(reason) });
      });
    return () => controller.abort();
  }, [url]);
  if (!result || result.url !== url) return <p className="hint">Loading HTML…</p>;
  if (result.error) return <pre className="persona-evidence__error">{result.error}</pre>;
  return <CodeMirror aria-label="HTML evidence source" value={result.source ?? ""} editable={false} height="min(60vh, 640px)" theme={oneDark} extensions={[html(), EditorView.lineWrapping]} basicSetup={{ lineNumbers: true, highlightActiveLine: true, bracketMatching: true, foldGutter: true }} />;
}

function ResultList({ items, kind, locale, empty }: { items: RecordItem[]; kind: "improvement" | "issue"; locale: Locale; empty: string }) {
  return <div className="result-items result-items--scrollable">{items.length ? items.map((item, index) => {
    const status = String(item.status ?? "—"), severity = String(item.severity ?? "—"), reportedAt = typeof item.reported_at === "string" ? item.reported_at : undefined;
    return <article className="result-row" key={index}><time className="result-row__time">{time(locale, reportedAt)}</time><div className="result-row__body"><strong>{String(item.title ?? "—")}</strong><p>{String(kind === "improvement" ? (item.rationale ?? "—") : (item.evidence ?? "—"))}</p></div><div className="result-row__metrics"><span><small>Iteration</small><b>#{String(item.__iteration ?? "—")}</b></span>{kind === "improvement" ? <><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span><span><small>Score</small><b>{String(item.effect_score ?? item.score ?? "—")}</b></span><span><small>Attempted</small><b>{item.attempted === true || status === "adopted" ? "Yes" : "No"}</b></span></> : <><span><small>Severity</small><b className={`decision decision--${severity}`}>{severity}</b></span><span><small>Status</small><b className={`decision decision--${status}`}>{status}</b></span></>}</div></article>;
  }) : <p className="hint result-empty">{empty}</p>}</div>;
}

export function EvaluationResultPanel({ error, records, summaries, steps, runId, improvements, issues, l, locale }: { error?: ReactNode; records: unknown[]; summaries: BehaviorTrace[]; steps: RunStepResult[]; runId: string; improvements: RecordItem[]; issues: RecordItem[]; l: Messages; locale: Locale }) {
  const [evidenceModal, setEvidenceModal] = useState<{ kind: "image" | "html"; artifacts: EvidenceArtifact[]; iteration: number } | null>(null);
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
    .flatMap((step) => [...(browserJourney(step.result)?.results ?? []), ...visualDataFiles(step)]);
  const modalArtifacts = evidenceModal?.artifacts.filter((artifact) => evidenceModal.kind === "image" ? Boolean(artifact.screenshot) : Boolean(artifact.html)) ?? [];
  return <>{error}{records.length ? <>{summaries.length > 0 && <section className="result-behavior-summaries"><h3>{l.observedBehavior}</h3><div className="result-items result-items--scrollable">{summaries.map((item) => { const artifacts = artifactsFor(item.iteration), imageArtifacts = artifacts.filter((artifact) => artifact.screenshot), htmlArtifacts = artifacts.filter((artifact) => artifact.html); return <article className="result-row result-behavior-trace" key={item.iteration}><time className="result-row__time">{time(locale, item.recordedAt)}</time><div className="result-row__body">{traceFields(item).length ? <dl>{traceFields(item).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p>{item.summary}</p>}</div><div className="result-row__metrics"><span className="result-row__iteration"><small>Iteration</small><b>#{item.iteration}</b></span><span className="result-row__evidence">{imageArtifacts.length > 0 && <button className="ghost icon-button" type="button" aria-label={l.viewImageEvidence} title={l.viewImageEvidence} onClick={() => setEvidenceModal({ kind: "image", artifacts: imageArtifacts, iteration: item.iteration })}><Image size={16} /></button>}{htmlArtifacts.length > 0 && <button className="ghost icon-button" type="button" aria-label={l.viewHtmlEvidence} title={l.viewHtmlEvidence} onClick={() => setEvidenceModal({ kind: "html", artifacts: htmlArtifacts, iteration: item.iteration })}><CodeXml size={16} /></button>}</span></div></article>; })}</div></section>}<section><h3>{l.proposals}</h3><ResultList locale={locale} kind="improvement" items={improvements} empty={l.noResults ?? ""} /></section><section><h3>{l.issues}</h3><ResultList locale={locale} kind="issue" items={issues} empty={l.noResults ?? ""} /></section></> : <p className="hint result-empty">{l.noMatchingResults}</p>}<Modal open={Boolean(evidenceModal)} title={evidenceModal?.kind === "image" ? l.imageEvidence ?? "" : l.htmlEvidence ?? ""} onClose={() => setEvidenceModal(null)} className="modal--evidence">{modalArtifacts.map((artifact, index) => <figure className="persona-evidence" key={`${artifact.id ?? index}-${evidenceModal?.kind}`}><figcaption>{artifact.name ?? artifact.id ?? `#${index + 1}`}</figcaption>{evidenceModal?.kind === "image" ? <img src={artifactUrl(runId, evidenceModal.iteration, artifact.screenshot!)} alt={artifact.name ?? artifact.id ?? ""} /> : <HtmlEvidenceViewer url={artifactUrl(runId, evidenceModal!.iteration, artifact.html!)} />}</figure>)}</Modal></>;
}
