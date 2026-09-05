"""OpenTelemetry setup for every workflow action and process lifecycle event."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult


class JsonlSpanExporter(SpanExporter):
    """Local OTEL exporter; each record is an exported span, never an ad-hoc log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans) -> SpanExportResult:  # type: ignore[no-untyped-def]
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            for span in spans:
                record = {
                    "resourceSpans": [
                        {
                            "resource": {key: str(value) for key, value in span.resource.attributes.items()},
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": span.name,
                                            "traceId": f"{span.context.trace_id:032x}",
                                            "spanId": f"{span.context.span_id:016x}",
                                            "parentSpanId": f"{span.parent.span_id:016x}"
                                            if span.parent
                                            else None,
                                            "startTime": span.start_time,
                                            "endTime": span.end_time,
                                            "attributes": dict(span.attributes),
                                            "status": span.status.status_code.name,
                                            "events": [
                                                {"name": event.name, "attributes": dict(event.attributes)}
                                                for event in span.events
                                            ],
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                    "exportedAt": datetime.now(UTC).isoformat(),
                }
                stream.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def configure_telemetry(path: Path):  # type: ignore[no-untyped-def]
    provider = TracerProvider(resource=Resource.create({"service.name": "orbit-agent-console"}))
    provider.add_span_processor(BatchSpanProcessor(JsonlSpanExporter(path), schedule_delay_millis=200))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("orbit.console")
