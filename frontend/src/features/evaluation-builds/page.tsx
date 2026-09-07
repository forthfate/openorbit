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
  TestTube2,
  Trash2,
  Wrench,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
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
} from "../../domain/models";
import { intlLocales, localeMessages, locales, type Locale } from "../../locales";
import { api } from "../../services/api";
import { useTemplateTranslations } from "../../services/use-template-translation";
import { EvaluationsPage } from "../evaluations/page";

type Draft = {
  id: string;
  name: string;
  runner_id: string;
  execution_environment_id: string;
  target_environment_id: string;
  purpose: string;
  manager_template_id: string;
  model_profile_name: string;
  test_case_set_id: string;
  timezone: string;
  repeat_interval_minutes: number;
  run_limit: number;
  approval_score: number;
  enabled: boolean;
};

type QuickStartTranslation = {
  name: string;
  description: string;
  parameters: {
    label: string;
    description?: string;
    placeholder?: string;
    options?: { label: string }[];
  }[];
};
type LabelCopy = { label: string; hint: string };
export type ProfileFormCopy = {
  profileName: LabelCopy;
  provider: LabelCopy;
  modelDeployment: LabelCopy;
};
type BuildWizardCopy = {
  buildId: LabelCopy;
  buildName: LabelCopy;
  runner: LabelCopy;
  targetEnvironment: LabelCopy;
  executionEnvironment: LabelCopy;
  purpose: LabelCopy;
  managerTemplate: LabelCopy;
  testCaseSet: LabelCopy;
  aiProfile: LabelCopy;
  timezone: LabelCopy;
  repeatInterval: LabelCopy;
  runLimit: LabelCopy;
  approvalScore: LabelCopy;
  name: string;
  next: string;
};

