import {
  Bot,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileUp,
  Languages,
  Play,
  Plus,
  Sparkles,
  Star,
  TestTube2,
  Trash2,
  Wrench,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { WorkflowGraph } from "../../components/workflow-graph";
import { DataTable, type Column } from "../../components/ui/data-table";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { PageSizeSelect } from "../../components/ui/page-size-select";
import { Pagination } from "../../components/ui/pagination";
import { SectionInfo } from "../../components/ui/section-info";
import type {
  Build,
  ExecutionEnvironment,
  PromptTemplate,
  QuickStart,
  Run,
  RunnerAsset,
  Settings,
  TargetEnvironment,
  TargetTestCaseSet,
  WorkflowGraphDefinition,
} from "../../domain/models";
import {
  intlLocales,
  localeMessages,
  locales,
  type Locale,
} from "../../locales";
import { api, upload } from "../../services/api";
import { useTemplateTranslations } from "../../services/use-template-translation";
import { EvaluationsPage } from "../evaluations/page";

type Draft = {
  id: string;
  name: string;
  runner_id: string;
  runner_version: number | null;
  execution_environment_id: string;
  target_environment_id: string;
  purpose: string;
  manager_template_id: string;
  model_profile_name: string;
  test_case_set_id: string;
  timezone: string;
  repeat_interval_minutes: number;
  run_limit: number;
  cadence_mode: "after_completion" | "fixed";
  overrun_policy: "wait" | "interrupt_eval";
  schedule_enabled: boolean;
  schedule_weekdays: number[];
  schedule_start_time: string;
  schedule_end_time: string;
  iteration_strategy: "linear" | "score_select";
  candidates_per_iteration: number;
  approval_score: number;
  require_human_approval_before_apply: boolean;
  enabled: boolean;
};

type QuickStartTranslation = {
  name: string;
  description: string;
  parameters?: {
    label: string;
    description?: string;
    tooltip?: string;
    placeholder?: string;
    options?: { label: string }[];
  }[];
};
type LabelCopy = { label: string; hint: string };
export type ProfileFormCopy = {
  profileName: LabelCopy;
  provider: LabelCopy;
  modelDeployment: LabelCopy;
  azureEndpoint: LabelCopy;
  region: LabelCopy;
  awsProfile: LabelCopy;
  secretEnv: LabelCopy;
  createNewAiProfile: LabelCopy;
};
type BuildWizardCopy = {
  basics: string;
  evaluationSetup: string;
  schedule: string;
  decisionPolicy: string;
  buildId: LabelCopy;
  buildName: LabelCopy;
  runner: LabelCopy;
  runnerVersion: LabelCopy & { latest: string };
  targetEnvironment: LabelCopy;
  executionEnvironment: LabelCopy;
  purpose: LabelCopy;
  managerTemplate: LabelCopy;
  testCaseSet: LabelCopy;
  aiProfile: LabelCopy;
  timezone: LabelCopy;
  repeatInterval: LabelCopy;
  iterationTiming: LabelCopy;
  overrunPolicy: LabelCopy;
  iterationTimingAfterCompletion: string;
  iterationTimingFixed: string;
  iterationTimingWait: string;
  iterationTimingInterrupt: string;
  runLimit: LabelCopy;
  iterationStrategy: LabelCopy;
  iterationStrategyLinear: string;
  iterationStrategyScoreSelect: string;
  candidatesPerIteration: LabelCopy;
  approvalScore: LabelCopy;
  humanApproval: LabelCopy;
  humanApprovalEnable: string;
  name: string;
  next: string;
};

const withQuickStartTranslation = (
  item: QuickStart,
  translation: QuickStartTranslation | null,
  labels?: { name: string; description: string },
): QuickStart =>
  translation || labels
    ? {
        ...item,
        name: translation?.name ?? labels?.name ?? item.name,
        description:
          translation?.description ?? labels?.description ?? item.description,
        parameters: item.parameters.map((parameter, index) => ({
          ...parameter,
          ...translation?.parameters?.[index],
          options: parameter.options?.map((option, optionIndex) => ({
            ...option,
            ...translation?.parameters?.[index]?.options?.[optionIndex],
          })),
        })),
      }
    : item;
const formatDate = (locale: Locale, value?: string) =>
  value
    ? new Intl.DateTimeFormat(intlLocales[locale], {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—";
const empty: Draft = {
  id: "",
  name: "",
  runner_id: "",
  runner_version: null,
  execution_environment_id: "",
  target_environment_id: "",
  purpose: "",
  manager_template_id: "",
  model_profile_name: "",
  test_case_set_id: "",
  timezone: "Asia/Tokyo",
  repeat_interval_minutes: 30,
  run_limit: 1,
  cadence_mode: "after_completion",
  overrun_policy: "wait",
  schedule_enabled: false,
  schedule_weekdays: [0, 1, 2, 3, 4],
  schedule_start_time: "09:00",
  schedule_end_time: "18:00",
  iteration_strategy: "linear",
  candidates_per_iteration: 2,
  approval_score: 8,
  require_human_approval_before_apply: false,
  enabled: true,
};
const testIsActive = (status: string) =>
  ["queued", "awaiting_approval", "running"].includes(status);
const draftOf = (b: Build, copy = false): Draft => ({
  ...empty,
  id: copy ? "" : b.id,
  name: copy ? `${b.name} copy` : b.name,
  runner_id: b.runner_id,
  runner_version: b.runner_version ?? null,
  execution_environment_id: b.execution_environment_id ?? "",
  target_environment_id: b.target_environment_id ?? "",
  purpose: b.purpose,
  manager_template_id: b.manager_template_id ?? "",
  model_profile_name: b.model_profile_name ?? "",
  test_case_set_id: b.test_case_set_id ?? "",
  timezone: b.timezone,
  repeat_interval_minutes: b.repeat_interval_minutes,
  run_limit: b.run_limit,
  cadence_mode: b.cadence_mode ?? "after_completion",
  overrun_policy: b.overrun_policy ?? "wait",
  schedule_enabled: b.schedule_enabled ?? false,
  schedule_weekdays: b.schedule_weekdays ?? [0, 1, 2, 3, 4],
  schedule_start_time: b.schedule_start_time ?? "09:00",
  schedule_end_time: b.schedule_end_time ?? "18:00",
  iteration_strategy: b.iteration_strategy ?? "linear",
  candidates_per_iteration: b.candidates_per_iteration ?? 2,
  approval_score: b.approval_score,
  require_human_approval_before_apply:
    b.require_human_approval_before_apply ?? false,
  enabled: b.enabled,
});
const Field = ({
  label,
  description,
  children,
  as = "label",
}: {
  label: string;
  description?: string;
  children: ReactNode;
  as?: "div" | "label";
}) => {
  const Container = as;
  return (
  <Container className="modal-setting-row">
    <span>
      {description ? (
        <SectionInfo title={label} description={description} />
      ) : (
        label
      )}
    </span>
    {children}
  </Container>
  );
};
export function ProfileForm({
  settings,
  setSettings,
  test,
  save,
  tested,
  t,
  help,
}: {
  settings: Settings;
  setSettings: (v: Settings) => void;
  test: () => void;
  save: () => void;
  tested: boolean;
  t: typeof locales.en.evaluation;
  help: ProfileFormCopy;
}) {
  return (
    <div className="modal-form">
      <Field label={t.profileName} description={help.profileName.hint}>
        <input
          value={settings.profile_name}
          onChange={(e) =>
            setSettings({ ...settings, profile_name: e.target.value })
          }
        />
      </Field>
      <Field label={t.provider} description={help.provider.hint}>
        <select
          value={settings.provider}
          onChange={(e) =>
            setSettings({ ...settings, provider: e.target.value })
          }
        >
          <option value="azure-openai">Azure OpenAI</option>
          <option value="aws-bedrock">AWS Bedrock</option>
        </select>
      </Field>
      <Field label={t.modelDeployment} description={help.modelDeployment.hint}>
        <input
          value={settings.model}
          onChange={(e) => setSettings({ ...settings, model: e.target.value })}
        />
      </Field>
      {settings.provider === "azure-openai" ? (
        <>
          <Field label={t.azureEndpoint} description={help.azureEndpoint.hint}>
            <input
              type="url"
              placeholder="https://your-resource.openai.azure.com"
              value={settings.endpoint}
              onChange={(e) =>
                setSettings({ ...settings, endpoint: e.target.value })
              }
            />
          </Field>
          <Field label={t.secretEnv} description={help.secretEnv.hint}>
            <input
              placeholder="AZURE_OPENAI_API_KEY"
              value={settings.secret_env}
              onChange={(e) =>
                setSettings({ ...settings, secret_env: e.target.value })
              }
            />
          </Field>
        </>
      ) : (
        <>
          <Field label={t.region} description={help.region.hint}>
            <input
              placeholder="us-east-1"
              value={settings.region}
              onChange={(e) =>
                setSettings({ ...settings, region: e.target.value })
              }
            />
          </Field>
          <Field label={t.awsProfile} description={help.awsProfile.hint}>
            <input
              placeholder="default"
              value={settings.aws_profile ?? ""}
              onChange={(e) =>
                setSettings({ ...settings, aws_profile: e.target.value })
              }
            />
          </Field>
        </>
      )}
      <div className="modal-actions">
        <button className="ghost" onClick={test}>
          <Bot size={15} />
          {t.test}
        </button>
        <button className="approve" title={tested ? undefined : t.test} onClick={save}>
          {t.saveProfile}
        </button>
      </div>
    </div>
  );
}

function Direct({
  d,
  setD,
  runners,
  profiles,
  prompts,
  tests,
  executions,
  targets,
  onSave,
  locale,
}: {
  d: Draft;
  setD: (x: Draft) => void;
  runners: RunnerAsset[];
  profiles: Settings[];
  prompts: PromptTemplate[];
  tests: TargetTestCaseSet[];
  executions: ExecutionEnvironment[];
  targets: TargetEnvironment[];
  onSave: () => void;
  locale: Locale;
}) {
  const t = locales[locale],
    copy = localeMessages<BuildWizardCopy>(locale, "buildWizard");
  const selectedRunner = runners.find((runner) => runner.id === d.runner_id);
  const scheduleCopy = locale === "ko" ? { label: "실행 시간 창", hint: "선택한 요일과 시간에만 실행합니다. 그 외 시간에는 대기합니다.", enable: "실행 시간 창 사용", start: "시작", end: "종료", days: ["월", "화", "수", "목", "금", "토", "일"] } : locale === "ja" ? { label: "実行時間帯", hint: "選択した曜日と時間帯だけ実行します。時間外は待機します。", enable: "実行時間帯を使用", start: "開始", end: "終了", days: ["月", "火", "水", "木", "金", "土", "日"] } : { label: "Execution window", hint: "Run only on the selected days and time range. Outside the window, the run waits.", enable: "Enable execution window", start: "Start", end: "End", days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] };
  const [step, setStep] = useState(1);
  return (
    <div className="build-wizard">
      <ol className="wizard-steps">
        {[copy.basics, copy.evaluationSetup, copy.schedule, copy.decisionPolicy, t.ui.review].map(
          (x, i) => (
            <li key={x} className={step === i + 1 ? "current" : ""}>
              <button onClick={() => setStep(i + 1)}>
                {i + 1}. {x}
              </button>
            </li>
          ),
        )}
      </ol>
      {step === 1 && (
        <div className="modal-form">
          <Field label={copy.buildId.label} description={copy.buildId.hint}>
            <input
              value={d.id}
              onChange={(e) => setD({ ...d, id: e.target.value })}
            />
          </Field>
          <Field label={copy.buildName.label} description={copy.buildName.hint}>
            <input
              value={d.name}
              onChange={(e) => setD({ ...d, name: e.target.value })}
            />
          </Field>
          <Field label={copy.purpose.label} description={copy.purpose.hint}>
            <textarea
              value={d.purpose}
              onChange={(e) => setD({ ...d, purpose: e.target.value })}
            />
          </Field>
          <Field label={copy.runner.label} description={copy.runner.hint}>
            <select
              value={d.runner_id}
              onChange={(e) => setD({ ...d, runner_id: e.target.value, runner_version: null })}
            >
              <option value="" />
              {runners.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={copy.runnerVersion.label} description={copy.runnerVersion.hint}>
            <select value={d.runner_version ?? "latest"} onChange={(e) => setD({ ...d, runner_version: e.target.value === "latest" ? null : Number(e.target.value) })} disabled={!d.runner_id}>
              <option value="latest">{copy.runnerVersion.latest}</option>
              {(runners.find((item) => item.id === d.runner_id)?.versions ?? []).slice().sort((a, b) => b.version - a.version).map((version) => <option key={version.version} value={version.version}>v{version.version}</option>)}
            </select>
          </Field>
          {selectedRunner && <RunnerWorkflowPreview key={`${selectedRunner.id}-${d.runner_version ?? "latest"}`} runnerId={selectedRunner.id} version={d.runner_version} locale={locale} />}
          <Field
            label={copy.targetEnvironment.label}
            description={copy.targetEnvironment.hint}
          >
            <select
              value={d.target_environment_id}
              onChange={(e) =>
                setD({ ...d, target_environment_id: e.target.value })
              }
            >
              <option value="" />
              {targets.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label={copy.executionEnvironment.label}
            description={copy.executionEnvironment.hint}
          >
            <select
              value={d.execution_environment_id}
              onChange={(e) =>
                setD({ ...d, execution_environment_id: e.target.value })
              }
            >
              <option value="" />
              {executions.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      {step === 2 && (
        <div className="modal-form">
          <Field
            label={copy.managerTemplate.label}
            description={copy.managerTemplate.hint}
          >
            <select
              value={d.manager_template_id}
              onChange={(e) =>
                setD({ ...d, manager_template_id: e.target.value })
              }
            >
              {prompts.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label={copy.testCaseSet.label}
            description={copy.testCaseSet.hint}
          >
            <select
              value={d.test_case_set_id}
              onChange={(e) => setD({ ...d, test_case_set_id: e.target.value })}
            >
              {tests.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={copy.aiProfile.label} description={copy.aiProfile.hint}>
            <select
              value={d.model_profile_name}
              onChange={(e) =>
                setD({ ...d, model_profile_name: e.target.value })
              }
            >
              {profiles.map((x) => (
                <option key={x.profile_name} value={x.profile_name}>
                  {x.profile_name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      {step === 3 && (
        <div className="modal-form">
          <Field label={copy.timezone.label} description={copy.timezone.hint}>
            <input
              value={d.timezone}
              onChange={(e) => setD({ ...d, timezone: e.target.value })}
            />
          </Field>
          <Field
            label={copy.repeatInterval.label}
            description={copy.repeatInterval.hint}
          >
            <input
              type="number"
              value={d.repeat_interval_minutes}
              onChange={(e) =>
                setD({ ...d, repeat_interval_minutes: Number(e.target.value) })
              }
            />
          </Field>
          <Field label={copy.iterationTiming.label} description={copy.iterationTiming.hint}>
            <select value={d.cadence_mode} onChange={(e) => setD({ ...d, cadence_mode: e.target.value as Draft["cadence_mode"] })}><option value="after_completion">{copy.iterationTimingAfterCompletion}</option><option value="fixed">{copy.iterationTimingFixed}</option></select>
          </Field>
          {d.cadence_mode === "fixed" && <Field label={copy.overrunPolicy.label} description={copy.overrunPolicy.hint}><select value={d.overrun_policy} onChange={(e) => setD({ ...d, overrun_policy: e.target.value as Draft["overrun_policy"] })}><option value="wait">{copy.iterationTimingWait}</option><option value="interrupt_eval">{copy.iterationTimingInterrupt}</option></select></Field>}
          <Field label={copy.runLimit.label} description={copy.runLimit.hint}>
            <input
              type="number"
              value={d.run_limit}
              onChange={(e) =>
                setD({ ...d, run_limit: Number(e.target.value) })
              }
            />
          </Field>
          <Field label={scheduleCopy.label} description={scheduleCopy.hint}>
            <label className="build-schedule-toggle"><input type="checkbox" checked={d.schedule_enabled} onChange={(e) => setD({ ...d, schedule_enabled: e.target.checked })} /> {scheduleCopy.enable}</label>
            {d.schedule_enabled && <div className="build-schedule-fields"><div className="build-schedule-days">{scheduleCopy.days.map((day, index) => <label key={day}><input type="checkbox" checked={d.schedule_weekdays.includes(index)} onChange={() => setD({ ...d, schedule_weekdays: d.schedule_weekdays.includes(index) ? d.schedule_weekdays.filter((value) => value !== index) : [...d.schedule_weekdays, index] })} />{day}</label>)}</div><label>{scheduleCopy.start}<input type="time" value={d.schedule_start_time} onChange={(e) => setD({ ...d, schedule_start_time: e.target.value })} /></label><label>{scheduleCopy.end}<input type="time" value={d.schedule_end_time} onChange={(e) => setD({ ...d, schedule_end_time: e.target.value })} /></label></div>}
          </Field>
        </div>
      )}
      {step === 4 && (
        <div className="modal-form">
          <Field label={copy.iterationStrategy.label} description={copy.iterationStrategy.hint}>
            <select value={d.iteration_strategy} onChange={(e) => setD({ ...d, iteration_strategy: e.target.value as Draft["iteration_strategy"] })}>
              <option value="linear">{copy.iterationStrategyLinear}</option>
              <option value="score_select">{copy.iterationStrategyScoreSelect}</option>
            </select>
          </Field>
          {d.iteration_strategy === "score_select" && (
            <Field label={copy.candidatesPerIteration.label} description={copy.candidatesPerIteration.hint}>
              <input type="number" min="2" max="8" value={d.candidates_per_iteration} onChange={(e) => setD({ ...d, candidates_per_iteration: Number(e.target.value) })} />
            </Field>
          )}
          <Field
            label={copy.approvalScore.label}
            description={copy.approvalScore.hint}
          >
            <input
              type="number"
              value={d.approval_score}
              onChange={(e) =>
                setD({ ...d, approval_score: Number(e.target.value) })
              }
            />
          </Field>
          <Field
            label={copy.humanApproval.label}
            description={copy.humanApproval.hint}
          >
            <span className="build-approval-toggle">
              <input
                type="checkbox"
                checked={d.require_human_approval_before_apply}
                onChange={(e) =>
                  setD({
                    ...d,
                    require_human_approval_before_apply: e.target.checked,
                  })
                }
              />
              {copy.humanApprovalEnable}
            </span>
          </Field>
        </div>
      )}
      {step === 5 && (
        <div className="wizard-review">
          <dl>
            <dt>{copy.name}</dt>
            <dd>{d.name || "—"}</dd>
            <dt>{copy.runner.label}</dt>
            <dd>{runners.find((x) => x.id === d.runner_id)?.name || "—"}</dd>
          </dl>
        </div>
      )}
      <div className="modal-actions">
        {step > 1 && (
          <button className="ghost" onClick={() => setStep(step - 1)}>
            <ChevronLeft size={15} />
            {t.ui.back}
          </button>
        )}
        {step < 5 ? (
          <button className="approve" onClick={() => setStep(step + 1)}>
            {copy.next}
            <ChevronRight size={15} />
          </button>
        ) : (
          <button className="approve" onClick={onSave}>
            {t.ui.save}
          </button>
        )}
      </div>
    </div>
  );
}

function RunnerWorkflowPreview({ runnerId, version, locale }: { runnerId: string; version: number | null; locale: Locale }) {
  const t = locales[locale].ui;
  const [workflowGraph, setWorkflowGraph] = useState<WorkflowGraphDefinition | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState("");
  useEffect(() => {
    let active = true;
    const query = version === null ? "" : `?version=${encodeURIComponent(version)}`;
    api<WorkflowGraphDefinition | null>(`/api/runners/${encodeURIComponent(runnerId)}/preview-graph${query}`)
      .then((graph) => {
        if (active) setWorkflowGraph(graph);
      })
      .catch((graphError: Error) => {
        if (active) setGraphError(graphError.message);
      })
      .finally(() => {
        if (active) setGraphLoading(false);
      });
    return () => { active = false; };
  }, [runnerId, version]);
  return <section className="build-runner-workflow" aria-label={t.workflowGraph}>
    <strong>{t.workflowGraph}</strong>
    <p>{t.runnerWorkflowDescription}</p>
    {graphLoading ? <p className="hint">{t.loadingGraph}</p> : workflowGraph?.nodes.length ? <WorkflowGraph nodes={workflowGraph.nodes} edges={workflowGraph.edges} /> : <p className="hint">{graphError || t.noWorkflowGraph}</p>}
  </section>;
}

function Quick({
  item,
  profiles,
  create,
  back,
  close,
  locale,
}: {
  item: QuickStart;
  profiles: Settings[];
  create: (id: string, v: Record<string, string>) => Promise<unknown>;
  back: () => void;
  close: () => void;
  locale: Locale;
}) {
  const t = locales[locale].ui;
  const profileCopy = localeMessages<{ profileForm: ProfileFormCopy }>(locale, "settingsPage").profileForm;
  const display = item;
  const createProfileValue = "__create_model_profile__";
  const [v, setV] = useState<Record<string, string>>(() =>
      Object.fromEntries(
        item.parameters.map((p) => [
          p.key,
          p.default ??
            (p.type === "model_profile"
              ? (profiles[0]?.profile_name ?? "")
              : ""),
        ]),
      ),
    ),
    [newProfile, setNewProfile] = useState<Settings>({
      profile_name: "",
      provider: "azure-openai",
      model: "",
      endpoint: "",
      region: "us-east-1",
      secret_env: "AZURE_OPENAI_API_KEY",
      aws_profile: "",
    }),
    [review, setReview] = useState(false),
    [busy, setBusy] = useState(false),
    [workflowGraph, setWorkflowGraph] = useState<WorkflowGraphDefinition | null>(null),
    [graphLoading, setGraphLoading] = useState(true),
    [graphError, setGraphError] = useState("");
  useEffect(() => {
    let active = true;
    api<WorkflowGraphDefinition | null>(`/api/quick-starts/${item.id}/preview-graph`, "POST")
      .then((graph) => {
        if (active) setWorkflowGraph(graph);
      })
      .catch((graphError: Error) => {
        if (active) setGraphError(graphError.message);
      })
      .finally(() => {
        if (active) setGraphLoading(false);
      });
    return () => { active = false; };
  }, [item.id]);
  const submit = async () => {
    setBusy(true);
    try {
      const profileParameter = display.parameters.find((parameter) => parameter.type === "model_profile");
      const inputs = { ...v };
      if (profileParameter && inputs[profileParameter.key] === createProfileValue) {
        inputs[profileParameter.key] = newProfile.profile_name;
        Object.assign(inputs, {
          __model_profile_mode: "create",
          __model_profile_provider: newProfile.provider,
          __model_profile_model: newProfile.model,
          __model_profile_endpoint: newProfile.endpoint,
          __model_profile_region: newProfile.region,
          __model_profile_secret_env: newProfile.secret_env,
          __model_profile_aws_profile: newProfile.aws_profile ?? "",
        });
      }
      await create(item.id, inputs);
      close();
    } catch {
      // The parent reports creation failures through the shared toast.
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="quick-start-form">
      <button className="ghost" onClick={back}>
        <ChevronLeft size={15} />
        {t.quickStarts}
      </button>
      <div className="quick-start-form__heading">
        <Sparkles size={19} />
        <div>
          <strong>{display.name}</strong>
          <p>{display.description}</p>
        </div>
      </div>
      {!review && <section className="quick-start-workflow" aria-label={t.workflowGraph}>
        <strong>{t.workflowGraph}</strong>
        <p>{t.quickStartWorkflowDescription}</p>
        {graphLoading ? <p className="hint">{t.loadingGraph}</p> : workflowGraph?.nodes.length ? <WorkflowGraph nodes={workflowGraph.nodes} edges={workflowGraph.edges} /> : <p className="hint">{graphError || t.noWorkflowGraph}</p>}
      </section>}
      {review ? (
        <div className="quick-start-review">
          <p>{t.quickStartReview}</p>
          <dl>
            {display.parameters.map((p) => (
              <>
                <dt key={`${p.key}a`}>{p.label}</dt>
                <dd key={`${p.key}b`}>
                  {p.type === "model_profile" && v[p.key] === createProfileValue
                    ? newProfile.profile_name || "—"
                    : v[p.key] || "—"}
                </dd>
              </>
            ))}
          </dl>
        </div>
      ) : (
        <div className="modal-form">
          {display.parameters.map((p) =>
            p.type === "model_profile" ? (
              <div className="quick-start-model-profile" key={p.key}>
                <Field label={p.label} description={p.tooltip ?? p.description} as="div">
                  <select
                    value={v[p.key]}
                    onChange={(e) => setV({ ...v, [p.key]: e.target.value })}
                  >
                    {profiles.map((x) => (
                      <option key={x.profile_name} value={x.profile_name}>
                        {x.profile_name}
                      </option>
                    ))}
                    <option value={createProfileValue}>{profileCopy.createNewAiProfile.label}</option>
                  </select>
                </Field>
                {v[p.key] === createProfileValue && (
                  <div className="quick-start-profile-form">
                    <Field label={profileCopy.profileName.label} description={profileCopy.profileName.hint}>
                      <input
                        value={newProfile.profile_name}
                        onChange={(e) => setNewProfile({ ...newProfile, profile_name: e.target.value })}
                      />
                    </Field>
                    <Field label={profileCopy.provider.label} description={profileCopy.provider.hint}>
                      <select
                        value={newProfile.provider}
                        onChange={(e) => setNewProfile({ ...newProfile, provider: e.target.value })}
                      >
                        <option value="azure-openai">Azure OpenAI</option>
                        <option value="aws-bedrock">AWS Bedrock</option>
                      </select>
                    </Field>
                    <Field label={profileCopy.modelDeployment.label} description={profileCopy.modelDeployment.hint}>
                      <input
                        value={newProfile.model}
                        onChange={(e) => setNewProfile({ ...newProfile, model: e.target.value })}
                      />
                    </Field>
                    {newProfile.provider === "azure-openai" ? (
                      <>
                        <Field label={profileCopy.azureEndpoint.label} description={profileCopy.azureEndpoint.hint}>
                          <input
                            type="url"
                            placeholder="https://your-resource.openai.azure.com"
                            value={newProfile.endpoint}
                            onChange={(e) => setNewProfile({ ...newProfile, endpoint: e.target.value })}
                          />
                        </Field>
                        <Field label={profileCopy.secretEnv.label} description={profileCopy.secretEnv.hint}>
                          <input
                            placeholder="AZURE_OPENAI_API_KEY"
                            value={newProfile.secret_env}
                            onChange={(e) => setNewProfile({ ...newProfile, secret_env: e.target.value })}
                          />
                        </Field>
                      </>
                    ) : (
                      <>
                        <Field label={profileCopy.region.label} description={profileCopy.region.hint}>
                          <input
                            placeholder="us-east-1"
                            value={newProfile.region}
                            onChange={(e) => setNewProfile({ ...newProfile, region: e.target.value })}
                          />
                        </Field>
                        <Field label={profileCopy.awsProfile.label} description={profileCopy.awsProfile.hint}>
                          <input
                            placeholder="default"
                            value={newProfile.aws_profile ?? ""}
                            onChange={(e) => setNewProfile({ ...newProfile, aws_profile: e.target.value })}
                          />
                        </Field>
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <Field key={p.key} label={p.label} description={p.tooltip ?? p.description}>
              {p.type === "select" ? (
                <select
                  value={v[p.key]}
                  onChange={(e) => setV({ ...v, [p.key]: e.target.value })}
                >
                  {p.options?.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={p.type === "url" ? "url" : "text"}
                  value={v[p.key]}
                  placeholder={p.placeholder}
                  onChange={(e) => setV({ ...v, [p.key]: e.target.value })}
                />
              )}
              </Field>
            ),
          )}
        </div>
      )}
      <div className="modal-actions">
        {review ? (
          <>
            <button className="ghost" onClick={() => setReview(false)}>
              {t.edit}
            </button>
            <button className="approve" disabled={busy} onClick={submit}>
              {busy ? t.creating : t.createAssetsAndBuild}
            </button>
          </>
        ) : (
          <button className="approve" onClick={() => setReview(true)}>
            {t.review}
            <ChevronRight size={15} />
          </button>
        )}
      </div>
    </div>
  );
}

function QuickStartCard({
  item,
  translation,
  labels,
  pick,
}: {
  item: QuickStart;
  translation: QuickStartTranslation | null;
  labels?: { name: string; description: string };
  pick: (item: QuickStart) => void;
}) {
  const display = withQuickStartTranslation(item, translation, labels);
  return (
    <article className="quick-start-card">
      <button className="quick-start-card__select" onClick={() => pick(item)}>
        <Sparkles size={18} />
        <span>
          <strong>{display.name}</strong>
          <small>{display.description}</small>
          <em>
            {item.publisher?.name ?? "Community"} · v{item.version}
          </em>
        </span>
        <ChevronRight size={16} />
      </button>
    </article>
  );
}

export function BuildsPage(props: {
  locale: Locale;
  builds: Build[];
  runners: RunnerAsset[];
  profiles: Settings[];
  promptTemplates: PromptTemplate[];
  testCaseSets: TargetTestCaseSet[];
  executionEnvironments: ExecutionEnvironment[];
  targetEnvironments: TargetEnvironment[];
  onInvoke: (id: string) => void;
  onTest: (id: string) => Promise<Run>;
  onCreate: (v: Draft) => Promise<unknown>;
  onUpdate: (id: string, v: Draft) => Promise<unknown>;
  onToggleStar: (id: string, starred: boolean) => Promise<unknown>;
  onDelete: (id: string) => void;
  onQuickStartCreate: (
    id: string,
    v: Record<string, string>,
  ) => Promise<unknown>;
  quickStartRequest?: number;
  quickStartSelection?: string;
  onQuickStartRequestHandled?: () => void;
}) {
  const {
    locale,
    builds,
    runners,
    profiles,
    promptTemplates,
    testCaseSets,
    executionEnvironments,
    targetEnvironments,
    onInvoke,
    onTest,
    onCreate,
    onUpdate,
    onToggleStar,
    onDelete,
    onQuickStartCreate,
    quickStartRequest,
    quickStartSelection,
    onQuickStartRequestHandled,
  } = props;
  const t = locales[locale],
    ui = t.ui;
  const [open, setOpen] = useState(false),
    [edit, setEdit] = useState<Build | null>(null),
    [d, setD] = useState(empty),
    [mode, setMode] = useState<"chooser" | "quick" | "direct">("chooser"),
    [items, setItems] = useState<QuickStart[]>([]),
    [picked, setPicked] = useState<QuickStart | null>(null),
    [error, setError] = useState(""),
    [page, setPage] = useState(1),
    [size, setSize] = useState(15),
    [selected, setSelected] = useState(""),
    [testRun, setTestRun] = useState<Run | null>(null),
    file = useRef<HTMLInputElement>(null);
  const translations = useTemplateTranslations<QuickStartTranslation>(
    "quick-start",
    items.map((item) => item.id),
    locale,
  );
  const translationCopy = locales[locale].templateTranslation;
  const allQuickStartsTranslated =
    items.length > 0 && items.every((item) => Boolean(translations.content(item.id)));
  const quickStartLabels = localeMessages<
    Record<string, { name: string; description: string }>
  >(locale, "quickStartLabels");
  const taskCount = (build: Build) =>
    testCaseSets.find((set) => set.id === build.test_case_set_id)?.cases.length ??
    build.test_cases?.length ??
    0;
  useEffect(() => {
    if (!testRun || !testIsActive(testRun.status)) return;
    const timer = window.setInterval(() => {
      api<Run>(`/api/build-tests/${encodeURIComponent(testRun.id)}`)
        .then(setTestRun)
        .catch(() => setTestRun(null));
    }, 750);
    return () => window.clearInterval(timer);
  }, [testRun]);
  const startTest = (id: string) => {
    onTest(id)
      .then(setTestRun)
      .catch((error) =>
        setError(
          error instanceof Error ? error.message : ui.testFailedToStart,
        ),
      );
  };
  const closeTest = () => {
    if (testRun && !testIsActive(testRun.status))
      api(
        `/api/build-tests/${encodeURIComponent(testRun.id)}`,
        "DELETE",
      ).catch(() => undefined);
    setTestRun(null);
  };
  const start = (
    initialMode: "chooser" | "quick" = "chooser",
    initialQuickStartId?: string,
  ) => {
    setEdit(null);
    setD(empty);
    setMode(initialMode);
    setPicked(null);
    setOpen(true);
    api<QuickStart[]>("/api/quick-starts")
      .then((next) => {
        setItems(next);
        setPicked(
          initialQuickStartId
            ? (next.find((item) => item.id === initialQuickStartId) ?? null)
            : null,
        );
      })
      .catch((e) => setError(e.message));
  };
  useEffect(() => {
    if (!quickStartRequest) return;
    queueMicrotask(() => {
      start("quick", quickStartSelection);
      onQuickStartRequestHandled?.();
    });
  }, [quickStartRequest, quickStartSelection, onQuickStartRequestHandled]);
  const importItem = async (f: File | undefined) => {
    if (!f) return;
    try {
      await upload("/api/quick-starts/import-package", f);
      setItems(await api("/api/quick-starts"));
    } catch (e) {
      setError(e instanceof Error ? e.message : ui.importFailed);
    }
  };
  const cols: Column<Build>[] = [
      {
        id: "select",
        header: <span className="visually-hidden">Select</span>,
        render: (b) => (
          <input
            aria-label={`Select ${b.name}`}
            checked={selected === b.id}
            name="build-selection"
            onChange={() => setSelected(b.id)}
            type="radio"
          />
        ),
      },
      {
        id: "name",
        header: locales[locale].evaluation.name,
        render: (b) => (
          <span className="build-name">
            <button
              className={`build-star${b.starred ? " build-star--active" : ""}`}
              type="button"
              aria-label={b.starred ? `Unstar ${b.name}` : `Star ${b.name}`}
              title={b.starred ? `Unstar ${b.name}` : `Star ${b.name}`}
              onClick={(event) => {
                event.stopPropagation();
                void onToggleStar(b.id, !b.starred);
              }}
            >
              <Star size={16} fill={b.starred ? "currentColor" : "none"} />
            </button>
            {b.name}
          </span>
        ),
        sortValue: (b) => b.name,
      },
      {
        id: "tasks",
        header: t.evaluation.tasks,
        render: (b) => taskCount(b),
        sortValue: taskCount,
      },
      {
        id: "repository",
        header: ui.repository,
        render: (b) => b.repository_name ?? b.repository,
        sortValue: (b) => b.repository_name ?? b.repository,
      },
      {
        id: "created",
        header: ui.created,
        render: (b) => formatDate(locale, b.created_at),
        sortValue: (b) => b.created_at ?? "",
      },
      {
        id: "last-started",
        header: ui.lastStarted,
        render: (b) => formatDate(locale, b.last_run_at),
        sortValue: (b) => b.last_run_at ?? "",
      },
      {
        id: "action",
        header: ui.action,
        render: (b) => (
          <span className="build-actions">
            <button
              className="ghost icon-button"
              onClick={(event) => {
                event.stopPropagation();
                startTest(b.id);
              }}
            >
              <TestTube2 size={15} />
            </button>
            <button
              className="approve icon-button"
              onClick={() => onInvoke(b.id)}
            >
              <Play size={15} />
            </button>
            <button
              className="icon-button danger"
              onClick={() => onDelete(b.id)}
            >
              <Trash2 size={15} />
            </button>
          </span>
        ),
      },
    ],
    pages = Math.max(1, Math.ceil(builds.length / size)),
    rows = builds.slice((page - 1) * size, page * size),
    save = async () => {
      await (edit ? onUpdate(edit.id, d) : onCreate(d));
      setOpen(false);
    };
  return (
    <>
      <section className="panel build-panel">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={<SectionInfo title={locales[locale].evaluation.buildList} description={localeMessages<Record<string, string>>(locale, "sectionDetails").buildList} />} />
            <p className="hint section-description">{locales[locale].evaluation.buildListDescription}</p>
          </div>
          <div className="build-list-actions">
            <button
              className="ghost"
              disabled={!selected}
              onClick={() => {
                const b = builds.find((x) => x.id === selected);
                if (b) {
                  setEdit(null);
                  setD(draftOf(b, true));
                  setMode("direct");
                  setOpen(true);
                }
              }}
            >
              <Copy size={15} />
              {ui.duplicate}
            </button>
            <button className="approve" onClick={() => start()}>
              <Plus size={14} />
              {ui.create}
            </button>
          </div>
        </div>
        <div className="build-list-toolbar">
          <PageSizeSelect
            locale={locale}
            value={size}
            onChange={(x) => {
              setSize(x);
              setPage(1);
            }}
          />
        </div>
        <DataTable
          columns={cols}
          rows={rows}
          onRowClick={(b) => {
            setSelected(b.id);
            setEdit(b);
            setD(draftOf(b));
            setMode("direct");
            setOpen(true);
          }}
          className="build-table"
          gridTemplateColumns="36px 1fr 90px 1fr 180px 180px 110px"
        />
        <Pagination
          locale={locale}
          page={page}
          totalPages={pages}
          totalItems={builds.length}
          pageSize={size}
          onPageChange={setPage}
        />
      </section>
      {testRun && (
        <EvaluationsPage
          runs={[testRun]}
          locale={locale}
          initialSelectedRun={testRun}
          onSelectedRunClose={closeTest}
          onStop={() => undefined}
          onRetry={() => undefined}
          onApprove={() => undefined}
          onReject={() => undefined}
          onEmergencyStop={() => undefined}
          onDeleteRuns={() => Promise.resolve()}
        />
      )}
      <Modal
        open={open}
        title={
          edit
            ? t.evaluation.createBuild
            : t.evaluation.createBuild
        }
        onClose={() => setOpen(false)}
      >
        {mode === "chooser" && (
          <div className="create-mode-picker">
            <button
              className="create-mode-card"
              onClick={() => setMode("quick")}
            >
              <Sparkles size={22} />
              <span>
                <strong>{ui.quickStart}</strong>
                <small>{ui.quickStartDescription}</small>
              </span>
              <ChevronRight size={18} />
            </button>
            <button
              className="create-mode-card"
              onClick={() => setMode("direct")}
            >
              <Wrench size={22} />
              <span>
                <strong>{ui.manualSetup}</strong>
                <small>{ui.manualSetupDescription}</small>
              </span>
              <ChevronRight size={18} />
            </button>
          </div>
        )}
        {mode === "quick" && !picked && (
          <div className="quick-start-picker">
            <div className="quick-start-picker__head">
              <button className="ghost" onClick={() => setMode("chooser")}>
                <ChevronLeft size={15} />
                {ui.back}
              </button>
              <input
                className="visually-hidden"
                ref={file}
                type="file"
                accept="application/zip,.zip"
                onChange={(e) => importItem(e.target.files?.[0])}
              />
              <div className="template-picker-actions">
                <button
                  className="ghost"
                  type="button"
                  disabled={translations.loading || translations.cacheLoading}
                  onClick={
                    allQuickStartsTranslated
                      ? () => translations.showOriginal()
                      : () => translations.translate()
                  }
                >
                  <Languages size={15} />
                  {translations.loading
                    ? translationCopy.translating
                    : translations.cacheLoading
                      ? translationCopy.checkingCache
                    : allQuickStartsTranslated
                      ? translationCopy.showOriginal
                      : translationCopy.translate}
                </button>
                <button className="ghost" onClick={() => file.current?.click()}>
                  <FileUp size={15} />
                  {ui.importQuickStart}
                </button>
              </div>
            </div>
            <div className="quick-start-list">
              {translations.cacheLoading ? (
                <p className="hint">{translationCopy.checkingCache}</p>
              ) : (
                items.map((item) => (
                  <QuickStartCard
                    key={item.id}
                    item={item}
                    translation={translations.content(item.id)}
                    labels={quickStartLabels[item.id]}
                    pick={setPicked}
                  />
                ))
              )}
            </div>
            {(error || translations.error) && (
              <small className="hint">{error || translationCopy.failed}</small>
            )}
          </div>
        )}
        {mode === "quick" && picked && (
          <Quick
            key={picked.id}
            item={withQuickStartTranslation(
              picked,
              translations.content(picked.id),
              quickStartLabels[picked.id],
            )}
            profiles={profiles}
            create={onQuickStartCreate}
            back={() => setPicked(null)}
            close={() => setOpen(false)}
            locale={locale}
          />
        )}{" "}
        {mode === "direct" && (
          <Direct
            d={d}
            setD={setD}
            runners={runners}
            profiles={profiles}
            prompts={promptTemplates}
            tests={testCaseSets}
            executions={executionEnvironments}
            targets={targetEnvironments}
            onSave={save}
            locale={locale}
          />
        )}
      </Modal>
    </>
  );
}
