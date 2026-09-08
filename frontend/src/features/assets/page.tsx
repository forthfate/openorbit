/* eslint-disable @typescript-eslint/no-explicit-any -- compact environment editor drafts */
import {
  ChevronLeft,
  ChevronRight,
  FileUp,
  Languages,
  Plus,
  Trash2,
} from "lucide-react";
import { Children, useEffect, useRef, useState } from "react";
import type {
  ExecutionEnvironment,
  PromptTemplate,
  RunnerAsset,
  RunnerTemplate,
  Settings,
  TargetEnvironment,
  TargetTestCaseSet,
  TestCase,
  Workflow,
  WorkflowStep,
} from "../../domain/models";
import {
  localeMessageMap,
  localeMessages,
  locales,
  type Locale,
} from "../../locales";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { PythonEditor } from "../../components/ui/python-editor";
import { YamlEditor } from "../../components/ui/yaml-editor";
import { api } from "../../services/api";
import { useTemplateTranslations } from "../../services/use-template-translation";
import { useToast } from "../../components/ui/toast-context";
import { ProfileForm, type ProfileFormCopy } from "../evaluation-builds/page";

const text = localeMessageMap<Record<string, string>>("assetsText");
const testBlank: TargetTestCaseSet = {
  id: "",
  name: "",
  description: "",
  cases: [{ id: "case-1", name: "", prompt: "", acceptance: "" }],
};
const fieldHelp = localeMessageMap<Record<string, string>>("assetsHelp");
const runnerLabels = localeMessageMap<Record<string, string>>("runnerLabels");
const phases: WorkflowStep["phase"][] = [
  "init",
  "setup",
  "run",
  "eval",
  "teardown",
  "finalize",
];
const pipelineYaml = (workflow: Workflow | null | undefined) =>
  phases
    .map((phase) => {
      const steps =
        workflow?.steps?.filter((step) => step.phase === phase) ?? [];
      const entries = steps.length
        ? steps
            .map(
              (step) =>
                `  - id: ${JSON.stringify(step.id)}\n    name: ${JSON.stringify(step.name)}\n    command: ${JSON.stringify(step.command)}\n    timeout_seconds: ${step.timeout_seconds}\n    approval: ${step.approval}\n    on_failure: ${step.on_failure}\n    minimum_interval_seconds: ${step.minimum_interval_seconds ?? 0}`,
            )
            .join("\n")
        : "  []";
      return `${phase}:\n${entries}`;
    })
    .join("\n\n");

function Catalog({
  title,
  button,
  children,
  emptyHint,
  showRunners = false,
  runners,
  onRefresh,
  locale,
}: {
  title: string;
  button: React.ReactNode;
  children: React.ReactNode;
  emptyHint: string;
  showRunners?: boolean;
  runners?: RunnerAsset[];
  onRefresh?: () => Promise<unknown>;
  locale: Locale;
}) {
  const isLegacyWorkflowSection = title === text[locale].flows;
  return (
    <>
      {showRunners && runners && onRefresh && (
        <RunnerCatalog locale={locale} items={runners} onRefresh={onRefresh} />
      )}{" "}
      {!isLegacyWorkflowSection && (
        <section className="panel app-settings">
          <div className="panel-title-action">
            <PanelHeader
              title={<SectionInfo title={title} description={emptyHint} />}
            />
            {button}
          </div>
          <div className="catalog-list">
            {Children.count(children) ? (
              children
            ) : (
              <p className="catalog-empty">{emptyHint}</p>
            )}
          </div>
        </section>
      )}
    </>
  );
}
function FieldLabel({
  label,
  description,
}: {
  label: string;
  description: string;
}) {
  return <SectionInfo title={label} description={description} />;
}

function PipelineYamlEditor({
  value,
  onChange,
  hint,
}: {
  value: string;
  onChange: (value: string) => void;
  hint: string;
}) {
  return (
    <div className="pipeline-yaml-editor">
      <p className="hint">{hint}</p>
      <YamlEditor value={value} onChange={onChange} />
    </div>
  );
}