const withQuickStartTranslation = (item: QuickStart, translation: QuickStartTranslation | null): QuickStart =>
  translation
    ? {
        ...item,
        name: translation.name,
        description: translation.description,
        parameters: item.parameters.map((parameter, index) => ({
          ...parameter,
          ...translation.parameters[index],
          options: parameter.options?.map((option, optionIndex) => ({
            ...option,
            ...translation.parameters[index]?.options?.[optionIndex],
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
  execution_environment_id: "",
  target_environment_id: "",
  purpose: "",
  manager_template_id: "",
  model_profile_name: "",
  test_case_set_id: "",
  timezone: "Asia/Tokyo",
  repeat_interval_minutes: 30,
  run_limit: 1,
  approval_score: 8,
  enabled: true,
};
const testIsActive = (status: string) => ["queued", "awaiting_approval", "running"].includes(status);
const draftOf = (b: Build, copy = false): Draft => ({
  ...empty,
  id: copy ? "" : b.id,
  name: copy ? `${b.name} copy` : b.name,
  runner_id: b.runner_id,
  execution_environment_id: b.execution_environment_id ?? "",
  target_environment_id: b.target_environment_id ?? "",
  purpose: b.purpose,
  manager_template_id: b.manager_template_id ?? "",
  model_profile_name: b.model_profile_name ?? "",
  test_case_set_id: b.test_case_set_id ?? "",
  timezone: b.timezone,
  repeat_interval_minutes: b.repeat_interval_minutes,
  run_limit: b.run_limit,
  approval_score: b.approval_score,
  enabled: b.enabled,
});
const Field = ({ label, description, children }: { label: string; description?: string; children: ReactNode }) => (
  <label className="modal-setting-row">
    <span>{description ? <SectionInfo title={label} description={description} /> : label}</span>
    {children}
  </label>
);
export function ProfileForm({
  settings,
  setSettings,
  test,
  save,
  tested,
  onClose,
  t,
  help,
}: {
  settings: Settings;
  setSettings: (v: Settings) => void;
  test: () => void;
  save: () => void;
  tested: boolean;
  onClose: () => void;
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
      <div className="modal-actions">
        <button className="ghost" onClick={onClose}>
          {t.cancel}
        </button>
        <button className="ghost" onClick={test}>
          <Bot size={15} />
          {t.test}
        </button>
        <button className="approve" disabled={!tested} onClick={save}>
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
  onClose,
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
  onClose: () => void;
  locale: Locale;
}) {
  const t = locales[locale], copy = localeMessages<BuildWizardCopy>(locale, "buildWizard");
  const [step, setStep] = useState(1);
  return (
    <div className="build-wizard">
      <ol className="wizard-steps">
        {[t.common.evaluationBuild, t.evaluation.criteria, t.ui.review].map(
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
          <Field label={copy.runner.label} description={copy.runner.hint}>
            <select
              value={d.runner_id}
              onChange={(e) => setD({ ...d, runner_id: e.target.value })}
            >
              <option value="" />
              {runners.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={copy.targetEnvironment.label} description={copy.targetEnvironment.hint}>
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
          <Field label={copy.executionEnvironment.label} description={copy.executionEnvironment.hint}>
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
          <Field label={copy.purpose.label} description={copy.purpose.hint}>
            <textarea
              value={d.purpose}
              onChange={(e) => setD({ ...d, purpose: e.target.value })}
            />
          </Field>
        </div>
      )}
      {step === 2 && (
        <div className="modal-form">
          <Field label={copy.managerTemplate.label} description={copy.managerTemplate.hint}>
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
          <Field label={copy.testCaseSet.label} description={copy.testCaseSet.hint}>
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
          <Field label={copy.timezone.label} description={copy.timezone.hint}>
            <input
              value={d.timezone}
              onChange={(e) => setD({ ...d, timezone: e.target.value })}
            />
          </Field>
          <Field label={copy.repeatInterval.label} description={copy.repeatInterval.hint}>
            <input
              type="number"
              value={d.repeat_interval_minutes}
              onChange={(e) =>
                setD({ ...d, repeat_interval_minutes: Number(e.target.value) })
              }
            />
          </Field>
          <Field label={copy.runLimit.label} description={copy.runLimit.hint}>
            <input
              type="number"
              value={d.run_limit}
              onChange={(e) =>
                setD({ ...d, run_limit: Number(e.target.value) })
              }
            />
          </Field>
          <Field label={copy.approvalScore.label} description={copy.approvalScore.hint}>
            <input
              type="number"
              value={d.approval_score}
              onChange={(e) =>
                setD({ ...d, approval_score: Number(e.target.value) })
              }
            />
          </Field>
        </div>
      )}
      {step === 3 && (
        <div className="wizard-review">
          <p>{t.ui.review}</p>
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
        {step < 3 ? (
          <button className="approve" onClick={() => setStep(step + 1)}>
            {copy.next}
            <ChevronRight size={15} />
          </button>
        ) : (
          <button className="approve" onClick={onSave}>
            {t.ui.save}
          </button>
        )}
        <button className="ghost" onClick={onClose}>
          {t.ui.cancel}
        </button>
      </div>
    </div>
  );
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
  const display = item;
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
    [review, setReview] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    try {
      await create(item.id, v);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Creation failed");
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
      {review ? (
        <div className="quick-start-review">
          <p>{t.quickStartReview}</p>
          <dl>
            {display.parameters.map((p) => (
              <>
                <dt key={`${p.key}a`}>{p.label}</dt>
                <dd key={`${p.key}b`}>{v[p.key] || "—"}</dd>
              </>
            ))}
          </dl>
        </div>
      ) : (
        <div className="modal-form">
          {display.parameters.map((p) => (
            <Field key={p.key} label={p.label}>
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
              ) : p.type === "model_profile" ? (
                <select
                  value={v[p.key]}
                  onChange={(e) => setV({ ...v, [p.key]: e.target.value })}
                >
                  {profiles.map((x) => (
                    <option key={x.profile_name} value={x.profile_name}>
                      {x.profile_name}
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
          ))}
        </div>
      )}
      <div className="modal-actions">
        {error && <small className="hint">{error}</small>}
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
        <button className="ghost" onClick={close}>
          {t.cancel}
        </button>
      </div>
    </div>
  );
}

function QuickStartCard({item,translation,pick}:{item:QuickStart;translation:QuickStartTranslation|null;pick:(item:QuickStart)=>void}){
  const display=withQuickStartTranslation(item,translation)
  return <article className="quick-start-card"><button className="quick-start-card__select" onClick={()=>pick(item)}><Sparkles size={18}/><span><strong>{display.name}</strong><small>{display.description}</small><em>{item.publisher?.name??'Community'} · v{item.version}</em></span><ChevronRight size={16}/></button></article>
}

export function EvaluationBuildsPage(props: {
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
  onDelete: (id: string) => void;
  onQuickStartCreate: (
    id: string,
    v: Record<string, string>,
  ) => Promise<unknown>;
  quickStartRequest?: number;
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
    onDelete,
    onQuickStartCreate,
    quickStartRequest,
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
  const translations = useTemplateTranslations<QuickStartTranslation>("quick-start", items.map((item) => item.id), locale);
  const translationCopy = locales[locale].templateTranslation;
  useEffect(() => {
    if (!testRun || !testIsActive(testRun.status)) return;
    const timer = window.setInterval(() => {
      api<Run>(`/api/evaluation-build-tests/${encodeURIComponent(testRun.id)}`)
        .then(setTestRun)
        .catch(() => setTestRun(null));
    }, 750);
    return () => window.clearInterval(timer);
  }, [testRun]);
  const startTest = (id: string) => {
    onTest(id).then(setTestRun).catch((error) =>
      setError(error instanceof Error ? error.message : "Test failed to start"),
    );
  };
  const closeTest = () => {
    if (testRun && !testIsActive(testRun.status))
      api(`/api/evaluation-build-tests/${encodeURIComponent(testRun.id)}`, "DELETE").catch(() => undefined);
    setTestRun(null);
  };
  const start = (initialMode: "chooser" | "quick" = "chooser") => {
    setEdit(null);
    setD(empty);
    setMode(initialMode);
    setPicked(null);
    setOpen(true);
    api<QuickStart[]>("/api/quick-starts")
      .then(setItems)
      .catch((e) => setError(e.message));
  };
  useEffect(() => {
    if (!quickStartRequest) return;
    queueMicrotask(() => {
      start("quick");
      onQuickStartRequestHandled?.();
    });
  }, [quickStartRequest, onQuickStartRequestHandled]);
  const importItem = async (f: File | undefined) => {
    if (!f) return;
    try {
      await api("/api/quick-starts/import", "POST", {
        manifest: JSON.parse(await f.text()),
      });
      setItems(await api("/api/quick-starts"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
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
            name="evaluation-build-selection"
            onChange={() => setSelected(b.id)}
            type="radio"
          />
        ),
      },
      {
        id: "name",
        header: locales[locale].evaluation.name,
        render: (b) => b.name,
      },
      {
        id: "repository",
        header: ui.repository,
        render: (b) => b.repository_name ?? b.repository,
      },
      { id: "created", header: ui.created, render: (b) => formatDate(locale, b.created_at) },
      {
        id: "last-started",
        header: ui.lastStarted,
        render: (b) => formatDate(locale, b.last_run_at),
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
      <section className="panel evaluation-build-panel">
        <div className="panel-title-action">
          <PanelHeader title={locales[locale].evaluation.evaluationBuildList} />
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
          className="evaluation-build-table"
          gridTemplateColumns="36px 1fr 1fr 180px 180px 110px"
        />
        <Pagination locale={locale} page={page} totalPages={pages} totalItems={builds.length} pageSize={size} onPageChange={setPage}/>
      </section>
      {testRun && <EvaluationsPage runs={[testRun]} locale={locale} initialSelectedRun={testRun} onSelectedRunClose={closeTest} onStop={() => undefined} onApprove={() => undefined} onReject={() => undefined} onEmergencyStop={() => undefined} onDeleteRuns={() => Promise.resolve()} />}
      <Modal
        open={open}
        title={
          edit
            ? t.evaluation.createEvaluationBuild
            : t.evaluation.createEvaluationBuild
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
                accept="application/json,.json"
                onChange={(e) => importItem(e.target.files?.[0])}
              />
              <div className="template-picker-actions">
                <button className="ghost" type="button" disabled={translations.loading} onClick={translations.content(items[0]?.id ?? "") ? translations.showOriginal : translations.translate}>
                  <Languages size={15} />
                  {translations.loading ? translationCopy.translating : translations.content(items[0]?.id ?? "") ? translationCopy.showOriginal : translationCopy.translate}
                </button>
                <button className="ghost" onClick={() => file.current?.click()}>
                  <FileUp size={15} />
                  {ui.importQuickStart}
                </button>
              </div>
            </div>
            <div className="quick-start-list">
              {items.map((item) => <QuickStartCard key={item.id} item={item} translation={translations.content(item.id)} pick={setPicked} />)}
            </div>
            {(error || translations.error) && <small className="hint">{error || translationCopy.failed}</small>}
          </div>
        )}
        {mode === "quick" && picked && (
          <Quick
            item={withQuickStartTranslation(picked, translations.content(picked.id))}
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
            onClose={() => setOpen(false)}
            locale={locale}
          />
        )}
      </Modal>
    </>
  );
}
