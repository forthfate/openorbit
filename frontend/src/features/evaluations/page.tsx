import { Check, ChevronLeft, ChevronRight, CircleStop, Info, Languages, ListFilter, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  Run,
  WorkflowGraphNode,
  CommitChange,
  PromptRevision,
  RunTelemetry,
  SupervisorRecord,
} from "../../domain/models";
import { DataTable, type Column } from "../../components/ui/data-table";
import { ConfirmDialog } from "../../components/ui/confirm-dialog";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { PageSizeSelect } from "../../components/ui/page-size-select";
import { Pagination } from "../../components/ui/pagination";
import { StatusBadge } from "../../components/ui/status-badge";
import { Tooltip } from "../../components/ui/tooltip";
import { WorkflowGraph } from "../../components/workflow-graph";
import { intlLocales, localeMessageMap, locales, type Locale } from "../../locales";
import { api } from "../../services/api";
import { useTemplateTranslations } from "../../services/use-template-translation";
import {
  RunDetailTabPanel,
  RunDetailTabs,
  type RunDetailTab,
} from "./run-detail-tabs";
import {
  CommitChangesPanel,
  PromptChangesPanel,
} from "./run-detail-change-panels";
import {
  CombinedLogPanel,
  WorkflowLogPanel,
} from "./run-detail-log-panels";
import { SupervisorPanel } from "./run-detail-supervisor-panel";
import { EvaluationResultPanel } from "./run-detail-result-panel";

const phases = [
  "before_all",
  "before_each",
  "execute",
  "verify",
  "after_each",
  "after_all",
] as const;
const time = (locale: Locale, value?: string) =>
  value
    ? new Intl.DateTimeFormat(intlLocales[locale], {
        dateStyle: "medium",
        timeStyle: "medium",
      }).format(new Date(value))
    : "—";
const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);
const runStatuses = [
  "queued",
  "awaiting_approval",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];
