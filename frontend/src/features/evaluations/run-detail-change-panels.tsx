import { useEffect, useMemo, useState } from "react";
import type { IssueManagementItem } from "../../domain/models";
import { api } from "../../services/api";

export function WorktreePanel({ items, empty, branch, path, diffLabel }: { items: IssueManagementItem[]; empty: string; branch: string; path: string; diffLabel: string }) {
  const worktrees = useMemo(() => items.filter((item) => {
    const change = item.proposal.agent_change as Record<string, unknown> | undefined;
    return typeof change?.worktree_path === "string" && Boolean(change.worktree_path);
  }), [items]);
  const [selectedId, setSelectedId] = useState<string | null>(null), [diff, setDiff] = useState("");
  const activeId = worktrees.some((item) => item.proposal_id === selectedId) ? selectedId : worktrees[0]?.proposal_id;
  useEffect(() => { if (!activeId) return; api<{ diff: string }>(`/api/v1/issue-management/${encodeURIComponent(activeId)}/diff`).then((result) => setDiff(result.diff)).catch(() => setDiff("")); }, [activeId]);
  if (!worktrees.length) return <p className="hint">{empty}</p>;
  const selected = worktrees.find((item) => item.proposal_id === activeId);
  const change = selected?.proposal.agent_change as Record<string, unknown> | undefined;
  return <div className="worktree-panel"><div className="worktree-panel__list" role="list">{worktrees.map((item) => { const proposal = item.proposal.agent_change as Record<string, unknown>; return <button type="button" role="listitem" className={item.proposal_id === activeId ? "selected" : ""} onClick={() => setSelectedId(item.proposal_id)} key={item.proposal_id}><strong>{item.title}</strong><small>{String(proposal.branch || "—")}</small></button>; })}</div>{selected && <section><p><small>{branch}</small> {String(change?.branch || "—")}</p><p><small>{path}</small> {String(change?.worktree_path || "—")}</p>{diff ? <UnifiedDiff patch={diff} label={diffLabel} /> : <p className="hint">{empty}</p>}</section>}</div>;
}

type UnifiedDiffRow = { kind: "added" | "removed" | "unchanged"; before?: number; after?: number; line: string } | { kind: "meta"; line: string };
function unifiedDiffRows(value: string): UnifiedDiffRow[] {
  let before: number | undefined, after: number | undefined;
  return value.split("\n").map((line) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (hunk) { before = Number(hunk[1]); after = Number(hunk[2]); return { kind: "meta", line }; }
    if (line.startsWith("+") && !line.startsWith("+++")) { const row = { kind: "added" as const, after, line }; after = (after ?? 0) + 1; return row; }
    if (line.startsWith("-") && !line.startsWith("---")) { const row = { kind: "removed" as const, before, line }; before = (before ?? 0) + 1; return row; }
    if (line.startsWith(" ")) { const row = { kind: "unchanged" as const, before, after, line }; before = (before ?? 0) + 1; after = (after ?? 0) + 1; return row; }
    return { kind: "meta", line };
  });
}
export function UnifiedDiff({ patch, label = "Diff" }: { patch: string; label?: string }) {
  return <div className="prompt-diff commit-diff" aria-label={label}>{unifiedDiffRows(patch).map((row, index) => row.kind === "meta" ? <div className="commit-diff__meta" key={index}><code>{row.line || " "}</code></div> : <div className={`prompt-diff__row prompt-diff__row--${row.kind}`} key={index}><span className="prompt-diff__line-number">{row.before ?? ""}</span><span className="prompt-diff__line-number">{row.after ?? ""}</span><span className="prompt-diff__marker">{row.kind === "added" ? "+" : row.kind === "removed" ? "−" : " "}</span><code>{row.line || " "}</code></div>)}</div>;
}
