import { useEffect, useMemo, useRef, useState } from "react";
import "./discussion.css";
import type { IssueManagementItem, Run } from "../../domain/models";
import { api } from "../../services/api";
import { StatusBadge } from "../../components/ui/status-badge";
import { Modal } from "../../components/ui/modal";
import { DataTable, type Column } from "../../components/ui/data-table";
import { SectionInfo } from "../../components/ui/section-info";
import { EvidenceViewer, visualEvidenceArtifacts } from "../../components/ui/evidence-viewer";
import { PanelHeader } from "../../components/ui/page-header";
import { intlLocales, localeMessages, locales, type Locale } from "../../locales";
import { ListFilter, Trash2 } from "lucide-react";
import { RunDetailTabs } from "../evaluations/run-detail-tabs";
import { UnifiedDiff } from "../evaluations/run-detail-change-panels";
import { ConfirmDialog } from "../../components/ui/confirm-dialog";
import { PageSizeSelect } from "../../components/ui/page-size-select";
import { Pagination } from "../../components/ui/pagination";

type Copy = {
  title: string;
  description: string;
  allBuilds: string;
  allStatuses: string;
  allDecisions: string;
  empty: string;
  unreviewed: string;
  reviewing: string;
  inProgress: string;
  resolved: string;
  deferred: string;
  comment: string;
  commentAuthor: string;
  assignerPlaceholder: string;
  commentPlaceholder: string;
  verificationRun: string;
  selectVerificationRun: string;
  save: string;
  managementStatus: string;
  proposalStatus: string;
  aiDecision: string;
  decisionRationale: string;
  persona: string;
  taskId: string;
  iteration: string;
  run: string;
  updated: string;
  saved: string;
  build: string;
  proposal: string;
  accuracyGrounding: string;
  safetyPrivacy: string;
  taskCompletion: string;
  userExperience: string;
  other: string;
  details: string;
  statusHint: string;
  managementStatusHint: string;
  commentHint: string;
  discussion: string;
  noComments: string;
  sendComment: string;
  assignerHint: string;
  verificationHint: string;
  historyHint: string;
  selected: string;
  deleteSelected: string;
  deleteSelectedTitle: string;
  deleteSelectedDescription: string;
  delete: string;
  proposed: string;
  acceptable: string;
  accepted: string;
  rejected: string;
  agentProposalDiff: string;
  noAgentProposalChanges: string;
  agentProposalBranch: string;
  committed: string;
  approveAndCommit: string;
  rejectAndRemove: string;
  agentProposalCommitted: string;
  agentProposalRemoved: string;
};
const statuses = [
  "unreviewed",
  "reviewing",
  "in_progress",
  "resolved",
  "deferred",
] as const;
type IssueRow = IssueManagementItem & { id: string; index: number };
const compactTimestamp = (locale: Locale, value?: string) =>
  value
    ? new Intl.DateTimeFormat(intlLocales[locale], {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "—";
export function IssueManagementSection({
  locale,
  onNotice,
  buildId,
}: {
  locale: Locale;
  onNotice: (message: string, tone?: "success" | "warning") => void;
  buildId: string;
}) {
  const t = localeMessages<Copy>(locale, "issueManagementPage"),
    evidenceCopy = localeMessages<Record<string, string>>(locale, "evaluations"),
    [items, setItems] = useState<IssueManagementItem[]>([]),
    [runs, setRuns] = useState<Run[]>([]),
    [managedStatuses, setManagedStatuses] = useState<Set<string>>(new Set()),
    [decisions, setDecisions] = useState<Set<string>>(new Set()),
    [filtersOpen, setFiltersOpen] = useState(false),
    [selected, setSelected] = useState<IssueManagementItem | null>(null),
    [agentDiff, setAgentDiff] = useState<{ proposalId: string; value: string } | null>(null),
    [modalTab, setModalTab] = useState<"details" | "history">("details"),
    [comment, setComment] = useState(""),
    [assigner, setAssigner] = useState(""),
    [managementStatus, setManagementStatus] = useState("unreviewed"),
    [run, setRun] = useState(""),
    [selectedIssueIds, setSelectedIssueIds] = useState<Set<string>>(new Set()),
    [deleteSelectionOpen, setDeleteSelectionOpen] = useState(false),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(15);
  const filterMenu = useRef<HTMLDivElement>(null);
  const load = () =>
    api<IssueManagementItem[]>("/api/v1/issue-management")
      .then(setItems)
      .catch(() => setItems([]));
  useEffect(() => {
    load();
    api<Run[]>("/api/runs").then(setRuns).catch(() => setRuns([]));
  }, [buildId]);
  useEffect(() => {
    if (!selected || !selected.proposal.agent_change) return;
    api<{ diff: string }>(`/api/v1/issue-management/${encodeURIComponent(selected.proposal_id)}/diff`)
      .then((result) => setAgentDiff({ proposalId: selected.proposal_id, value: result.diff }))
      .catch(() => setAgentDiff({ proposalId: selected.proposal_id, value: "" }));
  }, [selected]);
  useEffect(() => {
    if (!filtersOpen) return;
    const close = (event: PointerEvent) => {
      if (
        filterMenu.current &&
        !filterMenu.current.contains(event.target as Node)
      )
        setFiltersOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [filtersOpen]);
  const label = (v: string) =>
      ({
        unreviewed: t.unreviewed,
        reviewing: t.reviewing,
        in_progress: t.inProgress,
        resolved: t.resolved,
        deferred: t.deferred,
      })[v] ?? v,
    decisionLabel = (v: string) =>
      ({
        proposed: t.proposed,
        acceptable: t.acceptable,
        accepted: t.accepted,
        rejected: t.rejected,
      })[v] ?? v,
    categoryLabel = (v: string) =>
      ({
        accuracy_grounding: t.accuracyGrounding,
        safety_privacy: t.safetyPrivacy,
        task_completion: t.taskCompletion,
        user_experience: t.userExperience,
        other: t.other,
      })[v] ?? t.other,
    verificationRuns = useMemo(
      () =>
        runs
          .filter((item) => item.build_id === selected?.build_id)
          .sort(
            (left, right) =>
              Date.parse(right.finished_at ?? right.created_at ?? "") -
              Date.parse(left.finished_at ?? left.created_at ?? ""),
          ),
      [runs, selected?.build_id],
    ),
    knownAssignees = useMemo(
      () => [...new Set(items.flatMap((item) => [item.assigner, ...item.comments.map((comment) => comment.assigner)]).filter((value): value is string => Boolean(value?.trim())))].sort((left, right) => left.localeCompare(right)),
      [items],
    ),
    rows: IssueRow[] = items
      .filter(
        (x) =>
          x.build_id === buildId &&
          (!managedStatuses.size || managedStatuses.has(x.management_status)) &&
          (!decisions.size || decisions.has(x.status)),
      )
      .map((x, index) => ({ ...x, id: x.proposal_id, index: index + 1 }));
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pagedRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const save = () =>
    selected &&
    api<IssueManagementItem>(
      `/api/v1/issue-management/${encodeURIComponent(selected.proposal_id)}`,
      "PATCH",
      { status: managementStatus, comment, assigner, verification_run_id: run },
    )
      .then((x) => {
        setSelected(x);
        setComment("");
        setAssigner("");
        setManagementStatus(x.management_status);
        setRun("");
        load();
        onNotice(t.saved, "success");
      })
      .catch((e) => onNotice(e.message, "warning"));
  const decideAgentProposal = (decision: "approve" | "reject") =>
    selected &&
    api<IssueManagementItem>(
      `/api/v1/issue-management/${encodeURIComponent(selected.proposal_id)}/decision`,
      "POST",
      { decision },
    )
      .then((item) => {
        setSelected(item);
        setManagementStatus(item.management_status);
        load();
        onNotice(decision === "approve" ? t.agentProposalCommitted : t.agentProposalRemoved, "success");
      })
      .catch((error) => onNotice(error.message, "warning"));
  const allSelected = pagedRows.length > 0 && pagedRows.every((item) => selectedIssueIds.has(item.proposal_id));
  const toggleIssue = (proposalId: string) =>
    setSelectedIssueIds((current) => {
      const next = new Set(current);
      if (next.has(proposalId)) next.delete(proposalId);
      else next.add(proposalId);
      return next;
    });
  const toggleAll = () =>
    setSelectedIssueIds((current) => {
      const next = new Set(current);
      if (allSelected) pagedRows.forEach((item) => next.delete(item.proposal_id));
      else pagedRows.forEach((item) => next.add(item.proposal_id));
      return next;
    });
  const confirmDeleteSelected = () => {
    const proposalIds = [...selectedIssueIds];
    setDeleteSelectionOpen(false);
    api<{ deleted: number }>("/api/v1/issue-management", "DELETE", { proposal_ids: proposalIds })
      .then(({ deleted }) => {
        setSelectedIssueIds(new Set());
        load();
        onNotice(t.selected.replace("{count}", String(deleted)), "success");
      })
      .catch((error) => onNotice(error.message, "warning"));
  };
  const toggleManagedStatus = (status: string) =>
    {
      setPage(1);
      setManagedStatuses((current) => {
      const next = new Set(current);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
      });
    };
  const toggleDecision = (status: string) =>
    {
      setPage(1);
      setDecisions((current) => {
      const next = new Set(current);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
      });
    };
  const columns: Column<IssueRow>[] = [
    {
      id: "select",
      header: (
        <input
          aria-label="Select all issues"
          type="checkbox"
          checked={allSelected}
          disabled={!pagedRows.length}
          onChange={toggleAll}
        />
      ),
      render: (item) => (
        <input
          aria-label={`Select issue ${item.title}`}
          type="checkbox"
          checked={selectedIssueIds.has(item.proposal_id)}
          onChange={() => toggleIssue(item.proposal_id)}
        />
      ),
    },
    {
      id: "index",
      header: "#",
      render: (x) => x.index,
    },
    {
      id: "proposal",
      header: t.proposal,
      render: (x) => (
        <span className="issue-proposal">
          <em className={`issue-category issue-category--${x.category}`}>
            {categoryLabel(x.category)}
          </em>
          <strong>{x.title}</strong>
        </span>
      ),
      sortValue: (x) => x.title,
    },
    {
      id: "task-id",
      header: t.taskId,
      render: (x) => <span>{x.run_id ?? "—"}</span>,
      sortValue: (x) => x.run_id,
    },
    {
      id: "iteration",
      header: t.iteration,
      render: (x) => <span>#{x.iteration ?? "—"}</span>,
      sortValue: (x) => x.iteration,
    },
    {
      id: "persona",
      header: t.persona,
      render: (x) => (x.personas ?? []).join(", ") || "—",
      sortValue: (x) => (x.personas ?? []).join(", "),
    },
    {
      id: "decision",
      header: t.aiDecision,
      render: (x) => (
        <StatusBadge value={x.status} label={decisionLabel(x.status)} />
      ),
      sortValue: (x) => x.status,
    },
    {
      id: "managed",
      header: t.managementStatus,
      render: (x) => (
        <StatusBadge
          value={x.management_status}
          label={label(x.management_status)}
        />
      ),
      sortValue: (x) => x.management_status,
    },
  ];
  const filterCount = managedStatuses.size + decisions.size;
  return (
    <>
      <section className="panel active-evaluation-panel issue-management">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader
              title={
                <SectionInfo title={t.title} description={t.description} />
              }
            />
            <p className="hint section-description">{t.description}</p>
          </div>
        </div>
        <div className="run-filter-trigger" ref={filterMenu}>
          <button
            className="ghost run-filter-button"
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((open) => !open)}
          >
            <ListFilter size={15} />
            {locales[locale].runUi.filter}
            {filterCount > 0 && (
              <span className="nav-run-count">{filterCount}</span>
            )}
          </button>
          <PageSizeSelect
            locale={locale}
            value={pageSize}
            onChange={(value) => {
              setPageSize(value);
              setPage(1);
            }}
          />
          {filtersOpen && (
            <div className="run-filters run-filter-popover">
              <div className="run-filter-popover__header">
                <strong>{locales[locale].runUi.filter}</strong>
                <button
                  className="ghost"
                  onClick={() => {
                    setManagedStatuses(new Set());
                    setDecisions(new Set());
                    setPage(1);
                  }}
                >
                  {locales[locale].runUi.reset}
                </button>
              </div>
              <fieldset>
                <legend>{t.managementStatus}</legend>
                <div className="run-filters__statuses">
                  {statuses.map((value) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        checked={managedStatuses.has(value)}
                        onChange={() => toggleManagedStatus(value)}
                      />
                      {label(value)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend>{t.aiDecision}</legend>
                <div className="run-filters__statuses">
                  {["proposed", "acceptable", "accepted", "rejected"].map(
                    (value) => (
                      <label key={value}>
                        <input
                          type="checkbox"
                          checked={decisions.has(value)}
                          onChange={() => toggleDecision(value)}
                        />
                        {decisionLabel(value)}
                      </label>
                    ),
                  )}
                </div>
              </fieldset>
            </div>
          )}
        </div>
        <div className="run-history-actions">
          <span>{t.selected.replace("{count}", String(selectedIssueIds.size))}</span>
          <button
            className="icon-button danger"
            aria-label={t.deleteSelected}
            title={t.deleteSelected}
            onClick={() => setDeleteSelectionOpen(true)}
            disabled={!selectedIssueIds.size}
          >
            <Trash2 size={15} />
          </button>
        </div>
        <div className="issue-management-table-scroll">
          <DataTable
            columns={columns}
            rows={pagedRows}
            empty={t.empty}
            onRowClick={(item) => {
              setSelected(item);
              setModalTab("details");
              setComment("");
              setAssigner("");
              setManagementStatus(item.management_status);
              setRun("");
            }}
            className="issue-management-table"
            gridTemplateColumns="36px 42px minmax(410px,1fr) 112px 76px 96px 110px 110px"
          />
        </div>
        <Pagination
          locale={locale}
          page={currentPage}
          totalPages={totalPages}
          totalItems={rows.length}
          pageSize={pageSize}
          onPageChange={setPage}
        />
      </section>
      <ConfirmDialog
        open={deleteSelectionOpen}
        title={t.deleteSelectedTitle}
        description={t.deleteSelectedDescription.replace("{count}", String(selectedIssueIds.size))}
        cancelLabel={locales[locale].common.cancel}
        confirmLabel={t.delete}
        onCancel={() => setDeleteSelectionOpen(false)}
        onConfirm={confirmDeleteSelected}
      />
      <Modal
        open={!!selected}
        title={selected?.title ?? t.title}
        onClose={() => setSelected(null)}
      >
        {selected && (
          <div className="proposal-detail modal-form issue-management-detail">
            <div className="proposal-detail__summary">
              <span>
                {selected.build_name} · {t.run} {selected.run_id}
              </span>
              <StatusBadge
                value={selected.status}
                label={decisionLabel(selected.status)}
              />
              {selected.run_id && selected.iteration != null && (
                <EvidenceViewer
                  className="issue-management-evidence"
                  runId={selected.run_id}
                  iteration={selected.iteration}
                  artifacts={visualEvidenceArtifacts(selected.data_files ?? [])}
                  imageLabel={evidenceCopy.viewImageEvidence}
                  htmlLabel={evidenceCopy.viewHtmlEvidence}
                  imageTitle={evidenceCopy.imageEvidence}
                  htmlTitle={evidenceCopy.htmlEvidence}
                />
              )}
            </div>
            <RunDetailTabs
              activeTab={modalTab}
              onSelect={setModalTab}
              tabs={[
                { id: "details", label: t.details },
                { id: "history", label: t.updated },
              ]}
            />
            {modalTab === "details" ? (
              <>
                {selected.decision_rationale && (
                  <section className="issue-management-rationale">
                    <h3>{t.decisionRationale}</h3>
                    <p>{selected.decision_rationale}</p>
                  </section>
                )}
                {selected.proposal.agent_change && (
                  <section className="issue-management-diff">
                    <h3>{t.agentProposalDiff}</h3>
                    {agentDiff?.proposalId === selected.proposal_id && agentDiff.value ? <UnifiedDiff patch={agentDiff.value} label={t.agentProposalDiff} /> : <p className="hint">{t.noAgentProposalChanges}</p>}
                  </section>
                )}
                {selected.proposal.agent_change && (
                  <section className="issue-management-proposal-action">
                    <h3>{t.agentProposalBranch}</h3>
                    <p>{selected.proposal_branch || "—"}</p>
                    {selected.proposal_commit && <p>{t.committed}: {selected.proposal_commit}</p>}
                    {selected.proposal_action === "pending" && (
                      <div className="modal-actions">
                        <button className="approve" onClick={() => decideAgentProposal("approve")}>{t.approveAndCommit}</button>
                        <button className="danger" onClick={() => decideAgentProposal("reject")}>{t.rejectAndRemove}</button>
                      </div>
                    )}
                  </section>
                )}
                <label className="modal-setting-row">
                  <span>
                    <SectionInfo
                      title={t.managementStatus}
                      description={t.managementStatusHint}
                    />
                  </span>
                  <select
                    value={managementStatus}
                    onChange={(e) => setManagementStatus(e.target.value)}
                  >
                    {statuses.map((value) => (
                      <option key={value} value={value}>
                        {label(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <section className="issue-discussion">
                  <h3><SectionInfo title={t.discussion} description={t.commentHint} /></h3>
                  <div className="issue-discussion__messages">
                    {selected.comments.length ? [...selected.comments].sort((a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at)).map((item, index) => <article className="issue-message" key={`${item.recorded_at}-${index}`}><header><strong>{item.assigner || "—"}</strong><time>{compactTimestamp(locale, item.recorded_at)}</time></header><p>{item.body}</p>{item.verification_run_id && <small>{t.verificationRun} · {item.verification_run_id}</small>}</article>) : <p className="hint">{t.noComments}</p>}
                  </div>
                  <div className="issue-discussion__composer">
                    <input list="issue-comment-authors" value={assigner} placeholder={t.assignerPlaceholder} onChange={(e) => setAssigner(e.target.value)} />
                    <datalist id="issue-comment-authors">{knownAssignees.map((name) => <option key={name} value={name} />)}</datalist>
                    <textarea value={comment} placeholder={t.commentPlaceholder} onChange={(e) => setComment(e.target.value)} />
                    <select value={run} onChange={(e) => setRun(e.target.value)}><option value="">{t.selectVerificationRun}</option>{verificationRuns.map((item) => <option key={item.id} value={item.id}>{item.id} · {compactTimestamp(locale, item.finished_at ?? item.created_at)} · {item.status}</option>)}</select>
                    <div className="modal-actions"><button className="approve" onClick={save} disabled={!comment.trim()}>{t.sendComment}</button></div>
                  </div>
                </section>
              </>
            ) : (
              <section>
                <h3>
                  <SectionInfo title={t.updated} description={t.historyHint} />
                </h3>
                <ol className="proposal-timeline">
                  {selected.management_events.map((e, i) => (
                    <li key={i}>
                      <div>
                        <strong>
                          {new Date(e.recorded_at).toLocaleString()}
                        </strong>
                        <small>
                          {e.type === "status" ? label(e.status ?? "") : e.body}
                          {e.assigner ? ` · ${t.commentAuthor} ${e.assigner}` : ""}
                          {e.verification_run_id
                            ? ` · ${t.run} ${e.verification_run_id}`
                            : ""}
                        </small>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
