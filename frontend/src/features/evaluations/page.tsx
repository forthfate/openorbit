import { Check, ChevronLeft, ChevronRight, CircleStop, Info, ListFilter, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  Run,
  RunStepResult,
  RunTelemetry,
  SupervisorRecord,
  TelemetrySpan,
} from "../../domain/models";
import { DataTable, type Column } from "../../components/ui/data-table";
import { ConfirmDialog } from "../../components/ui/confirm-dialog";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { PageSizeSelect } from "../../components/ui/page-size-select";
import { StatusBadge } from "../../components/ui/status-badge";
import { Tooltip } from "../../components/ui/tooltip";
import { locales, type Locale } from "../../locales";
import { api } from "../../services/api";

const phases = [
  "init",
  "setup",
  "run",
  "eval",
  "teardown",
  "finalize",
] as const;
const dateLocale: Record<Locale, string> = {
  en: "en-US",
  ko: "ko-KR",
  ja: "ja-JP",
};
const time = (locale: Locale, value?: string) =>
  value
    ? new Intl.DateTimeFormat(dateLocale[locale], {
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
const copy = {
  en: {
    title: "Evaluation runs",
    evaluation: "Evaluation",
    iteration: "Iteration",
    detail: "Evaluation run detail",
    workflow: "Workflow logs",
    logs: "Logs",
    supervisor: "Supervisor AI",
    result: "Evaluation result",
    score: "Score",
    decision: "Evaluation decision",
    proposals: "Proposed improvements",
    issues: "Reported issues",
    status: "Run status",
    phase: "Current phase",
    approve: "Approve",
    reject: "Reject",
    supervisorPrompt: "Prompt sent to supervisor",
    supervisorResponse: "Supervisor response",
    supervisorWaiting: "The supervisor has not produced a response yet.",
    noSupervisorPrompt: "No supervisor prompt was recorded for this run.",
    noLogs: "No process output is available yet.",
    noResults: "No data recorded for this iteration.",
    complete: "Completed",
    cancelled: "Cancelled",
    failed: "Failed",
    waiting: "Waiting for next iteration",
  },
  ko: {
    title: "평가 실행 이력",
    evaluation: "평가",
    iteration: "반복",
    detail: "평가 실행 상세",
    workflow: "워크플로 로그",
    logs: "로그",
    supervisor: "감독관 AI",
    result: "평가 결과",
    score: "점수",
    decision: "평가 결정",
    proposals: "개선 제안",
    issues: "보고된 문제",
    status: "실행 상태",
    phase: "현재 단계",
    approve: "승인",
    reject: "거절",
    supervisorPrompt: "감독관에게 전달된 프롬프트",
    supervisorResponse: "감독관 응답",
    supervisorWaiting: "감독관 응답이 아직 생성되지 않았습니다.",
    noSupervisorPrompt: "이 실행에는 감독관 프롬프트가 기록되지 않았습니다.",
    noLogs: "아직 확인할 프로세스 출력이 없습니다.",
    noResults: "이 반복에 기록된 데이터가 없습니다.",
    complete: "완료",
    cancelled: "취소됨",
    failed: "실패",
    waiting: "다음 반복 대기",
  },
  ja: {
    title: "評価実行履歴",
    evaluation: "評価",
    iteration: "反復",
    detail: "評価実行の詳細",
    workflow: "ワークフローログ",
    logs: "ログ",
    supervisor: "監督AI",
    result: "評価結果",
    score: "スコア",
    decision: "評価判断",
    proposals: "改善提案",
    issues: "報告された問題",
    status: "実行状態",
    phase: "現在のフェーズ",
    approve: "承認",
    reject: "却下",
    supervisorPrompt: "監督AIに送信したプロンプト",
    supervisorResponse: "監督AIの応答",
    supervisorWaiting: "監督AIの応答はまだ生成されていません。",
    noSupervisorPrompt: "この実行には監督AIプロンプトが記録されていません。",
    noLogs: "プロセス出力はまだありません。",
    noResults: "この反復には記録済みのデータがありません。",
    complete: "完了",
    cancelled: "キャンセル済み",
    failed: "失敗",
    waiting: "次の反復を待機中",
  },
};
function BrowserEvidence({ result }: { result: Record<string, unknown> }) {
  const journey = result.browser_journey as
    | {
        base_url?: string;
        results?: {
          id?: string;
          name?: string;
          passed?: boolean;
          url?: string;
          expected_text?: string;
          screenshot?: string;
          error?: string;
        }[];
      }
    | undefined;
  if (!journey) return null;
  return (
    <div className="browser-evidence">
      <strong>Playwright browser journey</strong>
      <small>{journey.base_url}</small>
      {journey.results?.map((item) => (
        <div key={item.id}>
          <b
            className={
              item.passed ? "browser-evidence__pass" : "browser-evidence__fail"
            }
          >
            {item.passed ? "Passed" : "Failed"}
          </b>
          <span>
            {item.name ?? item.id} · {item.url}
          </span>
          {item.expected_text && <small>Expected: {item.expected_text}</small>}
          {item.screenshot && <small>Screenshot: {item.screenshot}</small>}
          {item.error && <pre>{item.error}</pre>}
        </div>
      ))}
    </div>
  );
}
function WorkflowLogOutput({
  steps,
  locale,
}: {
  steps: RunStepResult[];
  locale: Locale;
}) {
  return (
    <div className="console-output workflow-log-output">
      {steps.length ? (
        steps.map((step, index) => (
          <section key={`${step.step_id}-${index}`}>
            <div>
              <strong>{step.name ?? step.step_id}</strong>
              <small>
                {time(locale, step.ended_at)} · exit {step.exit_code ?? "—"}
              </small>
            </div>
            <code className="workflow-command">
              ${" "}
              {step.command?.join(" ") ??
                "Command metadata unavailable for this older run."}
            </code>
            {step.working_directory && (
              <small className="workflow-directory">
                {step.working_directory}
              </small>
            )}
            {step.result && <BrowserEvidence result={step.result} />}
            <pre>{step.output ?? step.error ?? "—"}</pre>
          </section>
        ))
      ) : (
        <p className="hint">No commands were executed for this phase.</p>
      )}
    </div>
  );
}
function IterationLogOutput({
  steps,
}: {
  steps: RunStepResult[];
}) {
  const output = steps
    .map((step) => step.output ?? step.error ?? "")
    .filter(Boolean)
    .join("\n");
  return (
    <div className="console-output iteration-log-output">
      {output ? (
        <pre>{output}</pre>
      ) : (
        <p className="hint">No logs were emitted for this iteration.</p>
      )}
    </div>
  );
}
function ResultList({
  items,
  kind,
  locale,
  empty,
}: {
  items: Record<string, unknown>[];
  kind: "improvement" | "issue";
  locale: Locale;
  empty: string;
}) {
  return (
    <div className="result-items">
      {items.length ? (
        items.map((item, index) => {
          const status = String(item.status ?? "—"),
            severity = String(item.severity ?? "—"),
            reportedAt =
              typeof item.reported_at === "string"
                ? item.reported_at
                : undefined;
          return (
            <article className="result-row" key={index}>
              <time className="result-row__time">
                {time(locale, reportedAt)}
              </time>
              <div className="result-row__body">
                <strong>{String(item.title ?? "—")}</strong>
                <p>
                  {String(
                    kind === "improvement"
                      ? (item.rationale ?? "—")
                      : (item.evidence ?? "—"),
                  )}
                </p>
              </div>
              <div className="result-row__metrics">
                {kind === "improvement" ? (
                  <>
                    <span>
                      <small>Status</small>
                      <b className={`decision decision--${status}`}>{status}</b>
                    </span>
                    <span>
                      <small>Score</small>
                      <b>{String(item.effect_score ?? item.score ?? "—")}</b>
                    </span>
                    <span>
                      <small>Attempted</small>
                      <b>
                        {item.attempted === true || status === "adopted"
                          ? "Yes"
                          : "No"}
                      </b>
                    </span>
                  </>
                ) : (
                  <>
                    <span>
                      <small>Severity</small>
                      <b className={`decision decision--${severity}`}>
                        {severity}
                      </b>
                    </span>
                    <span>
                      <small>Status</small>
                      <b className={`decision decision--${status}`}>{status}</b>
                    </span>
                  </>
                )}
              </div>
            </article>
          );
        })
      ) : (
        <p className="hint result-empty">{empty}</p>
      )}
    </div>
  );
}
function TelemetryTree({ telemetry }: { telemetry: RunTelemetry | undefined }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set()),
    tree = useMemo(() => {
      const spans = telemetry?.spans ?? [],
        children = new Map<string, TelemetrySpan[]>(),
        known = new Set(spans.map((span) => span.spanId));
      for (const span of spans) {
        if (span.parentSpanId && known.has(span.parentSpanId))
          children.set(span.parentSpanId, [
            ...(children.get(span.parentSpanId) ?? []),
            span,
          ]);
      }
      return {
        roots: spans.filter(
          (span) => !span.parentSpanId || !known.has(span.parentSpanId),
        ),
        children,
      };
    }, [telemetry]);
  if (!telemetry) return <p className="hint">Loading OpenTelemetry trace…</p>;
  if (!tree.roots.length)
    return (
      <p className="hint">No exported OpenTelemetry spans are available yet.</p>
    );
  const render = (span: TelemetrySpan): React.ReactNode => {
    const children = tree.children.get(span.spanId) ?? [],
      expandable = children.length > 0,
      isCollapsed = collapsed.has(span.spanId);
    return (
      <li key={span.spanId}>
        <button
          type="button"
          className="trace-node"
          disabled={!expandable}
          onClick={() => {
            if (!expandable) return;
            setCollapsed((current) => {
              const next = new Set(current);
              if (isCollapsed) next.delete(span.spanId);
              else next.add(span.spanId);
              return next;
            });
          }}
        >
          <span
            className={`trace-status trace-status--${span.status === "ERROR" ? "error" : "ok"}`}
          />
          <div>
            <strong>
              {expandable
                ? `${isCollapsed ? "▸" : "▾"} ${span.name}`
                : span.name}
            </strong>
            <small>
              {span.events?.map((event) => event.name).join(" · ") ||
                span.status ||
                "UNSET"}
            </small>
          </div>
        </button>
        {expandable && !isCollapsed && <ul>{children.map(render)}</ul>}
      </li>
    );
  };
  return <ul className="telemetry-tree">{tree.roots.map(render)}</ul>;
}
function SupervisorOutput({
  record,
  l,
  telemetry,
  iteration,
}: {
  record?: SupervisorRecord;
  l: (typeof copy)["en"];
  telemetry: RunTelemetry | undefined;
  iteration: number;
}) {
  const response = record?.response;
  const iterationTelemetry = telemetry
    ? {
        ...telemetry,
        spans: telemetry.spans.filter(
          (span) =>
            span.name === "supervisor.evaluate" &&
            Number(span.attributes?.["orbit.iteration"]) === iteration,
        ),
      }
    : undefined;
  return (
    <div className="supervisor-output">
      <section>
        <div className="supervisor-output__head">
          <strong>{l.supervisorPrompt}</strong>
          <StatusBadge
            value={record?.status ?? "pending"}
            label={record?.status ?? "pending"}
          />
        </div>
        <pre>{record?.prompt || l.noSupervisorPrompt}</pre>
      </section>
      <section>
        <strong>{l.supervisorResponse}</strong>
        {response ? (
          <pre>{JSON.stringify(response, null, 2)}</pre>
        ) : (
          <p>{record?.error || l.supervisorWaiting}</p>
        )}
      </section>
      <section>
        <strong>OpenTelemetry trace</strong>
        <TelemetryTree telemetry={iterationTelemetry} />
      </section>
    </div>
  );
}

export function EvaluationsPage({
  runs,
  onStop,
  onApprove,
  onReject,
  onEmergencyStop,
  onDeleteRuns,
  locale,
}: {
  runs: Run[];
  onStop: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEmergencyStop: () => void;
  onDeleteRuns: (ids: string[]) => Promise<unknown>;
  locale: Locale;
}) {
  const t = locales[locale].common,
    l = copy[locale];
  const [selected, setSelected] = useState<Run | null>(null),
    [tab, setTab] = useState<"workflow" | "logs" | "supervisor" | "result">(
      "workflow",
    ),
    [phaseTab, setPhaseTab] = useState<(typeof phases)[number]>("init"),
    [iterationTab, setIterationTab] = useState(1),
    [telemetry, setTelemetry] = useState<RunTelemetry>(),
    [statuses, setStatuses] = useState<Set<string>>(() => new Set(runStatuses)),
    [buildFilter, setBuildFilter] = useState(""),
    [modeFilter, setModeFilter] = useState<"all" | "run" | "test">("all"),
    [phaseFilter, setPhaseFilter] = useState(""),
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
    [draftActiveOnly, setDraftActiveOnly] = useState(false);
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set()),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(15),
    [deleteSelectionOpen, setDeleteSelectionOpen] = useState(false);
  const filterMenu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected)
      api<RunTelemetry>(`/api/runs/${selected.id}/telemetry`)
        .then(setTelemetry)
        .catch(() => setTelemetry({ spans: [] }));
  }, [selected]);
  const label = (status: string) =>
    ({
      queued: locale === "ko" ? "대기 중" : "Queued",
      awaiting_approval: locale === "ko" ? "승인 대기" : "Awaiting approval",
      running: locale === "ko" ? "실행 중" : "Running",
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
          run.evaluation_build_id ?? run.workflow_id,
          {
            id: run.evaluation_build_id ?? run.workflow_id,
            name:
              run.evaluation_build_name ??
              run.evaluation_build_id ??
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
        (run.evaluation_build_id ?? run.workflow_id) === buildFilter) &&
      (modeFilter === "all" || run.execution_mode === modeFilter) &&
      (!phaseFilter || run.current_phase === phaseFilter) &&
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
    setDraftActiveOnly(false);
  };
  const closeFilters = () => setFiltersOpen(false);
  const openFilters = () => {
    setDraftStatuses(new Set(statuses));
    setDraftBuildFilter(buildFilter);
    setDraftModeFilter(modeFilter);
    setDraftPhaseFilter(phaseFilter);
    setDraftActiveOnly(activeOnly);
    setFiltersOpen(true);
  };
  const applyFilters = () => {
    setStatuses(new Set(draftStatuses));
    setBuildFilter(draftBuildFilter);
    setModeFilter(draftModeFilter);
    setPhaseFilter(draftPhaseFilter);
    setActiveOnly(draftActiveOnly);
    setPage(1);
    closeFilters();
  };
  const appliedFilterCount =
    Number(statuses.size !== runStatuses.length) +
    Number(Boolean(buildFilter)) +
    Number(modeFilter !== "all") +
    Number(Boolean(phaseFilter)) +
    Number(activeOnly);
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
  const columns: Column<Run>[] = [
    {id:"select",header:<input aria-label="Select all runs on this page" type="checkbox" checked={allPageSelected} disabled={!selectableRuns.length} onChange={togglePage}/>,render:r=><input aria-label={`Select run ${r.id}`} type="checkbox" checked={selectedRunIds.has(r.id)} disabled={!terminal(r.status)} onChange={()=>toggleRun(r.id)}/>},
    {
      id: "build",
      header: t.evaluationBuild,
      render: (r) => (
        <span className="run-build">
          <strong>{r.evaluation_build_name ?? r.evaluation_build_id}</strong>
          <small>{r.workflow_name}</small>
        </span>
      ),
    },
    {
      id: "started",
      header: t.started,
      render: (r) => time(locale, r.created_at),
    },
    {
      id: "elapsed",
      header: t.elapsed,
      render: (r) =>
        elapsed(
          r.created_at,
          terminal(r.status) ? (r.finished_at ?? r.updated_at) : undefined,
        ),
    },
    { id: "phase", header: t.phase, render: finalPhase },
    { id: "pid", header: t.pid, render: (r) => r.pid ?? r.last_pid ?? "—" },
    {
      id: "proposed",
      header: t.proposed,
      render: (r) => r.proposed_improvements ?? 0,
    },
    {
      id: "approved",
      header: t.approved,
      render: (r) => r.approved_improvements ?? 0,
    },
    { id: "issues", header: t.issues, render: (r) => r.reported_issues ?? 0 },
    {
      id: "status",
      header: t.status,
      render: (r) => <StatusBadge value={r.status} label={label(r.status)} />,
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
  columns[1].header = l.evaluation;
  columns.splice(4, 0, {
    id: "iteration",
    header: l.iteration,
    render: (r) =>
      Math.max(
        0,
        ...(r.step_results ?? []).map((step) => step.loop_index ?? 0),
      ) || "—",
  });
  const steps = selected?.step_results ?? [],
    iterations = [
      ...new Set(
        steps.map((step) => step.loop_index ?? 0).filter((index) => index > 0),
      ),
    ].sort((a, b) => a - b),
    selectedSteps = steps.filter((step) => step.loop_index === iterationTab),
    supervision = selected?.supervisor_results?.find(
      (item) => item.iteration === iterationTab,
    ),
    result = supervision?.response,
    evaluation = result?.evaluation;
  const iterationPosition = iterations.indexOf(iterationTab),
    previousIteration = iterations[iterationPosition - 1],
    nextIteration = iterations[iterationPosition + 1];
  return (
    <section className="panel active-evaluation-panel">
      <PanelHeader
        title={
          <Tooltip content={t.runHistoryHint}>
            <span className="panel-title-with-tooltip">
              {l.title}
              <Info size={15} />
            </span>
          </Tooltip>
        }
        action={
          <button className="emergency" onClick={onEmergencyStop}>
            <CircleStop size={15} />
            {t.emergencyStop}
          </button>
        }
      />
      <div className="run-filter-trigger" ref={filterMenu}>
        <button
          className="ghost run-filter-button"
          aria-expanded={filtersOpen}
          onClick={() => (filtersOpen ? closeFilters() : openFilters())}
        >
          <ListFilter size={15} />
          {locale === "ko" ? "필터" : locale === "ja" ? "フィルター" : "Filter"}
          {appliedFilterCount > 0 && <span>{appliedFilterCount}</span>}
        </button>
        <PageSizeSelect locale={locale} value={pageSize} onChange={value=>{setPageSize(value);setPage(1)}}/>
        {filtersOpen && (
          <div className="run-filters run-filter-popover">
            <div className="run-filter-popover__header">
              <strong>{locale === "ko" ? "필터" : locale === "ja" ? "フィルター" : "Filter"}</strong>
              <button className="ghost" onClick={resetFilters}>
                {locale === "ko" ? "초기화" : locale === "ja" ? "リセット" : "Reset"}
              </button>
            </div>
            <fieldset>
              <legend>
                {locale === "ko"
                  ? "상태"
                  : locale === "ja"
                    ? "ステータス"
                    : "Status"}
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
              {locale === "ko"
                ? "평가 빌드"
                : locale === "ja"
                  ? "評価ビルド"
                  : "Evaluation build"}
              <select
                value={draftBuildFilter}
                onChange={(event) => setDraftBuildFilter(event.target.value)}
              >
                <option value="">
                  {locale === "ko"
                    ? "전체 빌드"
                    : locale === "ja"
                      ? "すべてのビルド"
                      : "All builds"}
                </option>
                {builds.map((build) => (
                  <option key={build.id} value={build.id}>
                    {build.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {locale === "ko"
                ? "실행 유형"
                : locale === "ja"
                  ? "実行タイプ"
                  : "Run type"}
              <select
                value={draftModeFilter}
                onChange={(event) =>
                  setDraftModeFilter(event.target.value as "all" | "run" | "test")
                }
              >
                <option value="all">
                  {locale === "ko"
                    ? "전체"
                    : locale === "ja"
                      ? "すべて"
                      : "All"}
                </option>
                <option value="run">Run</option>
                <option value="test">Test</option>
              </select>
            </label>
            <label>
              {locale === "ko" ? "단계" : locale === "ja" ? "フェーズ" : "Phase"}
              <select
                value={draftPhaseFilter}
                onChange={(event) => setDraftPhaseFilter(event.target.value)}
              >
                <option value="">
                  {locale === "ko" ? "전체 단계" : locale === "ja" ? "すべてのフェーズ" : "All phases"}
                </option>
                {phases.map((phase) => (
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
              {locale === "ko"
                ? "활성 실행만"
                : locale === "ja"
                  ? "実行中のみ"
                  : "Active only"}
            </label>
            <div className="run-filter-popover__footer">
              <button className="ghost" onClick={closeFilters}>
                {locale === "ko" ? "취소" : locale === "ja" ? "キャンセル" : "Cancel"}
              </button>
              <button className="approve" onClick={applyFilters}>
                {locale === "ko" ? "적용" : locale === "ja" ? "適用" : "Apply"}
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="run-history-actions">
        <span>{selectedRunIds.size} {locale === "ko" ? "개 선택됨" : locale === "ja" ? "件選択" : "selected"}</span>
        <button className="ghost" onClick={() => setSelectedRunIds(new Set())} disabled={!selectedRunIds.size}>{locale === "ko" ? "선택 해제" : locale === "ja" ? "選択解除" : "Deselect"}</button>
        <button className="icon-button danger" aria-label={locale === "ko" ? "선택 삭제" : "Delete selected"} title={locale === "ko" ? "선택 삭제" : "Delete selected"} onClick={deleteSelected} disabled={!selectedRunIds.size}><Trash2 size={15}/></button>
      </div>
      <DataTable
        columns={columns}
        rows={pagedRuns}
        onRowClick={(r) => {
          const latest = Math.max(
            1,
            ...(r.step_results ?? []).map((step) => step.loop_index ?? 0),
          );
          setSelected(r);
          setTab("logs");
          setPhaseTab("init");
          setIterationTab(latest);
        }}
        className="active-evaluation-table"
        gridTemplateColumns="36px minmax(220px,2fr) minmax(145px,1fr) 82px 90px 72px 96px 96px 82px 94px 72px 72px"
        empty={t.noRuns}
      />
      <div className="run-pagination"><span>{filteredRuns.length ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filteredRuns.length)} / ${filteredRuns.length}` : "0"}</span><div><button className="ghost" disabled={currentPage===1} onClick={()=>setPage(currentPage-1)}>{locale === "ko" ? "이전" : locale === "ja" ? "前へ" : "Previous"}</button><span>{currentPage} / {totalPages}</span><button className="ghost" disabled={currentPage===totalPages} onClick={()=>setPage(currentPage+1)}>{locale === "ko" ? "다음" : locale === "ja" ? "次へ" : "Next"}</button></div></div>
      <ConfirmDialog open={deleteSelectionOpen} title={locale === "ko" ? "선택한 실행을 삭제할까요?" : locale === "ja" ? "選択した実行を削除しますか？" : "Delete selected runs?"} description={locale === "ko" ? `${selectedRunIds.size}개의 완료된 실행 이력이 삭제됩니다. 이 작업은 되돌릴 수 없습니다.` : locale === "ja" ? `${selectedRunIds.size}件の完了した実行履歴を削除します。この操作は元に戻せません。` : `${selectedRunIds.size} completed run records will be deleted. This cannot be undone.`} cancelLabel={locale === "ko" ? "취소" : locale === "ja" ? "キャンセル" : "Cancel"} confirmLabel={locale === "ko" ? "삭제" : locale === "ja" ? "削除" : "Delete"} onCancel={()=>setDeleteSelectionOpen(false)} onConfirm={confirmDeleteSelected}/>
      {selected && (
        <Modal
          open
          title={l.detail}
          onClose={() => setSelected(null)}
          className="modal--run-detail"
        >
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
          <div className="run-tabs">
            <button
              className={tab === "workflow" ? "active" : ""}
              onClick={() => setTab("workflow")}
            >
              {l.workflow}
            </button>
            <button
              className={tab === "logs" ? "active" : ""}
              onClick={() => setTab("logs")}
            >
              {l.logs}
            </button>
            <button
              className={tab === "supervisor" ? "active" : ""}
              onClick={() => setTab("supervisor")}
            >
              {l.supervisor}
            </button>
            <button
              className={tab === "result" ? "active" : ""}
              onClick={() => setTab("result")}
            >
              {l.result}
            </button>
          </div>
          {iterations.length > 0 && (
            <div className="iteration-navigator" aria-label={l.iteration}>
              <button
                className="ghost icon-button"
                type="button"
                aria-label={locale === "ko" ? "이전 반복" : locale === "ja" ? "前の反復" : "Previous iteration"}
                title={locale === "ko" ? "이전 반복" : locale === "ja" ? "前の反復" : "Previous iteration"}
                disabled={previousIteration === undefined}
                onClick={() => {
                  if (previousIteration !== undefined) setIterationTab(previousIteration);
                }}
              >
                <ChevronLeft size={16} />
              </button>
              <select
                aria-label={l.iteration}
                value={iterationTab}
                onChange={(event) => setIterationTab(Number(event.target.value))}
              >
                {[...iterations].reverse().map((iteration) => (
                  <option key={iteration} value={iteration}>#{iteration}</option>
                ))}
              </select>
              <button
                className="ghost icon-button"
                type="button"
                aria-label={locale === "ko" ? "다음 반복" : locale === "ja" ? "次の反復" : "Next iteration"}
                title={locale === "ko" ? "다음 반복" : locale === "ja" ? "次の反復" : "Next iteration"}
                disabled={nextIteration === undefined}
                onClick={() => {
                  if (nextIteration !== undefined) setIterationTab(nextIteration);
                }}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
          {tab === "workflow" && (
            <>
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
              <WorkflowLogOutput
                locale={locale}
                steps={selectedSteps.filter(
                  (step) => (step.phase ?? step.step_id) === phaseTab,
                )}
              />
            </>
          )}
          {tab === "logs" && (
            <IterationLogOutput steps={selectedSteps} />
          )}{" "}
          {tab === "supervisor" && (
            <SupervisorOutput
              record={supervision}
              l={l}
              telemetry={telemetry}
              iteration={iterationTab}
            />
          )}{" "}
          {tab === "result" && (
            <div className="run-result">
              <section>
                <h3>{l.proposals}</h3>
                <ResultList
                  locale={locale}
                  kind="improvement"
                  items={result?.improvements ?? []}
                  empty={supervision ? l.noResults : l.supervisorWaiting}
                />
              </section>
              <section>
                <h3>{l.issues}</h3>
                <ResultList
                  locale={locale}
                  kind="issue"
                  items={result?.reported_issues ?? []}
                  empty={supervision ? l.noResults : l.supervisorWaiting}
                />
              </section>
            </div>
          )}
        </Modal>
      )}
    </section>
  );
}
