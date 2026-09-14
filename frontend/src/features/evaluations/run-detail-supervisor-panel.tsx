import type { ReactNode } from "react";
import type { SupervisorRecord } from "../../domain/models";
import { StatusBadge } from "../../components/ui/status-badge";

type Messages = Record<string, string | undefined>;

export function SupervisorPanel({ record, l, renderLineOutput }: { record?: SupervisorRecord; l: Messages; renderLineOutput: (value: string) => ReactNode }) {
  const response = record?.response;
  return <div className="supervisor-output"><section><div className="supervisor-output__head"><strong>{l.supervisorPrompt}</strong><StatusBadge value={record?.status ?? "pending"} label={record?.status ?? "pending"} /></div>{renderLineOutput(record?.prompt || l.noSupervisorPrompt || "")}</section><section><strong>{l.supervisorResponse}</strong>{response ? renderLineOutput(JSON.stringify(response, null, 2)) : <p>{record?.error || l.supervisorWaiting}</p>}</section></div>;
}