function WorkflowModal({
  onClose,
  flows,
  onCreate,
  onUpdate,
  editing,
  l,
}: {
  onClose: () => void;
  flows: Workflow[];
  onCreate: (values: unknown) => Promise<unknown>;
  onUpdate: (id: string, values: unknown) => Promise<unknown>;
  editing: Workflow | null;
  l: Record<string, string>;
}) {
  const [page, setPage] = useState(1),
    [draft, setDraft] = useState(() =>
      editing
        ? {
            id: editing.id,
            name: editing.name,
            description: editing.description,
            template_workflow_id: "",
          }
        : { id: "", name: "", description: "", template_workflow_id: "" },
    ),
    [workflowYaml, setWorkflowYaml] = useState(() => pipelineYaml(editing)),
    [notice, setNotice] = useState("");
  const chooseTemplate = (id: string) => {
    setDraft({ ...draft, template_workflow_id: id });
    setWorkflowYaml(pipelineYaml(flows.find((item) => item.id === id)));
  };
  const save = () => {
    const values = {
      ...draft,
      template_workflow_id: draft.template_workflow_id || editing?.id || "",
      workflow_yaml: workflowYaml,
    };
    (editing ? onUpdate(editing.id, values) : onCreate(values))
      .then(onClose)
      .catch((error) => setNotice(error.message));
  };
  return (
    <Modal open title={editing ? l.flows : l.addFlow} onClose={onClose}>
      <div className="build-wizard workflow-editor">
        <ol className="wizard-steps">
          <li className={page === 1 ? "current" : "done"}>
            <button type="button" onClick={() => setPage(1)}>
              1. {l.basic}
            </button>
          </li>
          <li className={page === 2 ? "current" : ""}>
            <button type="button" onClick={() => setPage(2)}>
              2. {l.steps}
            </button>
          </li>
        </ol>
        {page === 1 ? (
          <div className="modal-form">
            <label className="modal-setting-row">
              <span>{l.id}</span>
              <input
                disabled={Boolean(editing)}
                value={draft.id}
                onChange={(event) =>
                  setDraft({ ...draft, id: event.target.value })
                }
              />
            </label>
            <label className="modal-setting-row">
              <span>{l.name}</span>
              <input
                value={draft.name}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.target.value })
                }
              />
            </label>
            <label className="modal-setting-row">
              <span>{l.description}</span>
              <textarea
                rows={3}
                value={draft.description}
                onChange={(event) =>
                  setDraft({ ...draft, description: event.target.value })
                }
              />
            </label>
            <label className="modal-setting-row">
              <span>{l.template}</span>
              <select
                value={draft.template_workflow_id}
                onChange={(event) => chooseTemplate(event.target.value)}
              >
                <option value="">{l.selectTemplate}</option>
                {flows.map((flow, index) => (
                  <option key={`${flow.id}-${index}`} value={flow.id}>
                    {flow.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : (
          <PipelineYamlEditor
            value={workflowYaml}
            onChange={setWorkflowYaml}
            hint={l.pipelineHint}
          />
        )}
        <div className="modal-actions">
          {notice && <small className="hint">{notice}</small>}
          {page === 2 && (
            <button className="ghost" onClick={() => setPage(1)}>
              <ChevronLeft size={15} />
              {l.back}
            </button>
          )}
          {page === 1 ? (
            <button className="approve" onClick={() => setPage(2)}>
              {l.next}
              <ChevronRight size={15} />
            </button>
          ) : (
            <button className="approve" onClick={save}>
              {l.save}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}

function RunnerModal({
  locale,
  editing,
  onClose,
  onSaved,
}: {
  locale: Locale;
  editing: RunnerAsset | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const copy = runnerLabels[locale];
  const [templates, setTemplates] = useState<RunnerTemplate[]>([]),
    [draft, setDraft] = useState<RunnerAsset | undefined>(editing ?? undefined),
    [notice, setNotice] = useState("");
  const importInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!editing)
      api<RunnerTemplate[]>("/api/runner-templates")
        .then(setTemplates)
        .catch((error) => setNotice(error.message));
  }, [editing]);
  const choose = (template: RunnerTemplate) =>
    setDraft({
      id: "",
      name: template.name,
      description: template.description,
      template_id: template.id,
      source: template.source,
    });
  const changeTemplate = () => {
    setDraft(undefined);
    setNotice("");
  };
  const importTemplate = async (file: File | undefined) => {
    if (!file) return;
    try {
      const values = JSON.parse(await file.text()) as RunnerTemplate;
      const imported = await api<RunnerTemplate>(
        "/api/runner-templates/import",
        "POST",
        values,
      );
      setTemplates((current) => [
        ...current.filter((template) => template.id !== imported.id),
        imported,
      ]);
      setNotice(`${copy.imported} ${imported.name}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : copy.importFailed);
    } finally {
      if (importInput.current) importInput.current.value = "";
    }
  };
  const save = (openInVsCode = false) => {
    if (!draft) return;
    const runnerId = editing?.id ?? draft.id;
    api(
      editing ? `/api/runners/${editing.id}` : "/api/runners",
      editing ? "PUT" : "POST",
      editing
        ? {
            name: draft.name,
            description: draft.description,
            source: draft.source,
          }
        : draft,
    )
      .then(async () => {
        onSaved();
        if (openInVsCode)
          await api(`/api/runners/${runnerId}/open-vscode`, "POST");
        onClose();
      })
      .catch((error) => setNotice(error.message));
  };
  const translations = useTemplateTranslations<{
      name: string;
      description: string;
    }>(
      "runner-template",
      templates.map((template) => template.id),
      locale,
    ),
    translationCopy = locales[locale].templateTranslation;
  if (!draft)
    return (
      <Modal open title={copy.createTitle} onClose={onClose}>
        <div className="runner-template-picker">
          <div className="runner-template-picker__head">
            <p className="hint">{copy.chooseHint}</p>
            <div className="template-picker-actions">
              <input
                ref={importInput}
                className="visually-hidden"
                type="file"
                accept="application/json,.json"
                onChange={(event) => importTemplate(event.target.files?.[0])}
              />
              <button
                className="ghost"
                type="button"
                disabled={translations.loading}
                onClick={
                  translations.content(templates[0]?.id ?? "")
                    ? () => translations.showOriginal()
                    : () => translations.translate()
                }
              >
                <Languages size={15} />
                {translations.loading
                  ? translationCopy.translating
                  : translations.content(templates[0]?.id ?? "")
                    ? translationCopy.showOriginal
                    : translationCopy.translate}
              </button>
              <button
                className="ghost"
                type="button"
                onClick={() => importInput.current?.click()}
              >
                <FileUp size={15} />
                {copy.importTemplate}
              </button>
            </div>
          </div>
          <div className="runner-template-grid">
            {templates.map((template) => (
              <RunnerTemplateCard
                key={template.id}
                template={template}
                translation={translations.content(template.id)}
                choose={choose}
              />
            ))}
          </div>
          {translations.error && (
            <small className="hint">{translationCopy.failed}</small>
          )}
        </div>
        {notice && <small className="hint">{notice}</small>}
      </Modal>
    );
  const selectedTemplate = templates.find(
    (template) => template.id === draft.template_id,
  );
  return (
    <Modal
      open
      title={editing ? copy.editTitle : copy.configureTitle}
      onClose={onClose}
    >
      <div className="modal-form runner-editor">
        {!editing && (
          <div className="runner-template-selection">
            <div>
              <small>{copy.basedOn}</small>
              <strong>{selectedTemplate?.name ?? draft.template_id}</strong>
              <span>{selectedTemplate?.description}</span>
            </div>
            <button className="ghost" type="button" onClick={changeTemplate}>
              {copy.changeTemplate}
            </button>
          </div>
        )}
        <label className="modal-setting-row">
          <FieldLabel label={copy.id} description={fieldHelp[locale].id} />
          <input
            disabled={Boolean(editing)}
            value={draft.id}
            onChange={(event) => setDraft({ ...draft, id: event.target.value })}
          />
        </label>
        <label className="modal-setting-row">
          <FieldLabel label={copy.name} description={fieldHelp[locale].name} />
          <input
            value={draft.name}
            onChange={(event) =>
              setDraft({ ...draft, name: event.target.value })
            }
          />
        </label>
        <label className="modal-setting-row">
          <FieldLabel
            label={copy.description}
            description={fieldHelp[locale].description}
          />
          <textarea
            value={draft.description}
            onChange={(event) =>
              setDraft({ ...draft, description: event.target.value })
            }
          />
        </label>
        <label className="runner-source">
          <FieldLabel
            label={copy.source}
            description={fieldHelp[locale].source}
          />
          <PythonEditor
            ariaLabel={copy.source}
            value={draft.source}
            onChange={(source) => setDraft({ ...draft, source })}
          />
        </label>
        <div className="modal-actions">
          {notice && <small className="hint">{notice}</small>}
          <button className="ghost" type="button" onClick={() => save(true)}>
            {copy.saveAndOpen}
          </button>
          <button className="approve" onClick={() => save()}>
            {copy.save}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function RunnerTemplateCard({
  template,
  translation,
  choose,
}: {
  template: RunnerTemplate;
  translation: { name: string; description: string } | null;
  choose: (template: RunnerTemplate) => void;
}) {
  const display = translation ?? template;
  return (
    <article className="runner-template-card">
      <button
        className="runner-template-card__select"
        onClick={() => choose(template)}
      >
        <strong>{display.name}</strong>
        <span>{display.description}</span>
        <small>{template.id}</small>
      </button>
    </article>
  );
}

function AssetRow({
  name,
  detail,
  onClick,
  onDelete,
  deleteLabel = "Delete",
}: {
  name: string;
  detail: string;
  onClick: () => void;
  onDelete: () => void;
  deleteLabel?: string;
}) {
  return (
    <div className="catalog-row-wrap">
      <button className="catalog-row" onClick={onClick}>
        <strong>{name}</strong>
        <span>{detail}</span>
      </button>
      <button
        className="icon-button danger"
        aria-label={deleteLabel}
        onClick={onDelete}
      >
        <Trash2 size={15} />
      </button>
    </div>
  );
}
const blankProfile: Settings = {
  profile_name: "",
  provider: "azure-openai",
  model: "",
  endpoint: "",
  region: "us-east-1",
  secret_env: "AZURE_OPENAI_API_KEY",
  aws_profile: "",
};
type ProfileCatalogCopy = {
  title: string;
  description: string;
  create: string;
  edit: string;
  empty: string;
  delete: string;
};
function ProfileCatalog({
  locale,
  profiles,
  settings,
  setSettings,
  test,
  save,
  tested,
  onDelete,
}: {
  locale: Locale;
  profiles: Settings[];
  settings: Settings;
  setSettings: (settings: Settings) => void;
  test: () => void;
  save: () => Promise<unknown>;
  tested: boolean;
  onDelete: (id: string) => void;
}) {
  const copy = localeMessages<{
      profiles: ProfileCatalogCopy;
      profileForm: ProfileFormCopy;
    }>(locale, "settingsPage"),
    [open, setOpen] = useState(false);
  const saveProfile = () => save().then(() => setOpen(false));
  return (
    <section className="panel app-settings">
      <div className="panel-title-action">
        <PanelHeader
          title={
            <SectionInfo
              title={copy.profiles.title}
              description={copy.profiles.description}
            />
          }
        />
        <button
          className="approve"
          onClick={() => {
            setSettings(blankProfile);
            setOpen(true);
          }}
        >
          <Plus size={14} />
          {copy.profiles.create}
        </button>
      </div>
      <div className="catalog-list">
        {profiles.length ? (
          profiles.map((profile) => (
            <AssetRow
              key={profile.profile_name}
              name={profile.profile_name}
              detail={`${profile.provider} · ${profile.model || "—"}`}
              onClick={() => {
                setSettings(profile);
                setOpen(true);
              }}
              onDelete={() => onDelete(profile.profile_name)}
              deleteLabel={`${copy.profiles.delete} ${profile.profile_name}`}
            />
          ))
        ) : (
          <p className="catalog-empty">{copy.profiles.empty}</p>
        )}
      </div>
      <Modal
        open={open}
        title={
          settings.profile_name ? copy.profiles.edit : copy.profiles.create
        }
        onClose={() => setOpen(false)}
      >
        <ProfileForm
          settings={settings}
          setSettings={setSettings}
          test={test}
          save={saveProfile}
          tested={tested}
          onClose={() => setOpen(false)}
          t={locales[locale].evaluation}
          help={copy.profileForm}
        />
      </Modal>
    </section>
  );
}
function RunnerCatalog({
  locale,
  items,
  onRefresh,
}: {
  locale: Locale;
  items: RunnerAsset[];
  onRefresh: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false),
    [editing, setEditing] = useState<RunnerAsset | null>(null);
  const copy = runnerLabels[locale];
  const remove = (id: string) =>
    api(`/api/runners/${id}`, "DELETE").then(onRefresh);
  return (
    <section className="panel app-settings">
      <div className="panel-title-action">
        <PanelHeader
          title={
            <SectionInfo
              title={copy.title}
              description={text[locale].emptyRunners}
            />
          }
        />
        <button
          className="approve"
          onClick={() => {
            setEditing(null);
            setOpen(true);
          }}
        >
          <Plus size={14} />
          {copy.create}
        </button>
      </div>
      <div className="catalog-list">
        {items.length ? (
          items.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.description}`}
              onClick={() => {
                setEditing(item);
                setOpen(true);
              }}
              onDelete={() => remove(item.id)}
              deleteLabel={copy.delete}
            />
          ))
        ) : (
          <p className="catalog-empty">{text[locale].emptyRunners}</p>
        )}
      </div>
      {open && (
        <RunnerModal
          locale={locale}
          editing={editing}
          onClose={() => setOpen(false)}
          onSaved={onRefresh}
        />
      )}
    </section>
  );
}

