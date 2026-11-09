import { useMemo, useState } from "react";
import type { RunStepResult } from "../../domain/models";
import { EvidenceViewer, visualEvidenceArtifacts } from "../../components/ui/evidence-viewer";
import { intlLocales, type Locale } from "../../locales";

type RecordItem = Record<string, unknown>;
type DialogueMessage = { role: "persona" | "assistant" | "tool"; content: string; recordedAt?: string };
type Session = { persona: string; personaName: string; dialogue: DialogueMessage[]; iteration: number; recordedAt?: string; artifacts: ReturnType<typeof visualEvidenceArtifacts> };
type Copy = Record<string, string>;

const record = (value: unknown): RecordItem | null => value && typeof value === "object" && !Array.isArray(value) ? value as RecordItem : null;

function dialogue(value: unknown): DialogueMessage[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((message) => {
    const item = record(message);
    const role = item?.role;
    const content = item?.content;
    const recordedAt = typeof item?.recorded_at === "string" ? item.recorded_at : undefined;
    return (role === "persona" || role === "assistant" || role === "tool") && typeof content === "string"
      ? [{ role, content, recordedAt }]
      : [];
  });
}

// Tool output is deliberately reduced to a small public summary. It never renders
// the raw browser payload, which can contain page text or implementation detail.
function publicToolSummary(content: string) {
  try {
    const payload = record(JSON.parse(content));
    if (!payload) return content;
    const actions = Array.isArray(payload.actions) ? payload.actions : [];
    const actionSummary = actions.flatMap((action) => {
      const item = record(action);
      const type = typeof item?.type === "string" ? item.type : undefined;
      const status = typeof item?.status === "string" ? item.status : undefined;
      return type ? [`${type}${status ? ` · ${status}` : ""}`] : [];
    });
    const page = record(payload.page);
    const pageSummary = typeof page?.title === "string" ? page.title : undefined;
    return [...actionSummary, ...(pageSummary ? [pageSummary] : [])].join("\n") || "No public browser result was returned.";
  } catch {
    return "No structured public tool result was returned.";
  }
}

function sessionsFrom(steps: RunStepResult[]): Session[] {
  const latestByPersona = new Map<string, Session>();
  for (const step of steps) {
    const simulator = record(step.result?.insighta_persona_simulator);
    const evidence = simulator?.persona_evidence;
    if (!Array.isArray(evidence)) continue;
    for (const [index, entry] of evidence.entries()) {
      const item = record(entry);
      const plan = record(item?.plan);
      const messages = dialogue(plan?.dialogue);
      if (!item || !messages.length) continue;
      const persona = typeof item.persona === "string" ? item.persona : `Persona ${index + 1}`;
      const personaName = typeof item.persona_name === "string" && item.persona_name ? item.persona_name : persona;
      // A runner emits the same evidence from both the source-backed session
      // and the retention step. Keep the later record for one Persona/iteration.
      latestByPersona.set(`${step.loop_index ?? 0}:${persona}`, {
        persona,
        personaName,
        dialogue: messages,
        iteration: step.loop_index ?? 0,
        recordedAt: step.ended_at ?? step.started_at,
        artifacts: visualEvidenceArtifacts(step.data_files ?? []),
      });
    }
  }
  return [...latestByPersona.values()];
}

export function RunDetailConversationPanel({ steps, runId, l, locale }: { steps: RunStepResult[]; runId: string; l: Copy; locale: Locale }) {
  const sessions = useMemo(() => sessionsFrom(steps), [steps]);
  const [selectedPersona, setSelectedPersona] = useState("");
  const session = sessions.find((item) => item.persona === selectedPersona) ?? sessions[0];
  if (!session) return <div className="conversation-empty"><strong>{l.noConversation}</strong><p>{l.noConversationHint}</p></div>;
  return <div className="conversation-panel">
    <div className="conversation-sessions" aria-label={l.session}>
      {sessions.map((item) => <button key={item.persona} type="button" className={item.persona === session.persona ? "selected" : ""} onClick={() => setSelectedPersona(item.persona)}>
        <strong>{item.personaName}</strong><small>#{item.iteration}</small>
      </button>)}
    </div>
    <ol className="conversation-transcript" aria-label={`${session.personaName} ${l.session}`}>
      {session.dialogue.map((message, index) => <li key={`${message.role}-${index}`} className={`conversation-message conversation-message--${message.role}`}>
        <header><small>{message.role === "persona" ? `${l.persona} (${session.personaName})` : message.role === "assistant" ? l.toolAi : l.toolResult}</small>{(message.recordedAt ?? session.recordedAt) && <time dateTime={message.recordedAt ?? session.recordedAt}>{new Intl.DateTimeFormat(intlLocales[locale], { dateStyle: "short", timeStyle: "medium" }).format(new Date(message.recordedAt ?? session.recordedAt!))}</time>}</header>
        {message.role === "tool" ? <details><summary>{l.showToolResult}</summary><pre>{publicToolSummary(message.content)}</pre></details> : <p>{message.content}</p>}
        {message.role === "tool" && <EvidenceViewer runId={runId} iteration={session.iteration} artifacts={session.artifacts} imageLabel={l.viewImageEvidence} htmlLabel={l.viewHtmlEvidence} imageTitle={l.imageEvidence} htmlTitle={l.htmlEvidence} />}
      </li>)}
    </ol>
  </div>;
}
