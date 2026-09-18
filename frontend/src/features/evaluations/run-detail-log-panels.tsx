import type { RunStepResult, RunTelemetry } from "../../domain/models";
import { intlLocales, type Locale } from "../../locales";
import { TelemetryTree } from "./run-detail-telemetry-tree";

const time = (locale: Locale, value?: string) => value ? new Intl.DateTimeFormat(intlLocales[locale], { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value)) : "—";
const stepLogLines = (step: RunStepResult) => step.log_lines?.length ? step.log_lines.map(({ timestamp, value }) => ({ value, timestamp })) : (step.output ?? step.error ?? "—").split("\n").map((value) => ({ value, timestamp: step.ended_at ?? step.started_at }));

function TimestampedLogOutput({ lines, locale }: { lines: { value: string; timestamp?: string }[]; locale: Locale }) {
  return <div className="timestamped-log-output">{lines.map((line, index) => <div key={index}><time>{time(locale, line.timestamp)}</time><code>{line.value || " "}</code></div>)}</div>;
}

export function CombinedLogPanel({ steps, locale, empty, orbitLogs, targetLogs, telemetry, openTelemetryTrace, loadingOpenTelemetryTrace, noOpenTelemetrySpans }: { steps: RunStepResult[]; locale: Locale; empty: string; orbitLogs: string; targetLogs: string; telemetry?: RunTelemetry; openTelemetryTrace?: string; loadingOpenTelemetryTrace?: string; noOpenTelemetrySpans?: string }) {
  const logSteps = steps.filter((step) => step.output || step.error);
  const targetLines = steps.flatMap((step) => step.target_logs ?? []).map((entry) => ({
    timestamp: entry.timestamp,
    value: `[${entry.level ?? "info"}]${entry.source ? ` ${entry.source}` : ""} ${entry.message}`,
  }));
  return <div className="console-output combined-log-output"><section><h3>{orbitLogs}</h3>{logSteps.length ? <TimestampedLogOutput lines={logSteps.flatMap(stepLogLines)} locale={locale} /> : <p className="hint">{empty}</p>}</section><section><h3>{targetLogs}</h3>{targetLines.length ? <TimestampedLogOutput lines={targetLines} locale={locale} /> : <p className="hint">{empty}</p>}</section><section><h3>{openTelemetryTrace}</h3><TelemetryTree telemetry={telemetry} loading={loadingOpenTelemetryTrace} empty={noOpenTelemetrySpans} /></section></div>;
}
