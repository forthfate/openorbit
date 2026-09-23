/* eslint-disable @typescript-eslint/no-explicit-any -- compact environment editor drafts */
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  FileUp,
  Languages,
  Plus,
  Trash2,
} from "lucide-react";
import { Children, isValidElement, useEffect, useMemo, useRef, useState } from "react";
import localeCodes from "locale-codes";
import Select from "react-select";
import TimezoneSelect from "react-timezone-select";
import type {
  Build,
  ExecutionEnvironment,
  PromptTemplate,
  Persona,
  RunnerAsset,
  RunnerTemplate,
  Settings,
  TargetEnvironment,
  TargetTestCaseSet,
  TestCase,
  Workflow,
  WorkflowGraphDefinition,
  WorkflowStep,
  VisualRunnerBlueprint,
} from "../../domain/models";
import { buildAssetUsage, type AssetUsage } from "../../domain/asset-usage";
import {
  localeMessageMap,
  localeMessages,
  locales,
  intlLocales,
  type Locale,
} from "../../locales";
import { Modal } from "../../components/ui/modal";
import { ConfirmDialog } from "../../components/ui/confirm-dialog";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { PythonEditor } from "../../components/ui/python-editor";
import { JsonEditor } from "../../components/ui/json-editor";
import { MarkdownEditor } from "../../components/ui/markdown-editor";
import { WorkflowGraph } from "../../components/workflow-graph";
import { VisualRunnerEditor } from "../../components/visual-runner-editor";
import { YamlEditor } from "../../components/ui/yaml-editor";
import { api, upload } from "../../services/api";
import { useTemplateTranslations } from "../../services/use-template-translation";
import { useToast } from "../../components/ui/toast-context";
import { ProfileForm, type ProfileFormCopy } from "../builds/page";
import { SectionSkeleton } from "../../components/ui/section-skeleton";

const text = localeMessageMap<Record<string, string>>("assetsText");
type AssetTab = "ai" | "test-design" | "run-setup";
const assetTabIds: AssetTab[] = ["ai", "test-design", "run-setup"];
const assetTabFromLocation = (): AssetTab => {
  const value = new URLSearchParams(window.location.search).get("tab");
  return assetTabIds.includes(value as AssetTab) ? (value as AssetTab) : "ai";
};
const testBlank: TargetTestCaseSet = {
  id: "",
  name: "",
  description: "",
  cases: [{ id: "case-1", name: "", prompt: "", acceptance: "" }],
};

const personaLocaleOptions = Array.from(
  new Map(
    localeCodes.all.map((item) => [
      item.tag,
      {
        value: item.tag,
        label: `${item.name}${item.location ? ` (${item.location})` : ""}${item.local && item.local !== item.name ? ` — ${item.local}` : ""}`,
      },
    ]),
  ).values(),
).sort((left, right) => left.label.localeCompare(right.label));

function CatalogSkeleton() {
  return <SectionSkeleton rows={3} />;
}

