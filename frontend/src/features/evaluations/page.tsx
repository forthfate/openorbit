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
    noCommandsForPhase: "No commands were executed for this phase.",
    openTelemetryTrace: "OpenTelemetry trace",
    loadingOpenTelemetryTrace: "Loading OpenTelemetry trace…",
    noOpenTelemetrySpans: "No exported OpenTelemetry spans are available yet.",
    complete: "Completed",
    cancelled: "Cancelled",
    failed: "Failed",
    waiting: "Waiting for next iteration",
    filter: "Filter",
    reset: "Reset",
    apply: "Apply",
    cancel: "Cancel",
    allIterations: "All iterations",
    latestIteration: "Latest iteration",
    iterationRange: "Iteration range",
    from: "From",
    to: "To",
    noSupervisorResponse: "No supervisor response",
    allDecisions: "All decisions",
    allScores: "All scores",
    noScore: "No score",
    scoreLow: "0–3",
    scoreMedium: "4–6",
    scoreGood: "7–8",
    scoreExcellent: "9–10",
    resultContent: "Result content",
    allContent: "All content",
    improvementsOnly: "Improvements present",
    issuesOnly: "Issues present",
    noFindings: "No findings",
    noMatchingResults: "No evaluation results match these filters.",
    attempt: "Attempt",
    allAttempts: "All attempts",
    attempted: "Attempted",
    notAttempted: "Not attempted",
    improvementStatus: "Improvement status",
    issueSeverity: "Issue severity",
    issueStatus: "Issue status",
    allStatuses: "All statuses",
    allSeverities: "All severities",
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
    noCommandsForPhase: "이 단계에서 실행된 명령이 없습니다.",
    openTelemetryTrace: "OpenTelemetry 추적",
    loadingOpenTelemetryTrace: "OpenTelemetry 추적을 불러오는 중…",
    noOpenTelemetrySpans: "아직 내보낸 OpenTelemetry 스팬이 없습니다.",
    complete: "완료",
    cancelled: "취소됨",
    failed: "실패",
    waiting: "다음 반복 대기",
    filter: "필터",
    reset: "초기화",
    apply: "적용",
    cancel: "취소",
    allIterations: "전체 반복",
    latestIteration: "최신 반복",
    iterationRange: "반복 범위",
    from: "시작",
    to: "끝",
    noSupervisorResponse: "감독관 응답 없음",
    allDecisions: "전체 결정",
    allScores: "전체 점수",
    noScore: "점수 없음",
    scoreLow: "0–3점",
    scoreMedium: "4–6점",
    scoreGood: "7–8점",
    scoreExcellent: "9–10점",
    resultContent: "결과 내용",
    allContent: "전체 내용",
    improvementsOnly: "개선 제안 있음",
    issuesOnly: "문제 보고 있음",
    noFindings: "결과 없음",
    noMatchingResults: "필터와 일치하는 평가 결과가 없습니다.",
    attempt: "시도 여부",
    allAttempts: "전체",
    attempted: "시도함",
    notAttempted: "시도하지 않음",
    improvementStatus: "개선 제안 상태",
    issueSeverity: "문제 심각도",
    issueStatus: "문제 상태",
    allStatuses: "전체 상태",
    allSeverities: "전체 심각도",
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
    noCommandsForPhase: "このフェーズで実行されたコマンドはありません。",
    openTelemetryTrace: "OpenTelemetry トレース",
    loadingOpenTelemetryTrace: "OpenTelemetry トレースを読み込み中…",
    noOpenTelemetrySpans: "エクスポートされた OpenTelemetry スパンはまだありません。",
    complete: "完了",
    cancelled: "キャンセル済み",
    failed: "失敗",
    waiting: "次の反復を待機中",
    filter: "フィルター",
    reset: "リセット",
    apply: "適用",
    cancel: "キャンセル",
    allIterations: "すべての反復",
    latestIteration: "最新の反復",
    iterationRange: "反復の範囲",
    from: "開始",
    to: "終了",
    noSupervisorResponse: "監督AIの応答なし",
    allDecisions: "すべての判断",
    allScores: "すべてのスコア",
    noScore: "スコアなし",
    scoreLow: "0～3",
    scoreMedium: "4～6",
    scoreGood: "7～8",
    scoreExcellent: "9～10",
    resultContent: "結果の内容",
    allContent: "すべての内容",
    improvementsOnly: "改善提案あり",
    issuesOnly: "問題報告あり",
    noFindings: "結果なし",
    noMatchingResults: "フィルターに一致する評価結果はありません。",
    attempt: "試行",
    allAttempts: "すべて",
    attempted: "試行済み",
    notAttempted: "未試行",
    improvementStatus: "改善提案の状態",
    issueSeverity: "問題の重要度",
    issueStatus: "問題の状態",
    allStatuses: "すべての状態",
    allSeverities: "すべての重要度",
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
function WorkflowLogOutput({
  steps,
  locale,
}: {
  steps: RunStepResult[];
  locale: Locale;
}) {
  const l = copy[locale];
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
            <LineNumberedOutput value={step.output ?? step.error ?? "—"} />
          </section>
        ))
      ) : (
        <p className="hint">{l.noCommandsForPhase}</p>
      )}
    </div>
  );
}
function IterationLogOutput({
  steps,
  locale,
}: {
  steps: RunStepResult[];
  locale: Locale;
}) {
  const logSteps = steps.filter((step) => step.output || step.error);
  return (
    <div className="console-output iteration-log-output">
      {logSteps.length ? (
        logSteps.map((step, index) => (
          <section key={`${step.step_id}-${index}`}>
            <div>
              <strong>{step.name ?? step.step_id}</strong>
              <small>{time(locale, step.ended_at ?? step.started_at)}</small>
            </div>
            <LineNumberedOutput value={step.output ?? step.error ?? "—"} />
          </section>
        ))
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
  showIteration = false,
}: {
  items: Record<string, unknown>[];
  kind: "improvement" | "issue";
  locale: Locale;
  empty: string;
  showIteration?: boolean;
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
                {showIteration && typeof item.__iteration === "number" && (
                  <span>
                    <small>Iteration</small>
                    <b>#{item.__iteration}</b>
                  </span>
                )}
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
function TelemetryTree({
  telemetry,
  l,
}: {
  telemetry: RunTelemetry | undefined;
  l: (typeof copy)["en"];
}) {
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
  if (!telemetry)
    return <p className="hint">{l.loadingOpenTelemetryTrace}</p>;
  if (!tree.roots.length)
    return <p className="hint">{l.noOpenTelemetrySpans}</p>;
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
        <LineNumberedOutput value={record?.prompt || l.noSupervisorPrompt} />
      </section>
      <section>
        <strong>{l.supervisorResponse}</strong>
        {response ? (
          <LineNumberedOutput value={JSON.stringify(response, null, 2)} />
        ) : (
          <p>{record?.error || l.supervisorWaiting}</p>
        )}
      </section>
      <section>
        <strong>{l.openTelemetryTrace}</strong>
        <TelemetryTree telemetry={iterationTelemetry} l={l} />
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
  initialSelectedRun,
  onSelectedRunClose,
}: {
  runs: Run[];
  onStop: (id: string) => void;
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
    [tab, setTab] = useState<"workflow" | "logs" | "supervisor" | "result">(
      "result",
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
    [deleteSelectionOpen, setDeleteSelectionOpen] = useState(false);
  const selected = initialSelectedRun ?? selectedInternal;
  const filterMenu = useRef<HTMLDivElement>(null),
    resultFilterMenu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected)
      api<RunTelemetry>(`/api/runs/${selected.id}/telemetry`)
        .then(setTelemetry)
        .catch(() => setTelemetry({ spans: [] }));
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
    // `finalize` is bookkeeping after the last evaluation loop.  It must not
    // become the default detail iteration because supervisor results belong to
    // the actual run/eval loop.
    iterations = [
      ...new Set([
        ...steps
          .filter((step) => ["run", "eval"].includes(step.phase ?? step.step_id ?? ""))
          .map((step) => step.loop_index ?? 0)
          .filter((index) => index > 0),
        ...(selected?.supervisor_results ?? []).map((item) => item.iteration ?? 0).filter((index) => index > 0),
      ]),
    ].sort((a, b) => a - b),
    // `init` and `finalize` are process-level steps, not evaluation iterations.
    // Include them beside the relevant iteration so their evidence remains
    // visible without inventing a separate, misleading iteration.
    selectedSteps = steps.filter(
      (step) =>
        step.loop_index === iterationTab ||
        ((step.phase ?? step.step_id) === "init" && iterationTab === iterations[0]) ||
        ((step.phase ?? step.step_id) === "finalize" && iterationTab === iterations.at(-1)),
    ),
    availablePhases = phases.filter((phase) =>
      selectedSteps.some((step) => (step.phase ?? step.step_id) === phase),
    ),
    supervision = selected?.supervisor_results?.find(
      (item) => item.iteration === iterationTab,
    ),
    result = supervision?.response,
    evaluation = result?.evaluation;
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
      const response = record.response,
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
  const resultImprovements = resultRecords.flatMap((record) =>
      (record.response?.improvements ?? []).map((item) => ({
        ...item,
        __iteration: record.iteration,
      })),
    ),
    resultIssues = resultRecords.flatMap((record) =>
      (record.response?.reported_issues ?? []).map((item) => ({
        ...item,
        __iteration: record.iteration,
      })),
    );
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
          {ui.filter}
          {appliedFilterCount > 0 && <span>{appliedFilterCount}</span>}
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
              {ui.evaluationBuild}
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
              .filter((step) => ["run", "eval"].includes(step.phase ?? step.step_id ?? ""))
              .map((step) => step.loop_index ?? 0),
            ...(r.supervisor_results ?? []).map((item) => item.iteration ?? 0),
          );
          setSelected(r);
          setTab("result");
          setPhaseTab("init");
          setIterationTab(latest);
        }}
        className="active-evaluation-table"
        gridTemplateColumns="36px minmax(220px,2fr) minmax(145px,1fr) 82px 90px 72px 96px 96px 82px 94px 72px 72px"
        empty={t.noRuns}
      />
      <div className="run-pagination"><span>{filteredRuns.length ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filteredRuns.length)} / ${filteredRuns.length}` : "0"}</span><div><button className="ghost" disabled={currentPage===1} onClick={()=>setPage(currentPage-1)}>{locales[locale].ui.previous}</button><span>{currentPage} / {totalPages}</span><button className="ghost" disabled={currentPage===totalPages} onClick={()=>setPage(currentPage+1)}>{locales[locale].ui.next}</button></div></div>
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
              className={tab === "result" ? "active" : ""}
              onClick={() => setTab("result")}
            >
              {l.result}
            </button>
            <button
              className={tab === "supervisor" ? "active" : ""}
              onClick={() => setTab("supervisor")}
            >
              {l.supervisor}
            </button>
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
          </div>
          {tab !== "result" && iterations.length > 0 && (
            <div className="iteration-navigator" aria-label={l.iteration}>
              <button
                className="ghost icon-button"
                type="button"
                aria-label={ui.previousIteration}
                title={ui.previousIteration}
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
                aria-label={ui.nextIteration}
                title={ui.nextIteration}
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
            <IterationLogOutput locale={locale} steps={selectedSteps} />
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
                </button>
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
              {resultRecords.length ? (
                <>
                  <section>
                    <h3>{l.proposals}</h3>
                    <ResultList
                      locale={locale}
                      kind="improvement"
                      items={resultImprovements}
                      empty={l.noResults}
                      showIteration
                    />
                  </section>
                  <section>
                    <h3>{l.issues}</h3>
                    <ResultList
                      locale={locale}
                      kind="issue"
                      items={resultIssues}
                      empty={l.noResults}
                      showIteration
                    />
                  </section>
                </>
              ) : (
                <p className="hint result-empty">{l.noMatchingResults}</p>
              )}
            </div>
          )}
        </Modal>
      )}
    </section>
  );
}
