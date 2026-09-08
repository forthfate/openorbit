import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { CommitChange, PromptRevision } from "../../domain/models";
import { StatusBadge } from "../../components/ui/status-badge";

type Messages = Record<string, string | undefined>;
type LineOutput = (value: string) => ReactNode;

export function PromptChangesPanel({
  revisions,
  l,
  renderLineOutput,
}: {
  revisions: PromptRevision[];
  l: Messages;
  renderLineOutput: LineOutput;
}) {
  const items = [...revisions].reverse();
  const [revisionIndex, setRevisionIndex] = useState(0);
  if (!items.length) return <p className="hint">{l.noPromptChanges}</p>;
  const index = Math.min(revisionIndex, items.length - 1), item = items[index];
  return (
    <div className="prompt-changes">
      <div className="prompt-version-navigator">
        <button className="ghost icon-button" type="button" disabled={index >= items.length - 1} onClick={() => setRevisionIndex(index + 1)} aria-label={l.previousPromptChange} title={l.previousPromptChange}><ChevronLeft size={16} /></button>
        <span>{l.promptVersion?.replace("{0}", String(items.length - index)).replace("{1}", String(items.length))}</span>
        <button className="ghost icon-button" type="button" disabled={index === 0} onClick={() => setRevisionIndex(index - 1)} aria-label={l.nextPromptChange} title={l.nextPromptChange}><ChevronRight size={16} /></button>
      </div>
      <section>
        <div className="prompt-changes__head">
          <div>
            <strong>{item.path}</strong>
            <small>{item.status === "initial" ? l.initialPromptState : item.version_id ?? item.reason ?? l.noPromptSnapshot}</small>
          </div>
          <StatusBadge value={item.status} label={l[`prompt${item.status}`] ?? item.status} />
        </div>
        {item.status === "initial" ? (
          <p className="prompt-change-meta">{l.initialPromptHint}</p>
        ) : (
          <p className="prompt-change-meta">{l.iteration} #{item.iteration ?? "—"} · {item.phase ?? "—"}{item.run_id ? ` · ${item.run_id}` : ""}</p>
        )}
        {item.status === "blocked" && <p className="hint">{l.promptBlockedHint}</p>}
        {(item.status === "initial" || item.status === "blocked" || item.status === "unchanged") && typeof item.after === "string" ? (
          renderLineOutput(item.after)
        ) : typeof item.before === "string" && typeof item.after === "string" ? (
          <PromptDiff before={item.before} after={item.after} />
        ) : (
          <p className="hint">{l.noPromptSnapshot}</p>
        )}
      </section>
    </div>
  );
}

export function CommitChangesPanel({ changes, l }: { changes: CommitChange[]; l: Messages }) {
  const items = [...changes].reverse();
  const [changeIndex, setChangeIndex] = useState(0);
  if (!changes.length) return <p className="hint">{l.noCommitChanges}</p>;
  const index = Math.min(changeIndex, items.length - 1), change = items[index];
  return (
    <div className="commit-changes">
      <div className="prompt-version-navigator">
        <button className="ghost icon-button" type="button" disabled={index >= items.length - 1} onClick={() => setChangeIndex(index + 1)} aria-label={l.previousCommitChange} title={l.previousCommitChange}><ChevronLeft size={16} /></button>
        <span>{l.commitVersion?.replace("{0}", String(items.length - index)).replace("{1}", String(items.length))}</span>
        <button className="ghost icon-button" type="button" disabled={index === 0} onClick={() => setChangeIndex(index - 1)} aria-label={l.nextCommitChange} title={l.nextCommitChange}><ChevronRight size={16} /></button>
      </div>
      <section>
        <div className="commit-changes__head"><strong>{change.before.slice(0, 12)} → {change.after.slice(0, 12)}</strong><small>{l.iteration} #{change.iteration ?? "—"} · {change.phase ?? "—"}</small></div>
        {change.commits.length > 0 && <div className="commit-changes__group"><small>{l.commits}</small><ul>{change.commits.map((commit) => <li key={commit.sha}><code>{commit.sha.slice(0, 12)}</code><span>{commit.subject}</span></li>)}</ul></div>}
        <div className="commit-changes__group"><small>{l.changedFiles}</small>{change.changed_paths.length > 0 ? <ul>{change.changed_paths.map((path) => <li key={path}><code>{path}</code></li>)}</ul> : <p className="hint">{l.noChangedFiles}</p>}</div>
        {change.diff_artifact?.relative_path && <CommitPatch patch={change.diff} relativePath={change.diff_artifact.relative_path} l={l} />}
      </section>
    </div>
  );
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
function CommitPatch({ patch, relativePath, l }: { patch?: string | null; relativePath: string; l: Messages }) {
  if (patch == null) return <p className="commit-changes__artifact">{l.diffArtifact}: <code>{relativePath}</code></p>;
  return <div className="prompt-diff commit-diff" aria-label={l.diffArtifact}>{unifiedDiffRows(patch).map((row, index) => row.kind === "meta" ? <div className="commit-diff__meta" key={index}><code>{row.line || " "}</code></div> : <div className={`prompt-diff__row prompt-diff__row--${row.kind}`} key={index}><span className="prompt-diff__line-number">{row.before ?? ""}</span><span className="prompt-diff__line-number">{row.after ?? ""}</span><span className="prompt-diff__marker">{row.kind === "added" ? "+" : row.kind === "removed" ? "−" : " "}</span><code>{row.line || " "}</code></div>)}</div>;
}
function PromptDiff({ before, after }: { before: string; after: string }) {
  const beforeLines = before.split("\n"), afterLines = after.split("\n");
  let prefix = 0;
  while (prefix < beforeLines.length && prefix < afterLines.length && beforeLines[prefix] === afterLines[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < beforeLines.length - prefix && suffix < afterLines.length - prefix && beforeLines[beforeLines.length - 1 - suffix] === afterLines[afterLines.length - 1 - suffix]) suffix += 1;
  const rows: Array<{ kind: "unchanged" | "removed" | "added"; before?: number; after?: number; line: string }> = [
    ...beforeLines.slice(0, prefix).map((line, index) => ({ kind: "unchanged" as const, before: index + 1, after: index + 1, line })),
    ...beforeLines.slice(prefix, beforeLines.length - suffix).map((line, index) => ({ kind: "removed" as const, before: prefix + index + 1, line })),
    ...afterLines.slice(prefix, afterLines.length - suffix).map((line, index) => ({ kind: "added" as const, after: prefix + index + 1, line })),
    ...beforeLines.slice(beforeLines.length - suffix).map((line, index) => ({ kind: "unchanged" as const, before: beforeLines.length - suffix + index + 1, after: afterLines.length - suffix + index + 1, line })),
  ];
  return <div className="prompt-diff" aria-label="Prompt diff">{rows.map((row, index) => <div className={`prompt-diff__row prompt-diff__row--${row.kind}`} key={`${row.kind}-${index}`}><span className="prompt-diff__line-number" aria-label={row.before ? `Previous line ${row.before}` : "No previous line"}>{row.before ?? ""}</span><span className="prompt-diff__line-number" aria-label={row.after ? `New line ${row.after}` : "No new line"}>{row.after ?? ""}</span><span className="prompt-diff__marker" aria-hidden="true">{row.kind === "added" ? "+" : row.kind === "removed" ? "−" : " "}</span><code>{row.line || " "}</code></div>)}</div>;
}