function PromptTemplateEditor({
  template,
  onClose,
  onSaved,
  l,
  help,
}: {
  template: PromptTemplate;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
  l: Record<string, string>;
  help: Record<string, string>;
}) {
  const draftKey = `orbit.prompt-template-draft.${template.id}`,
    versions = template.versions?.length
      ? template.versions
      : [{ version: template.version, content: template.content }];
  const [draft, setDraft] = useState(() => {
      const saved = localStorage.getItem(draftKey);
      return saved ? (JSON.parse(saved) as PromptTemplate) : { ...template };
    }),
    [selectedVersion, setSelectedVersion] = useState(template.version),
    [notice, setNotice] = useState("");
  const dirty =
    draft.name !== template.name ||
    draft.content !== template.content ||
    draft.id !== template.id;
  useEffect(() => {
    if (dirty) localStorage.setItem(draftKey, JSON.stringify(draft));
    else localStorage.removeItem(draftKey);
  }, [draft, dirty, draftKey]);
  const close = () => {
    if (
      !dirty ||
      window.confirm("저장하지 않은 수정 내용이 있습니다. 닫을까요?")
    )
      onClose();
  };
  const selectVersion = (version: number) => {
    if (
      dirty &&
      !window.confirm(
        "저장하지 않은 수정 내용이 있습니다. 선택한 버전으로 전환할까요?",
      )
    )
      return;
    const selected = versions.find((item) => item.version === version);
    if (selected) {
      setSelectedVersion(version);
      setDraft({ ...template, content: selected.content, version });
      localStorage.removeItem(draftKey);
    }
  };
  const save = () =>
    api<PromptTemplate>(
      template.id === draft.id
        ? `/api/prompt-templates/${template.id}`
        : "/api/prompt-templates",
      template.id === draft.id ? "PUT" : "POST",
      { id: draft.id, name: draft.name, content: draft.content },
    )
      .then(async () => {
        localStorage.removeItem(draftKey);
        await onSaved();
        onClose();
      })
      .catch((error) => setNotice(error.message));
  return (
    <Modal open title={l.addTemplate} onClose={close}>
      <div className="modal-form">
        <label className="modal-setting-row">
          <FieldLabel label={l.id} description={help.id} />
          <input
            disabled={template.version > 0}
            value={draft.id}
            onChange={(event) => setDraft({ ...draft, id: event.target.value })}
          />
        </label>
        <label className="modal-setting-row">
          <FieldLabel label={l.name} description={help.name} />
          <input
            value={draft.name}
            onChange={(event) =>
              setDraft({ ...draft, name: event.target.value })
            }
          />
        </label>
        <label className="modal-setting-row">
          <FieldLabel label={l.version} description={help.version} />
          <select
            value={selectedVersion}
            onChange={(event) => selectVersion(Number(event.target.value))}
          >
            {[...versions]
              .sort((a, b) => b.version - a.version)
              .map((item) => (
                <option key={item.version} value={item.version}>
                  v{item.version}
                </option>
              ))}
          </select>
        </label>
        <label className="modal-setting-row">
          <FieldLabel label={l.body} description={help.content} />
          <textarea
            rows={14}
            value={draft.content}
            onChange={(event) =>
              setDraft({ ...draft, content: event.target.value })
            }
          />
        </label>
        {dirty && (
          <small className="hint">
            수정 중인 내용이 저장되어 있습니다. 저장하면 새 버전이 생성됩니다.
          </small>
        )}
        <div className="modal-actions">
          {notice && <small className="hint">{notice}</small>}
          <button className="approve" onClick={save}>
            {l.save}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function LegacyAssetsPage({
  locale,
  workflows,
  runners,
  promptTemplates,
  testCaseSets,
  onRefresh,
  onCreateWorkflow,
  onUpdateWorkflow,
  onDelete,
}: {
  locale: Locale;
  workflows: Workflow[];
  runners: RunnerAsset[];
  promptTemplates: PromptTemplate[];
  testCaseSets: TargetTestCaseSet[];
  onRefresh: () => Promise<unknown>;
  onCreateWorkflow: (values: unknown) => Promise<unknown>;
  onUpdateWorkflow: (id: string, values: unknown) => Promise<unknown>;
  onDelete: (kind: "template" | "test-set" | "workflow", id: string) => void;
}) {
  const createLabel = locales[locale].ui.create,
    l: Record<string, string> = {
      ...text[locale],
      addTemplate: createLabel,
      addTests: createLabel,
      addFlow: createLabel,
    };
  const help = fieldHelp[locale];
  const [flowOpen, setFlowOpen] = useState(false),
    [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null),
    [template, setTemplate] = useState<PromptTemplate | null>(null),
    [testSet, setTestSet] = useState<TargetTestCaseSet | null>(null),
    [notice, setNotice] = useState("");
  const saveSet = () => {
    if (!testSet) return;
    const existing = testCaseSets.some((item) => item.id === testSet.id);
    api<TargetTestCaseSet>(
      existing
        ? `/api/target-test-case-sets/${testSet.id}`
        : "/api/target-test-case-sets",
      existing ? "PUT" : "POST",
      testSet,
    )
      .then(() => {
        setTestSet(null);
        onRefresh();
      })
      .catch((error) => setNotice(error.message));
  };
  const updateCase = (index: number, values: Partial<TestCase>) =>
    setTestSet((current) =>
      current
        ? {
            ...current,
            cases: current.cases.map((item, i) =>
              i === index ? { ...item, ...values } : item,
            ),
          }
        : current,
    );
  return (
    <>
      <Catalog
        locale={locale}
        emptyHint={l.emptyTemplates}
        title={l.templates}
        button={
          <button
            className="approve"
            onClick={() =>
              setTemplate({
                id: `manager-template-${Date.now()}`,
                name: "",
                version: 1,
                content: "",
              })
            }
          >
            <Plus size={14} />
            {l.addTemplate}
          </button>
        }
      >
        {promptTemplates.map((item) => (
          <AssetRow
            key={item.id}
            name={item.name}
            detail={`${item.id} · v${item.version}`}
            onClick={() => setTemplate(item)}
            onDelete={() => onDelete("template", item.id)}
          />
        ))}
      </Catalog>
      <Catalog
        locale={locale}
        emptyHint={l.emptyTests}
        title={l.tests}
        button={
          <button className="approve" onClick={() => setTestSet(testBlank)}>
            <Plus size={14} />
            {l.addTests}
          </button>
        }
      >
        {testCaseSets.map((item) => (
          <AssetRow
            key={item.id}
            name={item.name}
            detail={`${item.id} · ${item.cases.length}`}
            onClick={() => setTestSet(item)}
            onDelete={() => onDelete("test-set", item.id)}
          />
        ))}
      </Catalog>
      <Catalog
        locale={locale}
        showRunners
        runners={runners}
        onRefresh={onRefresh}
        emptyHint={l.emptyFlows}
        title={l.flows}
        button={
          <button
            className="approve"
            onClick={() => {
              setEditingWorkflow(null);
              setFlowOpen(true);
            }}
          >
            <Plus size={14} />
            {l.addFlow}
          </button>
        }
      >
        {workflows.map((item, index) => (
          <AssetRow
            key={`${item.id}-${index}`}
            name={item.name}
            detail={`${item.id} · ${item.description}`}
            onClick={() => {
              setEditingWorkflow(item);
              setFlowOpen(true);
            }}
            onDelete={() => onDelete("workflow", item.id)}
          />
        ))}
      </Catalog>
      {template && (
        <PromptTemplateEditor
          template={template}
          onClose={() => setTemplate(null)}
          onSaved={onRefresh}
          l={l}
          help={help}
        />
      )}
      <Modal
        open={testSet !== null}
        title={l.addTests}
        onClose={() => setTestSet(null)}
      >
        {testSet && (
          <div className="modal-form">
            <label className="modal-setting-row">
              <FieldLabel label={l.id} description={help.id} />
              <input
                value={testSet.id}
                onChange={(event) =>
                  setTestSet({ ...testSet, id: event.target.value })
                }
              />
            </label>
            <label className="modal-setting-row">
              <FieldLabel label={l.name} description={help.name} />
              <input
                value={testSet.name}
                onChange={(event) =>
                  setTestSet({ ...testSet, name: event.target.value })
                }
              />
            </label>
            <label className="modal-setting-row">
              <FieldLabel
                label={l.description}
                description={help.description}
              />
              <textarea
                value={testSet.description}
                onChange={(event) =>
                  setTestSet({ ...testSet, description: event.target.value })
                }
              />
            </label>
            <div className="test-case-editor">
              <div>
                <FieldLabel label={l.cases} description={help.cases} />
                <button
                  className="ghost"
                  onClick={() =>
                    setTestSet({
                      ...testSet,
                      cases: [
                        ...testSet.cases,
                        {
                          id: `case-${testSet.cases.length + 1}`,
                          name: "",
                          prompt: "",
                          acceptance: "",
                        },
                      ],
                    })
                  }
                >
                  <Plus size={14} />
                  {l.addCase}
                </button>
              </div>
              {testSet.cases.map((item, index) => (
                <fieldset key={index}>
                  <label>
                    <FieldLabel label={l.id} description={help.id} />
                    <input
                      value={item.id}
                      onChange={(event) =>
                        updateCase(index, { id: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    <FieldLabel label={l.name} description={help.name} />
                    <input
                      value={item.name}
                      onChange={(event) =>
                        updateCase(index, { name: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    <FieldLabel label={l.prompt} description={help.prompt} />
                    <textarea
                      value={item.prompt}
                      onChange={(event) =>
                        updateCase(index, { prompt: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    <FieldLabel
                      label={l.acceptance}
                      description={help.acceptance}
                    />
                    <textarea
                      value={item.acceptance}
                      onChange={(event) =>
                        updateCase(index, { acceptance: event.target.value })
                      }
                    />
                  </label>
                  <button
                    className="ghost danger"
                    disabled={testSet.cases.length === 1}
                    onClick={() =>
                      setTestSet({
                        ...testSet,
                        cases: testSet.cases.filter((_, i) => i !== index),
                      })
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                </fieldset>
              ))}
            </div>
            <div className="modal-actions">
              <small>{notice}</small>
              <button className="approve" onClick={saveSet}>
                {l.save}
              </button>
            </div>
          </div>
        )}
      </Modal>
      {flowOpen && (
        <WorkflowModal
          key={editingWorkflow?.id ?? "new"}
          onClose={() => {
            setFlowOpen(false);
            setEditingWorkflow(null);
          }}
          flows={workflows}
          onCreate={onCreateWorkflow}
          onUpdate={onUpdateWorkflow}
          editing={editingWorkflow}
          l={l}
        />
      )}
    </>
  );
}

type EnvironmentProps = {
  executionEnvironments: ExecutionEnvironment[];
  targetEnvironments: TargetEnvironment[];
  onRefresh: () => Promise<unknown>;
  onDelete: (
    kind: "execution-environment" | "target-environment",
    id: string,
  ) => void;
};
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- retained while existing asset editor is migrated.
function EnvironmentAssets({
  executionEnvironments,
  targetEnvironments,
  onRefresh,
  onDelete,
}: EnvironmentProps) {
  const { pushToast } = useToast();
  const [kind, setKind] = useState<"execution" | "target" | null>(null),
    [execution, setExecution] = useState<any>(null),
    [target, setTarget] = useState<any>(null);
  const field = (
    label: string,
    value: string,
    onChange: (value: string) => void,
  ) => (
    <label className="modal-setting-row">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
  const save = async () => {
    try {
      if (kind === "execution" && execution) {
        const exists = executionEnvironments.some(
          (item) => item.id === execution.id,
        );
        await api(
          exists
            ? `/api/execution-environments/${execution.id}`
            : "/api/execution-environments",
          exists ? "PUT" : "POST",
          execution,
        );
      }
      if (kind === "target" && target) {
        const exists = targetEnvironments.some((item) => item.id === target.id);
        await api(
          exists
            ? `/api/target-environments/${target.id}`
            : "/api/target-environments",
          exists ? "PUT" : "POST",
          target,
        );
      }
      setKind(null);
      await onRefresh();
      pushToast("Asset saved", "success");
    } catch (error) {
      pushToast(error instanceof Error ? error.message : "Asset save failed");
    }
  };
  return (
    <>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <PanelHeader title="Execution environments" />
          <button
            className="approve"
            onClick={() => {
              setExecution({
                id: `execution-${Date.now()}`,
                name: "",
                executor_type: "local",
                remote_endpoint: "",
                remote_method: "POST",
                remote_timeout_seconds: 60,
                remote_headers: {},
                browser_executable_path: "",
                browser_library_path: "",
              });
              setKind("execution");
            }}
          >
            <Plus size={14} />
            Create
          </button>
        </div>
        <p className="hint">
          Reusable runner location, invocation method, and browser runtime.
        </p>
        <div className="catalog-list">
          {executionEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.executor.type}`}
              onClick={() => {
                setExecution({
                  id: item.id,
                  name: item.name,
                  executor_type: item.executor.type,
                  remote_endpoint: item.executor.endpoint ?? "",
                  remote_method: item.executor.method ?? "POST",
                  remote_timeout_seconds: item.executor.timeout_seconds ?? 60,
                  remote_headers: item.executor.headers ?? {},
                  browser_executable_path: item.browser_executable_path ?? "",
                  browser_library_path: item.browser_library_path ?? "",
                });
                setKind("execution");
              }}
              onDelete={() => onDelete("execution-environment", item.id)}
            />
          ))}
        </div>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <PanelHeader title="Target environments" />
          <button
            className="approve"
            onClick={() => {
              setTarget({
                id: `target-${Date.now()}`,
                name: "",
                repository: "",
                browser_base_url: "",
                managed_prompt_path: "",
              });
              setKind("target");
            }}
          >
            <Plus size={14} />
            Create
          </button>
        </div>
        <p className="hint">
          Reusable repository, browser URL, and native runner prompt-file
          target.
        </p>
        <div className="catalog-list">
          {targetEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.repository}`}
              onClick={() => {
                setTarget({
                  id: item.id,
                  name: item.name,
                  repository: item.repository,
                  browser_base_url: item.browser_base_url ?? "",
                  managed_prompt_path: item.managed_prompt_path ?? "",
                });
                setKind("target");
              }}
              onDelete={() => onDelete("target-environment", item.id)}
            />
          ))}
        </div>
      </section>
      <Modal
        open={kind === "execution"}
        title="Execution environment"
        onClose={() => setKind(null)}
      >
        {execution && (
          <div className="modal-form">
            {field("ID", execution.id, (value) =>
              setExecution({ ...execution, id: value }),
            )}
            {field("Name", execution.name, (value) =>
              setExecution({ ...execution, name: value }),
            )}
            <label className="modal-setting-row">
              <span>Executor</span>
              <select
                value={execution.executor_type}
                onChange={(event) =>
                  setExecution({
                    ...execution,
                    executor_type: event.target.value,
                  })
                }
              >
                <option value="local">Local</option>
                <option value="remote-http">Remote HTTP</option>
              </select>
            </label>
            {execution.executor_type === "remote-http" &&
              field("Endpoint", execution.remote_endpoint, (value) =>
                setExecution({ ...execution, remote_endpoint: value }),
              )}
            {field(
              "Browser executable (optional)",
              execution.browser_executable_path,
              (value) =>
                setExecution({ ...execution, browser_executable_path: value }),
            )}
            {field(
              "Browser library path (optional)",
              execution.browser_library_path,
              (value) =>
                setExecution({ ...execution, browser_library_path: value }),
            )}
            <div className="modal-actions">
              <button className="approve" onClick={save}>
                Save
              </button>
            </div>
          </div>
        )}
      </Modal>
      <Modal
        open={kind === "target"}
        title="Target environment"
        onClose={() => setKind(null)}
      >
        {target && (
          <div className="modal-form">
            {field("ID", target.id, (value) =>
              setTarget({ ...target, id: value }),
            )}
            {field("Name", target.name, (value) =>
              setTarget({ ...target, name: value }),
            )}
            {field("Repository", target.repository, (value) =>
              setTarget({ ...target, repository: value }),
            )}
            {field("Browser base URL", target.browser_base_url, (value) =>
              setTarget({ ...target, browser_base_url: value }),
            )}
            {field(
              "Managed prompt file (native runner only)",
              target.managed_prompt_path,
              (value) => setTarget({ ...target, managed_prompt_path: value }),
            )}
            <div className="modal-actions">
              <button className="approve" onClick={save}>
                Save
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

type EnvironmentDraft = {
  id: string;
  name: string;
  executor_type: "local" | "remote-http";
  remote_endpoint: string;
  remote_method: "GET" | "POST" | "PUT";
  remote_timeout_seconds: number;
  remote_headers: Record<string, string>;
  browser_executable_path: string;
  browser_library_path: string;
  environment_variables: Record<string, string>;
};
type TargetDraft = {
  id: string;
  name: string;
  repository: string;
  browser_base_url: string;
  managed_prompt_path: string;
};
const environmentText =
  localeMessageMap<Record<string, string>>("environmentText");
function EnvironmentCatalog({
  locale,
  executionEnvironments,
  targetEnvironments,
  onRefresh,
  onDelete,
}: {
  locale: Locale;
  executionEnvironments: ExecutionEnvironment[];
  targetEnvironments: TargetEnvironment[];
  onRefresh: () => Promise<unknown>;
  onDelete: (
    kind: "execution-environment" | "target-environment",
    id: string,
  ) => void;
}) {
  const t = environmentText[locale],
    { pushToast } = useToast();
  const [kind, setKind] = useState<"execution" | "target" | null>(null);
  const [execution, setExecution] = useState<EnvironmentDraft | null>(null);
  const [target, setTarget] = useState<TargetDraft | null>(null);
  const field = (
    label: string,
    description: string,
    value: string,
    onChange: (value: string) => void,
  ) => (
    <label className="modal-setting-row">
      <FieldLabel label={label} description={description} />
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
  const save = async () => {
    try {
      if (kind === "execution" && execution) {
        const exists = executionEnvironments.some(
          (item) => item.id === execution.id,
        );
        await api(
          exists
            ? `/api/execution-environments/${execution.id}`
            : "/api/execution-environments",
          exists ? "PUT" : "POST",
          execution,
        );
      }
      if (kind === "target" && target) {
        const exists = targetEnvironments.some((item) => item.id === target.id);
        await api(
          exists
            ? `/api/target-environments/${target.id}`
            : "/api/target-environments",
          exists ? "PUT" : "POST",
          target,
        );
      }
      setKind(null);
      await onRefresh();
      pushToast("Asset saved", "success");
    } catch (error) {
      pushToast(error instanceof Error ? error.message : "Asset save failed");
    }
  };
  const help = fieldHelp[locale];
  return (
    <>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <PanelHeader
            title={
              <SectionInfo title={t.execution} description={t.executionHint} />
            }
          />
          <button
            className="approve"
            onClick={() => {
              setExecution({
                id: `execution-${Date.now()}`,
                name: "",
                executor_type: "local",
                remote_endpoint: "",
                remote_method: "POST",
                remote_timeout_seconds: 60,
                remote_headers: {},
                browser_executable_path: "",
                browser_library_path: "",
                environment_variables: {},
              });
              setKind("execution");
            }}
          >
            <Plus size={14} />
            {t.create}
          </button>
        </div>
        <div className="catalog-list">
          {executionEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.executor.type}`}
              onClick={() => {
                setExecution({
                  id: item.id,
                  name: item.name,
                  executor_type: item.executor.type,
                  remote_endpoint: item.executor.endpoint ?? "",
                  remote_method: item.executor.method ?? "POST",
                  remote_timeout_seconds: item.executor.timeout_seconds ?? 60,
                  remote_headers: item.executor.headers ?? {},
                  browser_executable_path: item.browser_executable_path ?? "",
                  browser_library_path: item.browser_library_path ?? "",
                  environment_variables: item.environment_variables ?? {},
                });
                setKind("execution");
              }}
              onDelete={() => onDelete("execution-environment", item.id)}
            />
          ))}
        </div>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <PanelHeader
            title={<SectionInfo title={t.target} description={t.targetHint} />}
          />
          <button
            className="approve"
            onClick={() => {
              setTarget({
                id: `target-${Date.now()}`,
                name: "",
                repository: "",
                browser_base_url: "",
                managed_prompt_path: "",
              });
              setKind("target");
            }}
          >
            <Plus size={14} />
            {t.create}
          </button>
        </div>
        <div className="catalog-list">
          {targetEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.repository}`}
              onClick={() => {
                setTarget({
                  id: item.id,
                  name: item.name,
                  repository: item.repository,
                  browser_base_url: item.browser_base_url ?? "",
                  managed_prompt_path: item.managed_prompt_path ?? "",
                });
                setKind("target");
              }}
              onDelete={() => onDelete("target-environment", item.id)}
            />
          ))}
        </div>
      </section>
      <Modal
        open={kind === "execution"}
        title={t.execution}
        onClose={() => setKind(null)}
      >
        {execution && (
          <div className="modal-form">
            {field(t.id, help.id, execution.id, (value) =>
              setExecution({ ...execution, id: value }),
            )}
            {field(t.name, help.name, execution.name, (value) =>
              setExecution({ ...execution, name: value }),
            )}
            <label className="modal-setting-row">
              <FieldLabel label={t.executor} description={help.executor} />
              <select
                value={execution.executor_type}
                onChange={(event) =>
                  setExecution({
                    ...execution,
                    executor_type: event.target
                      .value as EnvironmentDraft["executor_type"],
                  })
                }
              >
                <option value="local">Local</option>
                <option value="remote-http">Remote HTTP</option>
              </select>
            </label>
            {execution.executor_type === "remote-http" &&
              field(
                t.endpoint,
                help.endpoint,
                execution.remote_endpoint,
                (value) =>
                  setExecution({ ...execution, remote_endpoint: value }),
              )}
            {field(
              t.executable,
              help.executable,
              execution.browser_executable_path,
              (value) =>
                setExecution({ ...execution, browser_executable_path: value }),
            )}
            {field(
              t.library,
              help.library,
              execution.browser_library_path,
              (value) =>
                setExecution({ ...execution, browser_library_path: value }),
            )}
            <div className="modal-actions">
              <button className="approve" onClick={save}>
                {t.save}
              </button>
            </div>
          </div>
        )}
      </Modal>
      <Modal
        open={kind === "target"}
        title={t.target}
        onClose={() => setKind(null)}
      >
        {target && (
          <div className="modal-form">
            {field(t.id, help.id, target.id, (value) =>
              setTarget({ ...target, id: value }),
            )}
            {field(t.name, help.name, target.name, (value) =>
              setTarget({ ...target, name: value }),
            )}
            {field(t.repository, help.repository, target.repository, (value) =>
              setTarget({ ...target, repository: value }),
            )}
            {field(
              t.promptPath,
              help.promptPath,
              target.managed_prompt_path,
              (value) => setTarget({ ...target, managed_prompt_path: value }),
            )}
            {field(t.baseUrl, help.baseUrl, target.browser_base_url, (value) =>
              setTarget({ ...target, browser_base_url: value }),
            )}
            <div className="modal-actions">
              <button className="approve" onClick={save}>
                {t.save}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

export function AssetsPage({
  locale,
  executionEnvironments,
  targetEnvironments,
  profiles,
  settings,
  setSettings,
  test,
  save,
  tested,
  onDelete,
  ...legacy
}: {
  locale: Locale;
  workflows: Workflow[];
  runners: RunnerAsset[];
  promptTemplates: PromptTemplate[];
  testCaseSets: TargetTestCaseSet[];
  executionEnvironments: ExecutionEnvironment[];
  targetEnvironments: TargetEnvironment[];
  profiles: Settings[];
  settings: Settings;
  setSettings: (settings: Settings) => void;
  test: () => void;
  save: () => Promise<unknown>;
  tested: boolean;
  onRefresh: () => Promise<unknown>;
  onCreateWorkflow: (values: unknown) => Promise<unknown>;
  onUpdateWorkflow: (id: string, values: unknown) => Promise<unknown>;
  onDelete: (
    kind:
      | "profile"
      | "template"
      | "test-set"
      | "workflow"
      | "execution-environment"
      | "target-environment",
    id: string,
  ) => void;
}) {
  return (
    <>
      <ProfileCatalog
        locale={locale}
        profiles={profiles}
        settings={settings}
        setSettings={setSettings}
        test={test}
        save={save}
        tested={tested}
        onDelete={(id) => onDelete("profile", id)}
      />
      <EnvironmentCatalog
        locale={locale}
        executionEnvironments={executionEnvironments}
        targetEnvironments={targetEnvironments}
        onRefresh={legacy.onRefresh}
        onDelete={onDelete}
      />
      <LegacyAssetsPage {...legacy} locale={locale} onDelete={onDelete} />
    </>
  );
}
