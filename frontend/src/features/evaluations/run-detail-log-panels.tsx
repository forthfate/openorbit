import type { RunStepResult } from "../../domain/models";
import { intlLocales, type Locale } from "../../locales";

const time = (locale: Locale, value?: string) => value ? new Intl.DateTimeFormat(intlLocales[locale], { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value)) : "—";
const stepLogLines = (step: RunStepResult) => step.log_lines?.length ? step.log_lines.map(({ timestamp, value }) => ({ value, timestamp })) : (step.output ?? step.error ?? "—").split("\n").map((value) => ({ value, timestamp: step.ended_at ?? step.started_at }));

function BrowserEvidence({ result }: { result: Record<string, unknown> }) {
  const journey = result.browser_journey as { base_url?: string; results?: { id?: string; name?: string; passed?: boolean; url?: string; expected_text?: string; screenshot?: string; error?: string }[] } | undefined;
  if (!journey) return null;
  return <div className="browser-evidence"><strong>Playwright browser journey</strong><small>{journey.base_url}</small>{journey.results?.map((item) => <div key={item.id}><b className={item.passed ? "browser-evidence__pass" : "browser-evidence__fail"}>{item.passed ? "Passed" : "Failed"}</b><span>{item.name ?? item.id} · {item.url}</span>{item.expected_text && <small>Expected: {item.expected_text}</small>}{item.screenshot && <small>Screenshot: {item.screenshot}</small>}{item.error && <pre>{item.error}</pre>}</div>)}</div>;
}
function TimestampedLogOutput({ lines, locale }: { lines: { value: string; timestamp?: string }[]; locale: Locale }) {
  return <div className="timestamped-log-output">{lines.map((line, index) => <div key={index}><time>{time(locale, line.timestamp)}</time><code>{line.value || " "}</code></div>)}</div>;
}

export function WorkflowLogPanel({ steps, locale, empty }: { steps: RunStepResult[]; locale: Locale; empty: string }) {
  const visibleSteps = steps.filter((step) => Boolean(step.result) || Boolean(step.log_lines?.length) || Boolean(step.output) || Boolean(step.error));
  return <div className="console-output workflow-log-output">{visibleSteps.length ? visibleSteps.map((step, index) => <section key={`${step.step_id}-${index}`}>{step.result && <BrowserEvidence result={step.result} />}{(step.log_lines?.length || step.output || step.error) && <TimestampedLogOutput locale={locale} lines={stepLogLines(step)} />}</section>) : <p className="hint">{empty}</p>}</div>;
}

export function CombinedLogPanel({ steps, locale, empty, orbitLogs, targetLogs }: { steps: RunStepResult[]; locale: Locale; empty: string; orbitLogs: string; targetLogs: string }) {
  const logSteps = steps.filter((step) => step.output || step.error);
  const targetLines = steps.flatMap((step) => step.target_logs ?? []).map((entry) => ({
    timestamp: entry.timestamp,
    value: `[${entry.level ?? "info"}]${entry.source ? ` ${entry.source}` : ""} ${entry.message}`,
  }));
  return <div className="console-output"><section><h3>{orbitLogs}</h3>{logSteps.length ? <TimestampedLogOutput lines={logSteps.flatMap(stepLogLines)} locale={locale} /> : <p className="hint">{empty}</p>}</section><section><h3>{targetLogs}</h3>{targetLines.length ? <TimestampedLogOutput lines={targetLines} locale={locale} /> : <p className="hint">{empty}</p>}</section></div>;
}
