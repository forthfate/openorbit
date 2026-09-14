import { useMemo, useState, type ReactNode } from "react";
import type { RunTelemetry, SupervisorRecord, TelemetrySpan } from "../../domain/models";
import { StatusBadge } from "../../components/ui/status-badge";

type Messages = Record<string, string | undefined>;

function telemetryValue(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function duration(span: TelemetrySpan) {
  if (!span.startTime || !span.endTime || span.endTime < span.startTime) return undefined;
  return `${((span.endTime - span.startTime) / 1_000_000).toFixed(1)} ms`;
}

function TelemetryTree({ telemetry, l }: { telemetry?: RunTelemetry; l: Messages }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const tree = useMemo(() => {
    const spans = telemetry?.spans ?? [], children = new Map<string, TelemetrySpan[]>(), known = new Set(spans.map((span) => span.spanId));
    for (const span of spans) if (span.parentSpanId && known.has(span.parentSpanId)) children.set(span.parentSpanId, [...(children.get(span.parentSpanId) ?? []), span]);
    return { roots: spans.filter((span) => !span.parentSpanId || !known.has(span.parentSpanId)), children };
  }, [telemetry]);
  if (!telemetry) return <p className="hint">{l.loadingOpenTelemetryTrace}</p>;
  if (!tree.roots.length) return <p className="hint">{l.noOpenTelemetrySpans}</p>;
  const render = (span: TelemetrySpan): ReactNode => {
    const children = tree.children.get(span.spanId) ?? [], expandable = children.length > 0, isCollapsed = collapsed.has(span.spanId), attributes = Object.entries(span.attributes ?? {}), events = span.events ?? [];
    const summary = [span.status || "UNSET", duration(span), ...events.map((event) => event.name)].filter(Boolean).join(" · ");
    return <li key={span.spanId}><button type="button" className="trace-node" disabled={!expandable} onClick={() => { if (!expandable) return; setCollapsed((current) => { const next = new Set(current); if (isCollapsed) next.delete(span.spanId); else next.add(span.spanId); return next; }); }}><span className={`trace-status trace-status--${span.status === "ERROR" ? "error" : "ok"}`} /><div><strong>{expandable ? `${isCollapsed ? "▸" : "▾"} ${span.name}` : span.name}</strong><small>{summary}</small></div></button>{!isCollapsed && (attributes.length > 0 || events.some((event) => Object.keys(event.attributes ?? {}).length > 0)) && <dl className="trace-details">{attributes.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{telemetryValue(value)}</dd></div>)}{events.flatMap((event) => Object.entries(event.attributes ?? {}).map(([key, value]) => <div key={`${event.name}.${key}`}><dt>{event.name} · {key}</dt><dd>{telemetryValue(value)}</dd></div>))}</dl>}{expandable && !isCollapsed && <ul>{children.map(render)}</ul>}</li>;
  };
  return <ul className="telemetry-tree">{tree.roots.map(render)}</ul>;
}

export function SupervisorPanel({ record, l, telemetry, renderLineOutput }: { record?: SupervisorRecord; l: Messages; telemetry?: RunTelemetry; renderLineOutput: (value: string) => ReactNode }) {
  const response = record?.response;
  return <div className="supervisor-output"><section><div className="supervisor-output__head"><strong>{l.supervisorPrompt}</strong><StatusBadge value={record?.status ?? "pending"} label={record?.status ?? "pending"} /></div>{renderLineOutput(record?.prompt || l.noSupervisorPrompt || "")}</section><section><strong>{l.supervisorResponse}</strong>{response ? renderLineOutput(JSON.stringify(response, null, 2)) : <p>{record?.error || l.supervisorWaiting}</p>}</section><section><strong>{l.openTelemetryTrace}</strong><TelemetryTree telemetry={telemetry} l={l} /></section></div>;
}