const activeStatuses = new Set(["queued", "awaiting_approval", "running"]);
const elapsed = (start?: string, end?: string) => {
  if (!start) return "—";
  const seconds = Math.max(
    0,
    Math.floor(
      ((end ? new Date(end) : new Date()).getTime() -
        new Date(start).getTime()) /
        1000,
    ),
  );
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
};
const copy = localeMessageMap<Record<string,string>>("evaluations");
type SupervisorResultTranslation = {
  prompt?: string;
  response: {
    evaluation: { behavior_summary?: string; behavior_trace?: { purpose: string; rationale: string; observation: string; decision: string; next_action: string }; summary?: string };
    improvements: Record<string, string>[];
    reported_issues: Record<string, string>[];
  };
};
function LineNumberedOutput({ value }: { value: string }) {
  return (
    <div className="line-numbered-output">
      {value.split("\n").map((line, index) => (
        <div key={index}>
          <span aria-hidden="true">{index + 1}</span>
          <code>{line || " "}</code>
        </div>
      ))}
    </div>
  );
}
export function EvaluationsPage({
  runs,
  onStop,
  onRetry,
  onApprove,
  onReject,
  onEmergencyStop,
  onDeleteRuns,
  locale,
  initialSelectedRun,
  onSelectedRunClose,
}: {
  runs: Run[];
  onStop: (id: string) => void;
  onRetry: (id: string, restartFromFirst: boolean) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEmergencyStop: () => void;
  onDeleteRuns: (ids: string[]) => Promise<unknown>;
  locale: Locale;
  initialSelectedRun?: Run | null;
  onSelectedRunClose?: () => void;
}) {
  const t = locales[locale].common,
    l = copy[locale],
    ui = locales[locale].runUi;
  const [selectedInternal, setSelected] = useState<Run | null>(null),
    [tab, setTab] = useState<RunDetailTab>("result"),
    [phaseTab, setPhaseTab] = useState<(typeof phases)[number]>("before_all"),
    [iterationTab, setIterationTab] = useState(1),
    [candidateTab, setCandidateTab] = useState<string | null>(null),
    [telemetry, setTelemetry] = useState<RunTelemetry>(),
    [promptRevisions, setPromptRevisions] = useState<PromptRevision[]>([]),
    [commitChanges, setCommitChanges] = useState<CommitChange[]>([]),
    [statuses, setStatuses] = useState<Set<string>>(() => new Set(runStatuses)),
    [buildFilter, setBuildFilter] = useState(""),
    [modeFilter, setModeFilter] = useState<"all" | "run" | "test">("all"),
    [phaseFilter, setPhaseFilter] = useState(""),
    [keywordFilter, setKeywordFilter] = useState(""),
    [activeOnly, setActiveOnly] = useState(false),
    [filtersOpen, setFiltersOpen] = useState(false),
    [draftStatuses, setDraftStatuses] = useState<Set<string>>(
      () => new Set(runStatuses),
    ),
    [draftBuildFilter, setDraftBuildFilter] = useState(""),
    [draftModeFilter, setDraftModeFilter] = useState<"all" | "run" | "test">(
      "all",
    ),
    [draftPhaseFilter, setDraftPhaseFilter] = useState(""),
    [draftKeywordFilter, setDraftKeywordFilter] = useState(""),
    [draftActiveOnly, setDraftActiveOnly] = useState(false),
    [resultFiltersOpen, setResultFiltersOpen] = useState(false),
    [resultIterationFilter, setResultIterationFilter] = useState<"all" | "latest" | "range">("all"),
    [resultIterationFrom, setResultIterationFrom] = useState(""),
    [resultIterationTo, setResultIterationTo] = useState(""),
    [resultDecisions, setResultDecisions] = useState<Set<string>>(
      () => new Set(["approved", "rejected", "pending", "no_response"]),
    ),
    [resultScoreBucket, setResultScoreBucket] = useState("all"),
    [resultContent, setResultContent] = useState<"all" | "improvements" | "issues" | "empty">("all"),
    [resultAttemptFilter, setResultAttemptFilter] = useState("all"),
    [resultImprovementStatus, setResultImprovementStatus] = useState("all"),
    [resultIssueSeverity, setResultIssueSeverity] = useState("all"),
    [resultIssueStatus, setResultIssueStatus] = useState("all"),
    [draftResultIterationFilter, setDraftResultIterationFilter] = useState<"all" | "latest" | "range">("all"),
    [draftResultIterationFrom, setDraftResultIterationFrom] = useState(""),
    [draftResultIterationTo, setDraftResultIterationTo] = useState(""),
    [draftResultDecisions, setDraftResultDecisions] = useState<Set<string>>(
      () => new Set(["approved", "rejected", "pending", "no_response"]),
    ),
    [draftResultScoreBucket, setDraftResultScoreBucket] = useState("all"),
    [draftResultContent, setDraftResultContent] = useState<"all" | "improvements" | "issues" | "empty">("all"),
    [draftResultAttemptFilter, setDraftResultAttemptFilter] = useState("all"),
    [draftResultImprovementStatus, setDraftResultImprovementStatus] = useState("all"),
    [draftResultIssueSeverity, setDraftResultIssueSeverity] = useState("all"),
    [draftResultIssueStatus, setDraftResultIssueStatus] = useState("all");
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set()),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(15),
    [deleteSelectionOpen, setDeleteSelectionOpen] = useState(false),
    [retryingRun, setRetryingRun] = useState<Run | null>(null);
  const retryCopy = locale === "ko" ? { title: "실행 재시도", warning: "재시도는 작업 디렉터리 또는 외부 대상의 중간 결과를 변경할 수 있습니다.", restart: "1부터 다시 시작", resume: "마지막 이터레이션부터 재시도", cancel: "취소" } : locale === "ja" ? { title: "実行を再試行", warning: "再試行により作業ディレクトリまたは外部ターゲットの中間結果が変わる可能性があります。", restart: "反復 1 から再開", resume: "最後の反復から再試行", cancel: "キャンセル" } : { title: "Retry run", warning: "Retrying can change intermediate results in the working directory or external target.", restart: "Restart from iteration 1", resume: "Retry from the last iteration", cancel: "Cancel" };
  const selected = initialSelectedRun ?? selectedInternal;
  const supervisorTranslationIds = useMemo(
    () =>
      (selected?.supervisor_results ?? [])
        .filter((record) => Boolean(record.response))
        .map((record) => `${selected?.id}:${record.iteration}`),
    [selected],
  );
  const supervisorTranslations = useTemplateTranslations<SupervisorResultTranslation>(
    "supervisor-result",
    supervisorTranslationIds,
    locale,
  );
  const resultTranslations = useTemplateTranslations<SupervisorResultTranslation>(
    "supervisor-result",
    supervisorTranslationIds,
    locale,
  );
  const translateSupervisorResponse = (record: SupervisorRecord) => {
    const response = record.response;
    const translated = supervisorTranslations.content(`${selected?.id}:${record.iteration}`);
    if (!response || !translated) return response;
    return {
      ...response,
      evaluation: response.evaluation
        ? { ...response.evaluation, ...translated.response.evaluation }
        : response.evaluation,
      improvements: response.improvements.map((item, index) => ({
        ...item,
        ...translated.response.improvements[index],
      })),
      reported_issues: response.reported_issues.map((item, index) => ({
        ...item,
        ...translated.response.reported_issues[index],
      })),
    };
  };
  const translateSupervisorRecord = (record?: SupervisorRecord) => {
    if (!record) return record;
    const translated = supervisorTranslations.content(`${selected?.id}:${record.iteration}`);
    if (!translated) return record;
    return {
      ...record,
      ...(translated.prompt ? { prompt: translated.prompt } : {}),
      response: translateSupervisorResponse(record),
    };
  };
  const translateResultResponse = (record: SupervisorRecord) => {
    const response = record.response;
    const translated = resultTranslations.content(`${selected?.id}:${record.iteration}`);
    if (!response || !translated) return response;
    return {
      ...response,
      evaluation: response.evaluation
        ? { ...response.evaluation, ...translated.response.evaluation }
        : response.evaluation,
      improvements: response.improvements.map((item, index) => ({
        ...item,
        ...translated.response.improvements[index],
      })),
      reported_issues: response.reported_issues.map((item, index) => ({
        ...item,
        ...translated.response.reported_issues[index],
      })),
    };
  };
  const translationCopy = locales[locale].templateTranslation;
  const filterMenu = useRef<HTMLDivElement>(null),
    resultFilterMenu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected)
      api<RunTelemetry>(`/api/runs/${selected.id}/telemetry`)
        .then(setTelemetry)
        .catch(() => setTelemetry({ spans: [] }));
  }, [selected]);
  useEffect(() => {
    if (!selected) return;
    api<CommitChange[]>(`/api/runs/${selected.id}/commit-changes`)
      .then(setCommitChanges)
      .catch(() => setCommitChanges([]));
  }, [selected]);
  useEffect(() => {
    if (!selected) return;
    api<PromptRevision[]>(`/api/runs/${selected.id}/prompt-revisions`)
      .then(setPromptRevisions)
      .catch(() => setPromptRevisions([]));
  }, [selected]);
  const label = (status: string) =>
    ({
      queued: ui.queued,
      awaiting_approval: ui.awaitingApproval,
      running: ui.running,
      succeeded: l.complete,
      cancelled: l.cancelled,
      failed: l.failed,
    })[status] ?? status;
  const finalPhase = (run: Run) => {
    if (run.status === "succeeded") return l.complete;
    if (run.status === "cancelled") return l.cancelled;
    if (run.status === "failed") return l.failed;
    return run.current_phase === "waiting" ? l.waiting : (run.current_phase ?? "—");
  };
  const builds = useMemo(
    () => [
      ...new Map(
        runs.map((run) => [
          run.build_id ?? run.workflow_id,
          {
            id: run.build_id ?? run.workflow_id,
            name:
              run.build_name ??
              run.build_id ??
              run.workflow_name,
          },
        ]),
      ).values(),
    ],
    [runs],
  );
  const filteredRuns = runs.filter(
    (run) =>
      statuses.has(run.status) &&
      (!buildFilter ||
        (run.build_id ?? run.workflow_id) === buildFilter) &&
      (modeFilter === "all" || run.execution_mode === modeFilter) &&
      (!phaseFilter || run.current_phase === phaseFilter) &&
      (!keywordFilter || [run.id, run.build_name, run.build_id, run.workflow_name, run.status, run.current_phase].some((value) => value?.includes(keywordFilter))) &&
      (!activeOnly || activeStatuses.has(run.status)),
  );
  const toggleStatus = (status: string) =>
    setDraftStatuses((current) => {
      const next = new Set(current);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  const resetFilters = () => {
    setDraftStatuses(new Set(runStatuses));
    setDraftBuildFilter("");
    setDraftModeFilter("all");
    setDraftPhaseFilter("");
    setDraftKeywordFilter("");
    setDraftActiveOnly(false);
  };
  const closeFilters = () => setFiltersOpen(false);
  const openFilters = () => {
    setDraftStatuses(new Set(statuses));
    setDraftBuildFilter(buildFilter);
    setDraftModeFilter(modeFilter);
    setDraftPhaseFilter(phaseFilter);
    setDraftKeywordFilter(keywordFilter);
    setDraftActiveOnly(activeOnly);
    setFiltersOpen(true);
  };
  const applyFilters = () => {
    setStatuses(new Set(draftStatuses));
    setBuildFilter(draftBuildFilter);
    setModeFilter(draftModeFilter);
    setPhaseFilter(draftPhaseFilter);
    setKeywordFilter(draftKeywordFilter);
    setActiveOnly(draftActiveOnly);
    setPage(1);
    closeFilters();
  };
  const resetResultFilters = () => {
    setDraftResultIterationFilter("all");
    setDraftResultIterationFrom("");
    setDraftResultIterationTo("");
    setDraftResultDecisions(new Set(["approved", "rejected", "pending", "no_response"]));
    setDraftResultScoreBucket("all");
    setDraftResultContent("all");
    setDraftResultAttemptFilter("all");
    setDraftResultImprovementStatus("all");
    setDraftResultIssueSeverity("all");
    setDraftResultIssueStatus("all");
  };
  const openResultFilters = () => {
    setDraftResultIterationFilter(resultIterationFilter);
    setDraftResultIterationFrom(resultIterationFrom);
    setDraftResultIterationTo(resultIterationTo);
    setDraftResultDecisions(new Set(resultDecisions));
    setDraftResultScoreBucket(resultScoreBucket);
    setDraftResultContent(resultContent);
    setDraftResultAttemptFilter(resultAttemptFilter);
    setDraftResultImprovementStatus(resultImprovementStatus);
    setDraftResultIssueSeverity(resultIssueSeverity);
    setDraftResultIssueStatus(resultIssueStatus);
    setResultFiltersOpen(true);
  };
  const applyResultFilters = () => {
    setResultIterationFilter(draftResultIterationFilter);
    setResultIterationFrom(draftResultIterationFrom);
    setResultIterationTo(draftResultIterationTo);
    setResultDecisions(new Set(draftResultDecisions));
    setResultScoreBucket(draftResultScoreBucket);
    setResultContent(draftResultContent);
    setResultAttemptFilter(draftResultAttemptFilter);
    setResultImprovementStatus(draftResultImprovementStatus);
    setResultIssueSeverity(draftResultIssueSeverity);
    setResultIssueStatus(draftResultIssueStatus);
    setResultFiltersOpen(false);
  };
  const toggleResultDecision = (decision: string) =>
    setDraftResultDecisions((current) => {
      const next = new Set(current);
      if (next.has(decision)) next.delete(decision);
      else next.add(decision);
      return next;
    });
  const appliedFilterCount =
    Number(statuses.size !== runStatuses.length) +
    Number(Boolean(buildFilter)) +
    Number(modeFilter !== "all") +
    Number(Boolean(phaseFilter)) +
    Number(Boolean(keywordFilter)) +
    Number(activeOnly);
  const resultAppliedFilterCount =
    Number(resultIterationFilter !== "all") +
    Number(resultDecisions.size !== 4) +
    Number(resultScoreBucket !== "all") +
    Number(resultContent !== "all") +
    Number(resultAttemptFilter !== "all") +
    Number(resultImprovementStatus !== "all") +
    Number(resultIssueSeverity !== "all") +
    Number(resultIssueStatus !== "all");
  const totalPages = Math.max(1, Math.ceil(filteredRuns.length / pageSize)),
    currentPage = Math.min(page, totalPages),
    pagedRuns = filteredRuns.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    selectableRuns = pagedRuns.filter((run) => terminal(run.status)),
    allPageSelected = selectableRuns.length > 0 && selectableRuns.every((run) => selectedRunIds.has(run.id));
  const toggleRun = (id: string) => setSelectedRunIds(current => { const next=new Set(current);if(next.has(id))next.delete(id);else next.add(id);return next })
  const togglePage = () => setSelectedRunIds(current => { const next=new Set(current);if(allPageSelected)selectableRuns.forEach(run=>next.delete(run.id));else selectableRuns.forEach(run=>next.add(run.id));return next })
  const deleteSelected = () => { if(selectedRunIds.size)setDeleteSelectionOpen(true) }
  const confirmDeleteSelected = () => { const ids=[...selectedRunIds];setDeleteSelectionOpen(false);onDeleteRuns(ids).then(()=>setSelectedRunIds(new Set())) }
  useEffect(() => {
    if (!filtersOpen) return;
    const close = (event: PointerEvent) => {
      if (
        filterMenu.current &&
        !filterMenu.current.contains(event.target as Node)
      )
        closeFilters();
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [filtersOpen]);
  useEffect(() => {
    if (!resultFiltersOpen) return;
    const close = (event: PointerEvent) => {
      if (
        resultFilterMenu.current &&
        !resultFilterMenu.current.contains(event.target as Node)
      )
        setResultFiltersOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [resultFiltersOpen]);
  const columns: Column<Run>[] = [
    {id:"select",header:<input aria-label="Select all runs on this page" type="checkbox" checked={allPageSelected} disabled={!selectableRuns.length} onChange={togglePage}/>,render:r=><input aria-label={`Select run ${r.id}`} type="checkbox" checked={selectedRunIds.has(r.id)} disabled={!terminal(r.status)} onChange={()=>toggleRun(r.id)}/>},
    {
      id: "build",
      header: t.build,
      render: (r) => (
        <span className="run-build">
          <strong>{r.build_name ?? r.build_id}</strong>
          <code>{r.id}</code>
        </span>
      ),
      sortValue: (r) => r.build_name ?? r.build_id ?? r.workflow_name,
    },
    {
      id: "started",
      header: t.started,
      render: (r) => time(locale, r.created_at),
      sortValue: (r) => r.created_at ?? "",
    },
    {
      id: "elapsed",
      header: t.elapsed,
      render: (r) =>
        elapsed(
          r.created_at,
          terminal(r.status) ? (r.finished_at ?? r.updated_at) : undefined,
        ),
      sortValue: (r) => terminal(r.status) && r.finished_at
        ? new Date(r.finished_at).getTime() - new Date(r.created_at ?? 0).getTime()
        : 0,
    },
    {
      id: "phase",
      header: t.phase,
      render: (r) => (
        <span className={`run-phase run-phase--${r.status}`}>
          {finalPhase(r)}
        </span>
      ),
      sortValue: (r) => finalPhase(r),
    },
    { id: "pid", header: t.pid, render: (r) => r.pid ?? r.last_pid ?? "—", sortValue: (r) => r.pid ?? r.last_pid ?? -1 },
    {
      id: "proposed",
      header: t.proposed,
      render: (r) => r.proposed_improvements ?? 0,
      sortValue: (r) => r.proposed_improvements ?? 0,
    },
    {
      id: "approved",
      header: t.approved,
      render: (r) => r.approved_improvements ?? 0,
      sortValue: (r) => r.approved_improvements ?? 0,
    },
    { id: "issues", header: t.issues, render: (r) => r.reported_issues ?? 0, sortValue: (r) => r.reported_issues ?? 0 },
    {
      id: "status",
      header: t.status,
      render: (r) => <StatusBadge value={r.status} label={label(r.status)} />,
      sortValue: (r) => label(r.status),
    },
    {
      id: "actions",
      header: locales[locale].evaluation.action,
      render: (r) => (
        <span className="build-actions">
          {r.status === "awaiting_approval" && (
            <>
              <button
                className="approve icon-button"
                title={l.approve}
                aria-label={l.approve}
                onClick={() => onApprove(r.id)}
              >
                <Check size={16} />
              </button>
              <button
                className="icon-button danger"
                title={l.reject}
                aria-label={l.reject}
                onClick={() => onReject(r.id)}
              >
                <X size={16} />
              </button>
            </>
          )}
          {["failed", "cancelled"].includes(r.status) && r.execution_type === "pipeline" && (
            <button className="icon-button" title={retryCopy.title} aria-label={retryCopy.title} onClick={(event) => { event.stopPropagation(); setRetryingRun(r); }}>
              <RotateCcw size={16} />
            </button>
          )}
          <button
            className="icon-button danger"
            title={t.stop}
            aria-label={t.stop}
            disabled={
              !["queued", "running", "awaiting_approval"].includes(r.status)
            }
            onClick={() => onStop(r.id)}
          >
            <CircleStop size={16} />
          </button>
        </span>
      ),
    },
  ];
  columns[1].header = l.task;
  columns.splice(4, 0, {
    id: "iteration",
    header: l.iteration,
    render: (r) => {
      const current = Math.max(
        0,
        ...(r.step_results ?? []).map((step) => step.loop_index ?? 0),
      );
      return current ? `${current}/${r.loop_limit ?? current}` : "—";
    },
    sortValue: (r) => Math.max(0, ...(r.step_results ?? []).map((step) => step.loop_index ?? 0)),
  });
  const steps = useMemo(() => selected?.step_results ?? [], [selected?.step_results]);
  const iterations =
    // `after_all` is bookkeeping after the last loop. It must not become the
    // default detail iteration because supervisor results belong to execute/verify.
    [
      ...new Set([
        ...steps
          .filter((step) => ["execute", "verify"].includes(step.phase ?? step.step_id ?? ""))
          .map((step) => step.loop_index ?? 0)
          .filter((index) => index > 0),
        ...(selected?.supervisor_results ?? []).map((item) => item.iteration ?? 0).filter((index) => index > 0),
      ]),
    ].sort((a, b) => a - b);
    // `before_all` and `after_all` are process-level steps, not iterations.
    // Include them beside the relevant iteration so their evidence remains
    // visible without inventing a separate, misleading iteration.
  const selectedSteps = steps.filter(
      (step) =>
        (!candidateTab || step.candidate_id === candidateTab) &&
        (step.loop_index === iterationTab ||
          ((step.phase ?? step.step_id) === "before_all" && iterationTab === iterations[0]) ||
          ((step.phase ?? step.step_id) === "after_all" && iterationTab === iterations.at(-1))),
    );
  const availablePhases = phases.filter((phase) =>
    selectedSteps.some((step) => (step.phase ?? step.step_id) === phase),
  );
  const supervision = selected?.supervisor_results?.find(
    (item) => item.iteration === iterationTab && (!candidateTab || item.candidate_id === candidateTab),
  );
  const result = supervision?.response;
  const evaluation = result?.evaluation;
  const workflowGraph = useMemo(() => {
    const definition = selected?.workflow_graph;
    if (!definition?.nodes.length) return null;
    return {
      ...definition,
      nodes: definition.nodes.map((node) => {
        const phaseSteps = steps.filter((step) => (step.phase ?? step.step_id) === node.phase);
        const latestStep = phaseSteps.at(-1);
        const status: WorkflowGraphNode["status"] = selected?.status === "running" && node.phase === selected.current_phase
          ? "running"
          : latestStep?.error || (latestStep?.exit_code ?? 0) !== 0
            ? "failed"
            : latestStep
              ? "succeeded"
              : "idle";
        return { ...node, status };
      }),
    };
  }, [selected, steps]);
  const resultFilterOptions = useMemo(() => {
    const improvementStatuses = new Set<string>(),
      issueSeverities = new Set<string>(),
      issueStatuses = new Set<string>();
    for (const record of selected?.supervisor_results ?? []) {
      for (const improvement of record.response?.improvements ?? []) {
        if (improvement.status) improvementStatuses.add(String(improvement.status));
      }
      for (const issue of record.response?.reported_issues ?? []) {
        if (issue.severity) issueSeverities.add(String(issue.severity));
        if (issue.status) issueStatuses.add(String(issue.status));
      }
    }
    return {
      improvementStatuses: [...improvementStatuses].sort(),
      issueSeverities: [...issueSeverities].sort(),
      issueStatuses: [...issueStatuses].sort(),
    };
  }, [selected]);
  const resultRecords = useMemo(() => {
    const records = [...(selected?.supervisor_results ?? [])].sort(
      (a, b) => b.iteration - a.iteration,
    );
    const latestIteration = records[0]?.iteration;
    return records.filter((record) => {
      const response = translateResultResponse(record),
        recordEvaluation = response?.evaluation,
        decision = recordEvaluation?.approval ?? "no_response",
        score = recordEvaluation?.score,
        improvements = response?.improvements ?? [],
        issues = response?.reported_issues ?? [];
      const inRange =
        (!resultIterationFrom || record.iteration >= Number(resultIterationFrom)) &&
        (!resultIterationTo || record.iteration <= Number(resultIterationTo));
      const scoreMatches =
        resultScoreBucket === "all" ||
        (resultScoreBucket === "missing" && score === undefined) ||
        (resultScoreBucket === "low" && score !== undefined && score <= 3) ||
        (resultScoreBucket === "medium" && score !== undefined && score >= 4 && score <= 6) ||
        (resultScoreBucket === "good" && score !== undefined && score >= 7 && score <= 8) ||
        (resultScoreBucket === "excellent" && score !== undefined && score >= 9 && score <= 10);
      const contentMatches =
        resultContent === "all" ||
        (resultContent === "improvements" && improvements.length > 0) ||
        (resultContent === "issues" && issues.length > 0) ||
        (resultContent === "empty" && improvements.length === 0 && issues.length === 0);
      const attemptMatches =
        resultAttemptFilter === "all" ||
        improvements.some((improvement) =>
          resultAttemptFilter === "attempted"
            ? improvement.attempted === true || improvement.status === "adopted"
            : improvement.attempted !== true && improvement.status !== "adopted",
        );
      const improvementStatusMatches =
        resultImprovementStatus === "all" ||
        improvements.some(
          (improvement) => String(improvement.status ?? "—") === resultImprovementStatus,
        );
      const issueSeverityMatches =
        resultIssueSeverity === "all" ||
        issues.some((issue) => String(issue.severity ?? "—") === resultIssueSeverity);
      const issueStatusMatches =
        resultIssueStatus === "all" ||
        issues.some((issue) => String(issue.status ?? "—") === resultIssueStatus);
      return (
        (!candidateTab || record.candidate_id === candidateTab) &&
        resultDecisions.has(decision) &&
        scoreMatches &&
        contentMatches &&
        attemptMatches &&
        improvementStatusMatches &&
        issueSeverityMatches &&
        issueStatusMatches &&
        (resultIterationFilter !== "range" || inRange) &&
        (resultIterationFilter !== "latest" || record.iteration === latestIteration)
      );
    });
  }, [
    selected,
    candidateTab,
    resultContent,
    resultDecisions,
    resultAttemptFilter,
    resultImprovementStatus,
    resultIssueSeverity,
    resultIssueStatus,
    resultIterationFilter,
    resultIterationFrom,
    resultIterationTo,
    resultScoreBucket,
  ]);
  const supervisorTranslationId = supervision?.response
    ? `${selected?.id}:${supervision.iteration}`
    : null;
  const resultTranslationIds = resultRecords
    .filter((record) => Boolean(record.response))
    .map((record) => `${selected?.id}:${record.iteration}`);
  const supervisorTranslationVisible = Boolean(
    supervisorTranslationId && supervisorTranslations.content(supervisorTranslationId),
  );
  const supervisorTranslationLoading = Boolean(
    supervisorTranslationId && supervisorTranslations.isLoading([supervisorTranslationId]),
  );
  const resultTranslationsVisible =
    resultTranslationIds.length > 0 &&
    resultTranslationIds.every((templateId) => Boolean(resultTranslations.content(templateId)));
  const resultTranslationsLoading = resultTranslations.isLoading(resultTranslationIds);
  const resultImprovements = resultRecords.flatMap((record) =>
      (translateResultResponse(record)?.improvements ?? []).map((item) => ({
        ...item,
        __iteration: record.iteration,
      })),
    ),
  resultIssues = resultRecords.flatMap((record) =>
      (translateResultResponse(record)?.reported_issues ?? []).map((item) => ({
        ...item,
        __iteration: record.iteration,
      })),
    );
  const resultBehaviorTraces = resultRecords.flatMap((record) => {
      const item = {
      iteration: record.iteration,
      recordedAt: record.recorded_at,
      trace: translateResultResponse(record)?.evaluation?.behavior_trace,
      summary: translateResultResponse(record)?.evaluation?.behavior_summary,
      };
      return item.trace || item.summary ? [item] : [];
    });
  const iterationPosition = iterations.indexOf(iterationTab),
    previousIteration = iterations[iterationPosition - 1],
    nextIteration = iterations[iterationPosition + 1];
  const iterationNavigator =
    tab !== "result" && tab !== "prompt" && iterations.length > 0 ? (
      <div className="iteration-navigator" aria-label={l.iteration}>
        <button className="ghost icon-button" type="button" aria-label={ui.previousIteration} title={ui.previousIteration} disabled={previousIteration === undefined} onClick={() => {
          if (previousIteration !== undefined) {
            setIterationTab(previousIteration);
            setCandidateTab(selected?.iteration_candidates?.find((candidate) => candidate.iteration === previousIteration && candidate.selected)?.id ?? null);
          }
        }}><ChevronLeft size={16} /></button>
        <select aria-label={l.iteration} value={iterationTab} onChange={(event) => {
          const next = Number(event.target.value);
          setIterationTab(next);
          setCandidateTab(selected?.iteration_candidates?.find((candidate) => candidate.iteration === next && candidate.selected)?.id ?? null);
        }}>{[...iterations].reverse().map((iteration) => <option key={iteration} value={iteration}>#{iteration}</option>)}</select>
        <button className="ghost icon-button" type="button" aria-label={ui.nextIteration} title={ui.nextIteration} disabled={nextIteration === undefined} onClick={() => {
          if (nextIteration !== undefined) {
            setIterationTab(nextIteration);
            setCandidateTab(selected?.iteration_candidates?.find((candidate) => candidate.iteration === nextIteration && candidate.selected)?.id ?? null);
          }
        }}><ChevronRight size={16} /></button>
      </div>
    ) : undefined;
  return (
    <section className="panel active-evaluation-panel">
      <div className="panel-title-action">
        <div className="panel-title-action__copy">
          <PanelHeader
            title={
              <Tooltip content={t.runHistoryHint}>
                <span className="panel-title-with-tooltip">
                  {l.title}
                  <Info size={15} />
                </span>
              </Tooltip>
            }
          />
          <p className="hint section-description">{t.runHistoryDescription}</p>
        </div>
        <button className="emergency" onClick={onEmergencyStop}>
          <CircleStop size={15} />
          {t.emergencyStop}
        </button>
      </div>
      <div className="run-filter-trigger" ref={filterMenu}>
        <button
          className="ghost run-filter-button"
          aria-expanded={filtersOpen}
          onClick={() => (filtersOpen ? closeFilters() : openFilters())}
        >
          <ListFilter size={15} />
          {ui.filter}
          {appliedFilterCount > 0 && <span className="nav-run-count">{appliedFilterCount}</span>}
        </button>
        <PageSizeSelect locale={locale} value={pageSize} onChange={value=>{setPageSize(value);setPage(1)}}/>
        {filtersOpen && (
          <div className="run-filters run-filter-popover">
            <div className="run-filter-popover__header">
              <strong>{ui.filter}</strong>
              <button className="ghost" onClick={resetFilters}>
                {ui.reset}
              </button>
            </div>
            <fieldset>
              <legend>
                {ui.status}
              </legend>
              <div className="run-filters__statuses">
                {runStatuses.map((status) => (
                  <label key={status}>
                    <input
                      type="checkbox"
                      checked={draftStatuses.has(status)}
                      onChange={() => toggleStatus(status)}
                    />
                    {label(status)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label>
              {ui.keyword}
              <input value={draftKeywordFilter} onChange={(event) => setDraftKeywordFilter(event.target.value)} placeholder={ui.keywordHint} />
            </label>
            <label>
              {ui.build}
              <select
                value={draftBuildFilter}
                onChange={(event) => setDraftBuildFilter(event.target.value)}
              >
                <option value="">
                  {ui.allBuilds}
                </option>
                {builds.map((build) => (
                  <option key={build.id} value={build.id}>
                    {build.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {ui.runType}
              <select
                value={draftModeFilter}
                onChange={(event) =>
                  setDraftModeFilter(event.target.value as "all" | "run" | "test")
                }
              >
                <option value="all">
                  {ui.all}
                </option>
                <option value="run">Run</option>
                <option value="test">Test</option>
              </select>
            </label>
            <label>
              {ui.phase}
              <select
                value={draftPhaseFilter}
                onChange={(event) => setDraftPhaseFilter(event.target.value)}
              >
                <option value="">
                  {ui.allPhases}
                </option>
                {availablePhases.map((phase) => (
                  <option key={phase} value={phase}>
                    {phase}
                  </option>
                ))}
                <option value="waiting">{l.waiting}</option>
              </select>
            </label>
            <label className="run-filters__active">
              <input
                type="checkbox"
                checked={draftActiveOnly}
                onChange={(event) => setDraftActiveOnly(event.target.checked)}
              />
              {ui.activeOnly}
            </label>
            <div className="run-filter-popover__footer">
              <button className="ghost" onClick={closeFilters}>
                {l.cancel}
              </button>
              <button className="approve" onClick={applyFilters}>
                {l.apply}
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="run-history-actions">
        <span>{ui.selected(selectedRunIds.size)}</span>
        <button className="ghost" onClick={() => setSelectedRunIds(new Set())} disabled={!selectedRunIds.size}>{ui.deselect}</button>
        <button className="icon-button danger" aria-label={ui.deleteSelected} title={ui.deleteSelected} onClick={deleteSelected} disabled={!selectedRunIds.size}><Trash2 size={15}/></button>
      </div>
      <DataTable
        columns={columns}
        rows={pagedRuns}
        onRowClick={(r) => {
          const latest = Math.max(
            1,
            ...(r.step_results ?? [])
              .filter((step) => ["execute", "verify"].includes(step.phase ?? step.step_id ?? ""))
              .map((step) => step.loop_index ?? 0),
            ...(r.supervisor_results ?? []).map((item) => item.iteration ?? 0),
          );
          setSelected(r);
          setTab("result");
          setPhaseTab("before_all");
          setIterationTab(latest);
          setCandidateTab(r.iteration_candidates?.find((candidate) => candidate.iteration === latest && candidate.selected)?.id ?? null);
        }}
        className="active-evaluation-table"
        gridTemplateColumns="36px minmax(220px,2fr) minmax(145px,1fr) 82px 90px 72px 96px 96px 82px 94px 72px 72px"
        empty={t.noRuns}
      />
      <Pagination locale={locale} page={currentPage} totalPages={totalPages} totalItems={filteredRuns.length} pageSize={pageSize} onPageChange={setPage}/>
      <ConfirmDialog open={deleteSelectionOpen} title={ui.deleteSelectedTitle} description={ui.deleteSelectedDescription(selectedRunIds.size)} cancelLabel={l.cancel} confirmLabel={ui.delete} onCancel={()=>setDeleteSelectionOpen(false)} onConfirm={confirmDeleteSelected}/>
      {selected && (
        <Modal
          open
          title={l.detail}
          onClose={() => {
            setSelected(null);
            onSelectedRunClose?.();
          }}
          className="modal--run-detail"
        >
          <div className="run-detail-evaluation">
            <strong>
              {selected.build_name ??
                selected.build_id ??
                selected.workflow_name}
            </strong>
            <code>{selected.id}</code>
          </div>
          <div className="run-detail-summary">
            <div>
              <small>{l.status}</small>
              <StatusBadge
                value={selected.status}
                label={label(selected.status)}
              />
            </div>
            <div>
              <small>{l.phase}</small>
              <strong>{finalPhase(selected)}</strong>
            </div>
            <div>
              <small>{t.elapsed}</small>
              <strong>
                {elapsed(
                  selected.created_at,
                  terminal(selected.status)
                    ? (selected.finished_at ?? selected.updated_at)
                    : undefined,
                )}
              </strong>
            </div>
            <div>
              <small>{l.score}</small>
              <strong>{evaluation ? `${evaluation.score}/10` : "—"}</strong>
            </div>
            <div>
              <small>{l.decision}</small>
              <strong>{evaluation?.approval ?? "—"}</strong>
            </div>
          </div>
          <section className="run-detail-workflow-graph" aria-label={l.workflowGraph}>
            {workflowGraph ? (
              <WorkflowGraph nodes={workflowGraph.nodes} edges={workflowGraph.edges} />
            ) : (
              <p className="hint">{l.noWorkflowGraph}</p>
            )}
          </section>
          <RunDetailTabs
            activeTab={tab}
            onSelect={setTab}
            tabs={[
              { id: "result", label: l.result },
              { id: "prompt", label: l.promptChanges },
              { id: "commits", label: l.commitChanges },
              { id: "supervisor", label: l.supervisor },
              { id: "workflow", label: l.workflow },
              { id: "logs", label: l.logs },
            ]}
          />
          {tab !== "result" && tab !== "prompt" && iterations.length > 0 && (
            <>
            {selected.iteration_strategy === "score_select" && (
              <div className="iteration-candidates">
                {(selected.iteration_candidates ?? []).filter((candidate) => candidate.iteration === iterationTab).map((candidate) => (
                  <button type="button" key={candidate.id} onClick={() => setCandidateTab(candidate.id)} className={candidateTab === candidate.id ? "selected" : ""}>
                    <b>{candidate.id}</b><small>{candidate.score ?? "—"}/10</small>{candidate.selected && <em>Winner</em>}
                  </button>
                ))}
              </div>
            )}
            </>
          )}
          {tab === "workflow" && (
            <RunDetailTabPanel description={l.workflowDescription} hint={l.workflowDataHint} action={iterationNavigator}>
              <div className="run-tabs phase-tabs">
                {phases.map((phase) => (
                  <button
                    key={phase}
                    className={phaseTab === phase ? "active" : ""}
                    onClick={() => setPhaseTab(phase)}
                  >
                    {phase}
                  </button>
                ))}
              </div>
              <WorkflowLogPanel
                locale={locale}
                steps={selectedSteps.filter(
                  (step) => (step.phase ?? step.step_id) === phaseTab,
                )}
                empty={l.noCommandsForPhase}
              />
            </RunDetailTabPanel>
          )}
          {tab === "logs" && (
            <RunDetailTabPanel description={l.logsDescription} hint={l.logsDataHint} action={iterationNavigator}>
              <CombinedLogPanel
                steps={selectedSteps}
                locale={locale}
                empty={l.noLogs}
                orbitLogs={l.orbitLogs}
                targetLogs={l.targetLogs}
              />
            </RunDetailTabPanel>
          )}
          {tab === "prompt" && (
            <RunDetailTabPanel description={l.promptChangesDescription} hint={l.promptDataHint}>
              <PromptChangesPanel
                key={selected.id}
                revisions={promptRevisions}
                l={l}
                renderLineOutput={(value) => <LineNumberedOutput value={value} />}
              />
            </RunDetailTabPanel>
          )}
          {tab === "commits" && (
            <RunDetailTabPanel description={l.commitChangesDescription} hint={l.commitsDataHint} action={iterationNavigator}>
              <CommitChangesPanel changes={commitChanges} l={l} />
            </RunDetailTabPanel>
          )}
          {tab === "supervisor" && (
            <RunDetailTabPanel description={l.supervisorDescription} hint={l.supervisorDataHint} action={iterationNavigator}>
              {supervisorTranslationId && (
                <div className="supervisor-translation-action">
                  <button
                    className="ghost"
                    type="button"
                    disabled={supervisorTranslationLoading}
                    onClick={() =>
                      supervisorTranslationVisible
                        ? supervisorTranslations.showOriginal([supervisorTranslationId])
                        : supervisorTranslations.translate([supervisorTranslationId])
                    }
                  >
                    <Languages size={15} />
                    {supervisorTranslationLoading
                      ? translationCopy.translating
                      : supervisorTranslationVisible
                        ? translationCopy.showOriginal
                        : translationCopy.translate}
                  </button>
                </div>
              )}
              {supervisorTranslations.error && <small className="hint">{translationCopy.failed}</small>}
              <SupervisorPanel
                record={translateSupervisorRecord(supervision)}
                l={l}
                telemetry={telemetry}
                iteration={iterationTab}
                renderLineOutput={(value) => <LineNumberedOutput value={value} />}
              />
            </RunDetailTabPanel>
          )}
          {tab === "result" && (
            <RunDetailTabPanel description={l.resultDescription} hint={l.resultDataHint}>
              <div className="run-result">
              <div className="result-filter-trigger" ref={resultFilterMenu}>
                <button
                  className="ghost run-filter-button"
                  aria-expanded={resultFiltersOpen}
                  onClick={() =>
                    resultFiltersOpen ? setResultFiltersOpen(false) : openResultFilters()
                  }
                >
                  <ListFilter size={15} />
                  {l.filter}
                  {resultAppliedFilterCount > 0 && <span className="nav-run-count">{resultAppliedFilterCount}</span>}
                </button>
                {resultTranslationIds.length > 0 && (
                  <button
                    className="ghost result-translation-action"
                    type="button"
                    disabled={resultTranslationsLoading}
                    onClick={() =>
                      resultTranslationsVisible
                        ? resultTranslations.showOriginal(resultTranslationIds)
                        : resultTranslations.translate(resultTranslationIds)
                    }
                  >
                    <Languages size={15} />
                    {resultTranslationsLoading
                      ? translationCopy.translating
                      : resultTranslationsVisible
                        ? translationCopy.showOriginal
                        : translationCopy.translate}
                  </button>
                )}
                {resultFiltersOpen && (
                  <div className="run-filters run-filter-popover result-filter-popover">
                    <div className="run-filter-popover__header">
                      <strong>{l.filter}</strong>
                      <button className="ghost" onClick={resetResultFilters}>
                        {l.reset}
                      </button>
                    </div>
                    <label>
                      {l.iteration}
                      <select
                        value={draftResultIterationFilter}
                        onChange={(event) =>
                          setDraftResultIterationFilter(
                            event.target.value as "all" | "latest" | "range",
                          )
                        }
                      >
                        <option value="all">{l.allIterations}</option>
                        <option value="latest">{l.latestIteration}</option>
                        <option value="range">{l.iterationRange}</option>
                      </select>
                    </label>
                    {draftResultIterationFilter === "range" && (
                      <div className="result-filter-range">
                        <label>
                          {l.from}
                          <input
                            type="number"
                            min="1"
                            value={draftResultIterationFrom}
                            onChange={(event) => setDraftResultIterationFrom(event.target.value)}
                          />
                        </label>
                        <label>
                          {l.to}
                          <input
                            type="number"
                            min="1"
                            value={draftResultIterationTo}
                            onChange={(event) => setDraftResultIterationTo(event.target.value)}
                          />
                        </label>
                      </div>
                    )}
                    <fieldset>
                      <legend>{l.decision}</legend>
                      <div className="run-filters__statuses">
                        {(["approved", "rejected", "pending", "no_response"] as const).map((decision) => (
                          <label key={decision}>
                            <input
                              type="checkbox"
                              checked={draftResultDecisions.has(decision)}
                              onChange={() => toggleResultDecision(decision)}
                            />
                            {decision === "no_response" ? l.noSupervisorResponse : decision === "approved" ? l.approve : decision === "rejected" ? l.reject : "Pending"}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <label>
                      {l.score}
                      <select
                        value={draftResultScoreBucket}
                        onChange={(event) => setDraftResultScoreBucket(event.target.value)}
                      >
                        <option value="all">{l.allScores}</option>
                        <option value="missing">{l.noScore}</option>
                        <option value="low">{l.scoreLow}</option>
                        <option value="medium">{l.scoreMedium}</option>
                        <option value="good">{l.scoreGood}</option>
                        <option value="excellent">{l.scoreExcellent}</option>
                      </select>
                    </label>
                    <label>
                      {l.resultContent}
                      <select
                        value={draftResultContent}
                        onChange={(event) =>
                          setDraftResultContent(
                            event.target.value as "all" | "improvements" | "issues" | "empty",
                          )
                        }
                      >
                        <option value="all">{l.allContent}</option>
                        <option value="improvements">{l.improvementsOnly}</option>
                        <option value="issues">{l.issuesOnly}</option>
                        <option value="empty">{l.noFindings}</option>
                      </select>
                    </label>
                    <label>
                      {l.attempt}
                      <select
                        value={draftResultAttemptFilter}
                        onChange={(event) => setDraftResultAttemptFilter(event.target.value)}
                      >
                        <option value="all">{l.allAttempts}</option>
                        <option value="attempted">{l.attempted}</option>
                        <option value="not_attempted">{l.notAttempted}</option>
                      </select>
                    </label>
                    <label>
                      {l.improvementStatus}
                      <select
                        value={draftResultImprovementStatus}
                        onChange={(event) => setDraftResultImprovementStatus(event.target.value)}
                      >
                        <option value="all">{l.allStatuses}</option>
                        {resultFilterOptions.improvementStatuses.map((status) => (
                          <option key={status} value={status}>{status}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {l.issueSeverity}
                      <select
                        value={draftResultIssueSeverity}
                        onChange={(event) => setDraftResultIssueSeverity(event.target.value)}
                      >
                        <option value="all">{l.allSeverities}</option>
                        {resultFilterOptions.issueSeverities.map((severity) => (
                          <option key={severity} value={severity}>{severity}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {l.issueStatus}
                      <select
                        value={draftResultIssueStatus}
                        onChange={(event) => setDraftResultIssueStatus(event.target.value)}
                      >
                        <option value="all">{l.allStatuses}</option>
                        {resultFilterOptions.issueStatuses.map((status) => (
                          <option key={status} value={status}>{status}</option>
                        ))}
                      </select>
                    </label>
                    <div className="run-filter-popover__footer">
                      <button className="ghost" onClick={() => setResultFiltersOpen(false)}>
                        {l.cancel}
                      </button>
                      <button className="approve" onClick={applyResultFilters}>
                        {l.apply}
                      </button>
                    </div>
                  </div>
                )}
              </div>
{/* Result presentation is isolated from the filter controls above. */}
              <EvaluationResultPanel
                error={resultTranslations.error && <small className="hint">{translationCopy.failed}</small>}
                records={resultRecords}
                summaries={resultBehaviorTraces}
                improvements={resultImprovements}
                issues={resultIssues}
                l={l}
                locale={locale}
              />
              </div>
            </RunDetailTabPanel>
          )}
        </Modal>
      )}
      <Modal open={Boolean(retryingRun)} title={retryCopy.title} onClose={() => setRetryingRun(null)} className="modal--confirm">
        <div className="modal-form retry-confirmation">
          <p className="confirm-description">{retryCopy.warning}</p>
          <div className="modal-actions">
            <button className="ghost" onClick={() => setRetryingRun(null)}>{retryCopy.cancel}</button>
            <button className="reject" onClick={() => { if (retryingRun) onRetry(retryingRun.id, false); setRetryingRun(null); }}>{retryCopy.resume}</button>
            <button className="approve" onClick={() => { if (retryingRun) onRetry(retryingRun.id, true); setRetryingRun(null); }}>{retryCopy.restart}</button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
