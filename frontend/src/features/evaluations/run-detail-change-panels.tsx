import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { CommitChange } from "../../domain/models";

type Messages = Record<string, string | undefined>;

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
  return <UnifiedDiff patch={patch} label={l.diffArtifact ?? "Diff"} />;
}
export function UnifiedDiff({ patch, label = "Diff" }: { patch: string; label?: string }) {
  return <div className="prompt-diff commit-diff" aria-label={label}>{unifiedDiffRows(patch).map((row, index) => row.kind === "meta" ? <div className="commit-diff__meta" key={index}><code>{row.line || " "}</code></div> : <div className={`prompt-diff__row prompt-diff__row--${row.kind}`} key={index}><span className="prompt-diff__line-number">{row.before ?? ""}</span><span className="prompt-diff__line-number">{row.after ?? ""}</span><span className="prompt-diff__marker">{row.kind === "added" ? "+" : row.kind === "removed" ? "−" : " "}</span><code>{row.line || " "}</code></div>)}</div>;
}