const fieldHelp = localeMessageMap<Record<string, string>>("assetsHelp");
const runnerLabels = localeMessageMap<Record<string, string>>("runnerLabels");
const phases: WorkflowStep["phase"][] = [
  "before_all",
  "before_each",
  "execute",
  "verify",
  "after_each",
  "after_all",
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

function AssetCatalog({
  children,
  loading = false,
  emptyHint,
  locale = "en",
}: {
  children: React.ReactNode;
  loading?: boolean;
  emptyHint: string;
  locale?: Locale;
}) {
  const [sort, setSort] = useState<{
    key: "name" | "createdAt" | "usageCount";
    direction: "asc" | "desc";
    }>({ key: "createdAt", direction: "desc" }),
    rows = Children.toArray(children).filter(isValidElement).sort((left, right) => {
      const a = String(
        (left.props as { name?: string; detail?: string; createdAt?: string; usageCount?: number })[
          sort.key
        ] ?? "",
      );
      const b = String(
        (right.props as { name?: string; detail?: string; createdAt?: string; usageCount?: number })[
          sort.key
        ] ?? "",
      );
      const value = a.localeCompare(b, undefined, {
        numeric: true,
        sensitivity: "base",
      });
      return sort.direction === "asc" ? value : -value;
    }),
    changeSort = (key: typeof sort.key) =>
      setSort((current) => ({
        key,
        direction:
          current.key === key && current.direction === "asc" ? "desc" : "asc",
      })),
    icon = (key: typeof sort.key) =>
      sort.key !== key
        ? ChevronsUpDown
        : sort.direction === "asc"
          ? ChevronUp
          : ChevronDown;
  return (
    <div className="catalog-list">
      {loading ? <CatalogSkeleton /> : rows.length ? (
        <>
          <div className="catalog-list__header">
            {(["name", "usageCount", "createdAt"] as const).map((key) => {
              const Icon = icon(key);
              return (
                <button key={key} type="button" onClick={() => changeSort(key)}>
                  {key === "createdAt" ? text[locale].columnCreated : key === "usageCount" ? text[locale].columnUsage : text[locale].columnName}
                  <Icon size={13} />
                </button>
              );
            })}
            <span>{text[locale].columnActions}</span>
          </div>
          {rows}
        </>
      ) : (
        <p className="catalog-empty">{emptyHint}</p>
      )}
    </div>
  );
}

function Catalog({
  title,
  tooltip,
  button,
  children,
  emptyHint,
  showRunners = false,
  runners,
  onRefresh,
  onDelete,
  runnerUsage,
  loading = false,
  locale,
}: {
  title: string;
  tooltip: string;
  button: React.ReactNode;
  children: React.ReactNode;
  emptyHint: string;
  showRunners?: boolean;
  runners?: RunnerAsset[];
  onRefresh?: () => Promise<unknown>;
  onDelete?: (kind: "runner", id: string) => void;
  runnerUsage?: AssetUsage["runners"];
  loading?: boolean;
  locale: Locale;
}) {
  const isLegacyWorkflowSection = title === text[locale].flows;
  return (
    <>
      {showRunners && runners && onRefresh && onDelete && runnerUsage && (
        <RunnerCatalog locale={locale} items={runners} onRefresh={onRefresh} loading={loading} onDelete={onDelete} usage={runnerUsage} />
      )}{" "}
      {!isLegacyWorkflowSection && (
        <section className="panel app-settings">
          <div className="panel-title-action">
            <div className="panel-title-action__copy">
              <PanelHeader
                title={<SectionInfo title={title} description={tooltip} />}
              />
              <p className="hint section-description">{emptyHint}</p>
            </div>
            {button}
          </div>
          <AssetCatalog locale={locale} loading={loading} emptyHint={emptyHint}>{children}</AssetCatalog>
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
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  hint: string;
  label: string;
}) {
  return (
    <div className="pipeline-yaml-editor">
      <p className="hint">{hint}</p>
      <YamlEditor value={value} onChange={onChange} label={label} />
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
            label={l.steps}
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
    [selectedVersion, setSelectedVersion] = useState<number | null>(editing?.version ?? null),
    [notice, setNotice] = useState(""),
    [editorTab, setEditorTab] = useState<"code" | "graph">("code"),
    [workflowGraph, setWorkflowGraph] = useState<WorkflowGraphDefinition | null>(null),
    [graphSource, setGraphSource] = useState(""),
    [graphLoading, setGraphLoading] = useState(false),
    [graphError, setGraphError] = useState(""),
    [visualEditorOpen, setVisualEditorOpen] = useState(false),
    [visualBlueprint, setVisualBlueprint] = useState<VisualRunnerBlueprint | undefined>(editing?.visual_blueprint),
    [visualDetached, setVisualDetached] = useState(Boolean(editing && !editing.visual_blueprint));
  const importInput = useRef<HTMLInputElement>(null);
  const draftSource = useRef(draft?.source ?? ""), graphInFlight = useRef<string | null>(null);
  const emptyTemplate: RunnerTemplate = {
    id: "empty",
    name: copy.empty,
    description: copy.emptyDescription,
    source: "from orbit_sdk import graph, runner\n\ngraph.connect(\"initialize-runner\", \"prepare-iteration\")\ngraph.connect(\"prepare-iteration\", \"run-iteration\")\ngraph.connect(\"run-iteration\", \"verify-iteration\")\ngraph.connect(\"verify-iteration\", \"close-iteration\")\ngraph.connect(\"close-iteration\", \"prepare-iteration\", kind=\"loop\", label=\"next iteration\")\ngraph.connect(\"close-iteration\", \"finalize-runner\", kind=\"condition\", label=\"completed\")\n\n\n@graph.step(\"initialize-runner\", title=\"Initialize runner\", phase=\"before_all\", outputs=[\"runner_ready\"])\n@runner.phase(\"before_all\")\ndef before_all(ctx):\n    # TODO: Add one-time setup before the run starts.\n    pass\n\n\n@graph.step(\"prepare-iteration\", title=\"Prepare iteration\", phase=\"before_each\", inputs=[\"runner_ready\"], outputs=[\"iteration_ready\"])\n@runner.phase(\"before_each\")\ndef before_each(ctx):\n    # TODO: Add setup for each iteration.\n    pass\n\n\n@graph.step(\"run-iteration\", title=\"Run iteration\", phase=\"execute\", inputs=[\"iteration_ready\"], outputs=[\"iteration_result\"])\n@runner.phase(\"execute\")\ndef execute(ctx):\n    # TODO: Add the main work for this iteration.\n    pass\n\n\n@graph.step(\"verify-iteration\", title=\"Verify iteration\", phase=\"verify\", inputs=[\"iteration_result\"], outputs=[\"verification\"])\n@runner.phase(\"verify\")\ndef verify(ctx):\n    # TODO: Verify the result of this iteration.\n    pass\n\n\n@graph.step(\"close-iteration\", title=\"Close iteration\", phase=\"after_each\", inputs=[\"verification\"], outputs=[\"iteration_complete\"])\n@runner.phase(\"after_each\")\ndef after_each(ctx):\n    # TODO: Add cleanup for each iteration.\n    pass\n\n\n@graph.step(\"finalize-runner\", title=\"Finalize runner\", phase=\"after_all\", inputs=[\"iteration_complete\"], outputs=[\"final_status\"])\n@runner.phase(\"after_all\")\ndef after_all(ctx):\n    # TODO: Add one-time cleanup after the run ends.\n    pass\n\n\nif __name__ == \"__main__\":\n    runner.main()\n",
  };
  const templateOptions = [emptyTemplate, ...templates];
  useEffect(() => {
    draftSource.current = draft?.source ?? "";
  }, [draft?.source]);
  useEffect(() => {
    if (!editing)
      api<RunnerTemplate[]>("/api/runner-templates")
        .then(setTemplates)
        .catch((error) => setNotice(error.message));
  }, [editing]);
  const choose = (template: RunnerTemplate) => {
    setVisualBlueprint(template.visual_blueprint);
    setVisualDetached(!template.visual_blueprint);
    setDraft({
      id: "",
      name: template.name,
      description: template.description,
      template_id: template.id,
      source: template.source,
      version: 1,
    });
  };
  const changeTemplate = () => {
    setDraft(undefined);
    setVisualBlueprint(undefined);
    setVisualDetached(false);
    setNotice("");
  };
  const refreshWorkflowGraph = (source = draft?.source ?? "") => {
    if (!source || source === graphSource || source === graphInFlight.current) return;
    graphInFlight.current = source;
    setGraphLoading(true);
    setGraphError("");
    api<{ id: string }>("/api/runners/graph-drafts", "POST", { source })
      .then((draft) => api<WorkflowGraphDefinition | null>(`/api/runners/graph-drafts/${encodeURIComponent(draft.id)}/preview`))
      .then((graph) => {
        if (draftSource.current !== source) return;
        setWorkflowGraph(graph);
        setGraphSource(source);
      })
      .catch((error) => {
        if (draftSource.current === source) setGraphError(error.message);
      })
      .finally(() => {
        if (graphInFlight.current === source) {
          graphInFlight.current = null;
          setGraphLoading(false);
        }
      });
  };
  const importTemplate = async (file: File | undefined) => {
    if (!file) return;
    try {
      const imported = await upload<RunnerTemplate>("/api/runner-templates/import-package", file);
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
    const values = editing
      ? {
          name: draft.name,
          description: draft.description,
          source: draft.source,
        }
      : {
          id: draft.id,
          name: draft.name,
          description: draft.description,
          template_id: draft.template_id,
          source: draft.source,
        };
    const visualValues = visualBlueprint ? { ...values, visual_blueprint: visualBlueprint } : values;
    api(
      editing ? `/api/runners/${editing.id}` : "/api/runners",
      editing ? "PUT" : "POST",
      visualValues,
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
    translationCopy = locales[locale].templateTranslation,
    allRunnerTemplatesTranslated =
      templates.length > 0 && templates.every((template) => Boolean(translations.content(template.id)));
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
                accept="application/zip,.zip"
                onChange={(event) => importTemplate(event.target.files?.[0])}
              />
                <button
                  className="ghost"
                  type="button"
                  disabled={translations.loading || translations.cacheLoading}
                onClick={
                    allRunnerTemplatesTranslated
                      ? () => translations.showOriginal()
                      : () => translations.translate()
                }
              >
                <Languages size={15} />
                  {translations.loading
                    ? translationCopy.translating
                    : translations.cacheLoading
                      ? translationCopy.checkingCache
                    : allRunnerTemplatesTranslated
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
            {translations.cacheLoading ? (
              <p className="hint">{translationCopy.checkingCache}</p>
            ) : (
              templateOptions.map((template) => (
                <RunnerTemplateCard
                  key={template.id}
                  template={template}
                  translation={translations.content(template.id)}
                  choose={choose}
                />
              ))
            )}
          </div>
          {translations.error && (
            <small className="hint">{translationCopy.failed}</small>
          )}
        </div>
        {notice && <small className="hint">{notice}</small>}
      </Modal>
    );
  const selectedTemplate = templateOptions.find(
    (template) => template.id === draft.template_id,
  );
  const selectedTemplateDisplay = selectedTemplate
    ? { ...selectedTemplate, ...(translations.content(selectedTemplate.id) ?? {}) }
    : null;
  const versions = editing?.versions ?? [];
  const selectVersion = (version: number) => {
    const selected = versions.find((item) => item.version === version);
    if (!selected) return;
    setSelectedVersion(version);
    setDraft({ ...draft, source: selected.source });
    setVisualBlueprint(selected.visual_blueprint);
    setVisualDetached(!selected.visual_blueprint);
  };
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
              <strong>{selectedTemplateDisplay?.name ?? draft.template_id}</strong>
              <span>{selectedTemplateDisplay?.description}</span>
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
        {editing && (
          <label className="modal-setting-row">
            <FieldLabel label={copy.version} description={copy.versionHint} />
            <div>
              <select value={selectedVersion ?? editing.version} onChange={(event) => selectVersion(Number(event.target.value))}>
                {[...versions].sort((a, b) => b.version - a.version).map((version) => (
                  <option key={version.version} value={version.version}>
                    v{version.version}{version.version === editing.version ? ` (${copy.current})` : ""}
                  </option>
                ))}
              </select>
            </div>
          </label>
        )}
        {!editing && <p className="hint">{copy.initialVersion}</p>}
        <div className="runner-editor-tabs" role="tablist" aria-label={copy.source}>
          <button className={editorTab === "code" ? "selected" : ""} role="tab" aria-selected={editorTab === "code"} type="button" onClick={() => setEditorTab("code")}><SectionInfo title={copy.source} description={fieldHelp[locale].source} /></button>
          <button className={editorTab === "graph" ? "selected" : ""} role="tab" aria-selected={editorTab === "graph"} type="button" onClick={() => { setEditorTab("graph"); refreshWorkflowGraph(); }}>{copy.workflowGraph}</button>
        </div>
        {editorTab === "code" ? <div className="runner-source">
          <div className="runner-source__toolbar">
            {visualBlueprint ? <p className="runner-visual-warning">{copy.visualModeCodeWarning}</p> : visualDetached ? <p className="runner-visual-detached">{copy.visualModeDetached}</p> : null}
            <button className="ghost" type="button" disabled={visualDetached} title={visualDetached ? copy.visualModeDetached : undefined} onClick={() => setVisualEditorOpen(true)}>{copy.editInVisualMode}</button>
          </div>
          <PythonEditor ariaLabel={copy.source} value={draft.source} onChange={(source) => { setDraft({ ...draft, source }); if (visualBlueprint) { setVisualBlueprint(undefined); setVisualDetached(true); } }} onBlur={() => refreshWorkflowGraph()} />
        </div> : <section className="runner-workflow-graph">
          {graphLoading ? <p className="hint">{copy.loadingGraph}</p> : workflowGraph?.nodes.length ? <WorkflowGraph nodes={workflowGraph.nodes} edges={workflowGraph.edges} /> : <p className="hint">{graphError || copy.noWorkflowGraph}</p>}
        </section>}
        <div className="modal-actions">
          {notice && <small className="hint">{notice}</small>}
          <button className="ghost" type="button" onClick={() => save(true)}>
            {copy.saveAndOpen}
          </button>
          <button className="approve" onClick={() => save()}>
            {copy.save}
          </button>
        </div>
        {visualEditorOpen && <VisualRunnerEditor blueprint={visualBlueprint} locale={locale} onClose={() => setVisualEditorOpen(false)} onApply={(blueprint, source) => { setVisualBlueprint(blueprint); setVisualDetached(false); setDraft({ ...draft, source }); setVisualEditorOpen(false); }} />}
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
  createdAt,
  usageCount = 0,
  locale,
  onClick,
  onDelete,
  deleteLabel = "Delete",
}: {
  name: string;
  detail: string;
  createdAt?: string;
  usageCount?: number;
  locale?: Locale;
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
      <span className="catalog-row__usage">{usageCount}</span>
      <time className="catalog-row__created" dateTime={createdAt}>
        {createdAt
          ? new Intl.DateTimeFormat(intlLocales[locale ?? "en"], {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(createdAt))
          : "-"}
      </time>
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
export function ProfileCatalog({
  locale,
  profiles,
  settings,
  setSettings,
  test,
  save,
  tested,
  loading,
  onDelete,
  usage,
}: {
  locale: Locale;
  profiles: Settings[];
  settings: Settings;
  setSettings: (settings: Settings) => void;
  test: () => void;
  save: () => Promise<unknown>;
  tested: boolean;
  loading: boolean;
  onDelete: (id: string) => void;
  usage?: AssetUsage["profiles"];
}) {
  const copy = localeMessages<{
      profiles: ProfileCatalogCopy;
      profileForm: ProfileFormCopy;
    }>(locale, "settingsPage"),
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails"),
    [open, setOpen] = useState(false);
  const saveProfile = () => save().then(() => setOpen(false));
  return (
    <section className="panel app-settings">
      <div className="panel-title-action">
        <div className="panel-title-action__copy">
          <PanelHeader
            title={<SectionInfo title={copy.profiles.title} description={sectionDetails.assetProfiles} />}
          />
          <p className="hint section-description">{copy.profiles.description}</p>
        </div>
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
      <div className="settings-section-content">
        <AssetCatalog locale={locale} loading={loading} emptyHint={copy.profiles.empty}>
          {profiles.map((profile) => (
              <AssetRow
                key={profile.profile_name}
                name={profile.profile_name}
                detail={`${profile.provider} · ${profile.model || "—"}`}
                createdAt={profile.created_at}
                usageCount={usage?.get(profile.profile_name) ?? 0}
                locale={locale}
                onClick={() => {
                  setSettings(profile);
                  setOpen(true);
                }}
                onDelete={() => onDelete(profile.profile_name)}
                deleteLabel={`${copy.profiles.delete} ${profile.profile_name}`}
              />
          ))}
        </AssetCatalog>
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
  loading,
  onDelete,
  usage,
}: {
  locale: Locale;
  items: RunnerAsset[];
  onRefresh: () => Promise<unknown>;
  loading: boolean;
  onDelete: (kind: "runner", id: string) => void;
  usage: AssetUsage["runners"];
}) {
  const [open, setOpen] = useState(false),
    [editing, setEditing] = useState<RunnerAsset | null>(null);
  const copy = runnerLabels[locale], sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails");
  return (
    <section className="panel app-settings">
      <div className="panel-title-action">
        <div className="panel-title-action__copy">
          <PanelHeader
            title={<SectionInfo title={copy.title} description={sectionDetails.assetRunners} />}
          />
          <p className="hint section-description">{text[locale].emptyRunners}</p>
        </div>
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
      <AssetCatalog locale={locale} loading={loading} emptyHint={text[locale].emptyRunners}>
        {items.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · v${item.version} · ${item.description}`}
              createdAt={item.created_at}
              usageCount={usage.get(item.id) ?? 0}
              locale={locale}
              onClick={() => {
                setEditing(item);
                setOpen(true);
              }}
              onDelete={() => onDelete("runner", item.id)}
              deleteLabel={copy.delete}
            />
          ))}
      </AssetCatalog>
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
  locale,
  template,
  onClose,
  onSaved,
  l,
  help,
}: {
  locale: Locale;
  template: PromptTemplate;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
  l: Record<string, string>;
  help: Record<string, string>;
}) {
  const copy = localeMessages<Record<string, string>>(locale, "promptDraft");
  const [pendingAction, setPendingAction] = useState<
    { type: "close" } | { type: "version"; version: number } | null
  >(null);
  const draftKey = `orbit.prompt-template-draft.${template.id}`,
    versions = template.versions?.length
      ? template.versions
      : [{ version: template.version, content: template.content }];
  const [draft, setDraft] = useState(() => {
      const saved = localStorage.getItem(draftKey);
      return saved ? (JSON.parse(saved) as PromptTemplate) : { ...template };
    }),
    [selectedVersion, setSelectedVersion] = useState(draft.version),
    [notice, setNotice] = useState("");
  const selectedContent =
    versions.find((item) => item.version === selectedVersion)?.content ??
    template.content;
  const dirty =
    draft.name !== template.name ||
    draft.content !== selectedContent ||
    draft.id !== template.id;
  useEffect(() => {
    if (dirty) localStorage.setItem(draftKey, JSON.stringify(draft));
    else localStorage.removeItem(draftKey);
  }, [draft, dirty, draftKey]);
  const close = () => {
    if (dirty) setPendingAction({ type: "close" });
    else onClose();
  };
  const applyVersion = (version: number) => {
    const selected = versions.find((item) => item.version === version);
    if (selected) {
      setSelectedVersion(version);
      setDraft({ ...template, content: selected.content, version });
      localStorage.removeItem(draftKey);
    }
  };
  const selectVersion = (version: number) => {
    if (dirty) setPendingAction({ type: "version", version });
    else applyVersion(version);
  };
  const discard = () => {
    if (!pendingAction) return;
    localStorage.removeItem(draftKey);
    if (pendingAction.type === "close") onClose();
    else applyVersion(pendingAction.version);
    setPendingAction(null);
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
    <>
      <Modal open={!pendingAction} title={l.addTemplate} onClose={close}>
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
              {copy.savedHint}
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
      <ConfirmDialog
        open={pendingAction !== null}
        title={copy.title}
        description={pendingAction?.type === "version" ? copy.switchDescription : copy.closeDescription}
        cancelLabel={copy.cancel}
        confirmLabel={copy.discard}
        onCancel={() => setPendingAction(null)}
        onConfirm={discard}
      />
    </>
  );
}

function LegacyAssetsPage({
  locale,
  workflows,
  runners,
  promptTemplates,
  testCaseSets,
  loading,
  onRefresh,
  onCreateWorkflow,
  onUpdateWorkflow,
  onDelete,
  usage,
  activeTab,
}: {
  locale: Locale;
  workflows: Workflow[];
  runners: RunnerAsset[];
  promptTemplates: PromptTemplate[];
  testCaseSets: TargetTestCaseSet[];
  loading: boolean;
  onRefresh: () => Promise<unknown>;
  onCreateWorkflow: (values: unknown) => Promise<unknown>;
  onUpdateWorkflow: (id: string, values: unknown) => Promise<unknown>;
  onDelete: (kind: "template" | "test-set" | "runner" | "workflow", id: string) => void;
  usage: AssetUsage;
  activeTab: "ai" | "test-design" | "run-setup";
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
      {activeTab === "ai" && <Catalog
        locale={locale}
        loading={loading}
        emptyHint={l.emptyTemplates}
        title={l.templates}
        tooltip={localeMessages<Record<string, string>>(locale, "sectionDetails").assetTemplates}
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
            createdAt={item.created_at}
            usageCount={usage.promptTemplates.get(item.id) ?? 0}
            locale={locale}
            onClick={() => setTemplate(item)}
            onDelete={() => onDelete("template", item.id)}
          />
        ))}
      </Catalog>}
      {activeTab === "test-design" && <Catalog
        locale={locale}
        loading={loading}
        emptyHint={l.emptyTests}
        title={l.tests}
        tooltip={localeMessages<Record<string, string>>(locale, "sectionDetails").assetTests}
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
            createdAt={item.created_at}
            usageCount={usage.testCaseSets.get(item.id) ?? 0}
            locale={locale}
            onClick={() => setTestSet(item)}
            onDelete={() => onDelete("test-set", item.id)}
          />
        ))}
      </Catalog>}
      {activeTab === "run-setup" && <Catalog
        locale={locale}
        loading={loading}
        showRunners
        runners={runners}
        runnerUsage={usage.runners}
        onRefresh={onRefresh}
        onDelete={onDelete}
        emptyHint={l.emptyFlows}
        title={l.flows}
        tooltip={localeMessages<Record<string, string>>(locale, "sectionDetails").assetRunners}
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
            usageCount={0}
            onClick={() => {
              setEditingWorkflow(item);
              setFlowOpen(true);
            }}
            onDelete={() => onDelete("workflow", item.id)}
          />
        ))}
      </Catalog>}
      {template && (
        <PromptTemplateEditor
          locale={locale}
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
        <AssetCatalog emptyHint="No execution environments yet.">
          {executionEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={item.id}
              createdAt={item.created_at}
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
        </AssetCatalog>
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
        <AssetCatalog emptyHint="No target environments yet.">
          {targetEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.repository}`}
              createdAt={item.created_at}
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
        </AssetCatalog>
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
  loading,
  onRefresh,
  onDelete,
  usage,
}: {
  locale: Locale;
  executionEnvironments: ExecutionEnvironment[];
  targetEnvironments: TargetEnvironment[];
  loading: boolean;
  onRefresh: () => Promise<unknown>;
  onDelete: (
    kind: "execution-environment" | "target-environment",
    id: string,
  ) => void;
  usage: Pick<AssetUsage, "executionEnvironments" | "targetEnvironments">;
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
      pushToast(t.assetSaved, "success");
    } catch (error) {
      pushToast(error instanceof Error ? error.message : t.assetSaveFailed);
    }
  };
  const help = fieldHelp[locale], sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails");
  return (
    <>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader
              title={<SectionInfo title={t.execution} description={sectionDetails.executionEnvironment} />}
            />
            <p className="hint section-description">{t.executionHint}</p>
          </div>
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
        <AssetCatalog locale={locale} loading={loading} emptyHint={t.executionHint}>
          {executionEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={item.id}
              createdAt={item.created_at}
              usageCount={usage.executionEnvironments.get(item.id) ?? 0}
              locale={locale}
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
        </AssetCatalog>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader
              title={<SectionInfo title={t.target} description={sectionDetails.targetEnvironment} />}
            />
            <p className="hint section-description">{t.targetHint}</p>
          </div>
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
        <AssetCatalog locale={locale} loading={loading} emptyHint={t.targetHint}>
          {targetEnvironments.map((item) => (
            <AssetRow
              key={item.id}
              name={item.name}
              detail={`${item.id} · ${item.repository}`}
              createdAt={item.created_at}
              usageCount={usage.targetEnvironments.get(item.id) ?? 0}
              locale={locale}
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
        </AssetCatalog>
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

function PersonaCatalog({ builds, onRefresh, locale, loading }: { builds: Build[]; onRefresh: () => Promise<unknown>; locale: Locale; loading: boolean }) {
  const t = text[locale];
  const [items, setItems] = useState<Persona[]>([]), [draft, setDraft] = useState<Persona | null>(null), [error, setError] = useState(""), [itemsLoading, setItemsLoading] = useState(true);
  const load = () => {
    setItemsLoading(true);
    return api<Persona[]>("/api/personas").then(setItems).finally(() => setItemsLoading(false));
  };
  useEffect(() => {
    void api<Persona[]>("/api/personas").then(setItems).finally(() => setItemsLoading(false));
  }, []);
  const save = () => {
    if (!draft) return;
    const exists = items.some((item) => item.id === draft.id);
    api<Persona>(exists ? `/api/personas/${draft.id}` : "/api/personas", exists ? "PUT" : "POST", draft)
      .then(() => { setDraft(null); setError(""); return Promise.all([load(), onRefresh()]); })
      .catch((value) => setError(value.message));
  };
  const selectedLocale =
    personaLocaleOptions.find((option) => option.value === draft?.locale) ??
    (draft ? { value: draft.locale, label: draft.locale } : null);
  return <section className="panel app-settings"><div className="panel-title-action"><div className="panel-title-action__copy"><PanelHeader title={<SectionInfo title={t.personas} description={t.personaDescription} />} /><p className="hint section-description">{t.personaDescription}</p></div><button className="approve" onClick={() => setDraft({ id: `persona-${Date.now()}`, name: "", locale: "en-US", timezone: "UTC", activity_windows: [], definition: "", context: {} })}><Plus size={14} />{locales[locale].ui.create}</button></div><AssetCatalog locale={locale} loading={loading || itemsLoading} emptyHint={t.emptyPersonas}>{items.map((item) => <AssetRow key={item.id} name={item.name} detail={`${item.locale} · ${item.timezone}`} usageCount={builds.filter((build) => build.persona_ids?.includes(item.id)).length} locale={locale} onClick={() => setDraft(item)} onDelete={() => api(`/api/personas/${item.id}`, "DELETE").then(() => Promise.all([load(), onRefresh()]).then(() => undefined)).catch((value) => setError(value.message))} />)}</AssetCatalog>{draft && <Modal open title={t.persona} onClose={() => setDraft(null)}><div className="modal-form"><label className="modal-setting-row"><span>{t.id}</span><input disabled={items.some((item) => item.id === draft.id)} value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value })} /></label><label className="modal-setting-row"><span>{t.name}</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label className="modal-setting-row"><span>{t.locale}</span><Select classNamePrefix="orbit-select" options={personaLocaleOptions} value={selectedLocale} placeholder={t.localeSearch} noOptionsMessage={() => t.noMatchingOptions} onChange={(option) => option && setDraft({ ...draft, locale: option.value })} /></label><label className="modal-setting-row"><span>{t.timezone}</span><TimezoneSelect classNamePrefix="orbit-select" value={draft.timezone} placeholder={t.timezoneSearch} noOptionsMessage={() => t.noMatchingOptions} onChange={(option) => setDraft({ ...draft, timezone: option.value })} /></label><label className="modal-setting-row"><span>{t.definition}</span><div className="persona-definition-editor"><MarkdownEditor value={draft.definition} onChange={(definition) => setDraft({ ...draft, definition })} label={t.definition} placeholder={t.definitionPlaceholder} /></div></label><label className="modal-setting-row"><span>{t.activityContext}</span><div className="persona-context-editor"><JsonEditor value={JSON.stringify({ activity_windows: draft.activity_windows, context: draft.context }, null, 2)} onChange={(source) => { try { const value = JSON.parse(source); setDraft({ ...draft, activity_windows: value.activity_windows ?? [], context: value.context ?? {} }); setError(""); } catch { setError(t.invalidPersonaJson); } }} label={t.activityContext} height="260px" /></div></label><div className="modal-actions"><small>{error}</small><button className="approve" onClick={save}>{t.save}</button></div></div></Modal>}</section>;
}

export function AssetsPage({
  locale,
  builds,
  executionEnvironments,
  targetEnvironments,
  profiles,
  settings,
  setSettings,
  test,
  save,
  tested,
  loading,
  onDelete,
  ...legacy
}: {
  locale: Locale;
  builds: Build[];
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
  loading: boolean;
  onRefresh: () => Promise<unknown>;
  onCreateWorkflow: (values: unknown) => Promise<unknown>;
  onUpdateWorkflow: (id: string, values: unknown) => Promise<unknown>;
  onDelete: (
    kind:
      | "profile"
      | "template"
      | "test-set"
      | "runner"
      | "workflow"
      | "execution-environment"
      | "target-environment",
    id: string,
  ) => void;
}) {
  const usage = useMemo(() => buildAssetUsage(builds), [builds]);
  const tabs = [
    { id: "ai" as const, label: text[locale].tabAI },
    { id: "test-design" as const, label: text[locale].tabTestDesign },
    { id: "run-setup" as const, label: text[locale].tabRunSetup },
  ];
  const [activeTab, setActiveTab] = useState<AssetTab>(assetTabFromLocation);
  useEffect(() => {
    const sync = () => setActiveTab(assetTabFromLocation());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  const selectTab = (tab: AssetTab) => {
    if (tab === activeTab) return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.pushState(null, "", `${url.pathname}${url.search}${url.hash}`);
    setActiveTab(tab);
  };
  const moveTab = (offset: number) => {
    const index = tabs.findIndex((tab) => tab.id === activeTab);
    selectTab(tabs[(index + offset + tabs.length) % tabs.length].id);
  };
  return (
    <>
      <div className="asset-tabs" role="tablist" aria-label={text[locale].tabsLabel}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`asset-tab-${tab.id}`}
            role="tab"
            type="button"
            aria-selected={activeTab === tab.id}
            aria-controls={`asset-panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            className={activeTab === tab.id ? "selected" : undefined}
            onClick={() => selectTab(tab.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") { event.preventDefault(); moveTab(1); }
              if (event.key === "ArrowLeft") { event.preventDefault(); moveTab(-1); }
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div id={`asset-panel-${activeTab}`} role="tabpanel" aria-labelledby={`asset-tab-${activeTab}`}>
      {activeTab === "ai" && <>
      <ProfileCatalog
        locale={locale}
        profiles={profiles}
        settings={settings}
        setSettings={setSettings}
        test={test}
        save={save}
        tested={tested}
        loading={loading}
        usage={usage.profiles}
        onDelete={(id) => onDelete("profile", id)}
      />
      <LegacyAssetsPage {...legacy} locale={locale} loading={loading} onDelete={onDelete} usage={usage} activeTab="ai" />
      </>}
      {activeTab === "test-design" && <>
      <PersonaCatalog builds={builds} onRefresh={legacy.onRefresh} locale={locale} loading={loading} />
      <LegacyAssetsPage {...legacy} locale={locale} loading={loading} onDelete={onDelete} usage={usage} activeTab="test-design" />
      </>}
      {activeTab === "run-setup" && <>
      <EnvironmentCatalog
        locale={locale}
        executionEnvironments={executionEnvironments}
        targetEnvironments={targetEnvironments}
        loading={loading}
        onRefresh={legacy.onRefresh}
        onDelete={onDelete}
        usage={usage}
      />
      <LegacyAssetsPage {...legacy} locale={locale} loading={loading} onDelete={onDelete} usage={usage} activeTab="run-setup" />
      </>}
      </div>
    </>
  );
}
