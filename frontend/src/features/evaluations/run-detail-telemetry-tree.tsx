import { useMemo, useState, type ReactNode } from "react";
import type { RunTelemetry, TelemetrySpan } from "../../domain/models";

function telemetryValue(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function duration(span: TelemetrySpan) {
  if (!span.startTime || !span.endTime || span.endTime < span.startTime) return undefined;
  return `${((span.endTime - span.startTime) / 1_000_000).toFixed(1)} ms`;
}

export function TelemetryTree({ telemetry, loading, empty }: { telemetry?: RunTelemetry; loading?: string; empty?: string }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const tree = useMemo(() => {
    const spans = telemetry?.spans ?? [], children = new Map<string, TelemetrySpan[]>(), known = new Set(spans.map((span) => span.spanId));
    for (const span of spans) if (span.parentSpanId && known.has(span.parentSpanId)) children.set(span.parentSpanId, [...(children.get(span.parentSpanId) ?? []), span]);
    return { roots: spans.filter((span) => !span.parentSpanId || !known.has(span.parentSpanId)), children };
  }, [telemetry]);
  if (!telemetry) return <p className="hint">{loading}</p>;
  if (!tree.roots.length) return <p className="hint">{empty}</p>;
  const render = (span: TelemetrySpan): ReactNode => {
    const children = tree.children.get(span.spanId) ?? [], expandable = children.length > 0, isCollapsed = collapsed.has(span.spanId), attributes = Object.entries(span.attributes ?? {}), events = span.events ?? [];
    const summary = [span.status || "UNSET", duration(span), ...events.map((event) => event.name)].filter(Boolean).join(" · ");
    return <li key={span.spanId}><button type="button" className="trace-node" disabled={!expandable} onClick={() => { if (!expandable) return; setCollapsed((current) => { const next = new Set(current); if (isCollapsed) next.delete(span.spanId); else next.add(span.spanId); return next; }); }}><span className={`trace-status trace-status--${span.status === "ERROR" ? "error" : "ok"}`} /><div><strong>{expandable ? `${isCollapsed ? "▸" : "▾"} ${span.name}` : span.name}</strong><small>{summary}</small></div></button>{!isCollapsed && (attributes.length > 0 || events.some((event) => Object.keys(event.attributes ?? {}).length > 0)) && <dl className="trace-details">{attributes.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{telemetryValue(value)}</dd></div>)}{events.flatMap((event) => Object.entries(event.attributes ?? {}).map(([key, value]) => <div key={`${event.name}.${key}`}><dt>{event.name} · {key}</dt><dd>{telemetryValue(value)}</dd></div>))}</dl>}{expandable && !isCollapsed && <ul>{children.map(render)}</ul>}</li>;
  };
  return <ul className="telemetry-tree">{tree.roots.map(render)}</ul>;
}
