import { ChevronLeft, ChevronRight, FileUp, Languages, Sparkles } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { ProfileFormCopy } from "../features/builds/page";
import { type QuickStart, type Settings, type WorkflowGraphDefinition } from "../domain/models";
import { localeMessages, locales, type Locale } from "../locales";
import { api, upload } from "../services/api";
import { useTemplateTranslations } from "../services/use-template-translation";
import { Modal } from "./ui/modal";
import { SectionInfo } from "./ui/section-info";
import { WorkflowGraph } from "./workflow-graph";

type QuickStartTranslation = {
  name: string;
  description: string;
  parameters?: { label: string; description?: string; tooltip?: string; placeholder?: string; options?: { label: string }[] }[];
};

const translatedQuickStart = (item: QuickStart, translation: QuickStartTranslation | null, labels?: { name: string; description: string }): QuickStart =>
  translation || labels ? {
    ...item,
    name: translation?.name ?? labels?.name ?? item.name,
    description: translation?.description ?? labels?.description ?? item.description,
    parameters: item.parameters.map((parameter, index) => ({
      ...parameter,
      ...translation?.parameters?.[index],
      options: parameter.options?.map((option, optionIndex) => ({ ...option, ...translation?.parameters?.[index]?.options?.[optionIndex] })),
    })),
  } : item;

function Field({ label, description, children, as = "label" }: { label: string; description?: string; children: ReactNode; as?: "div" | "label" }) {
  const Container = as;
  return <Container className="modal-setting-row"><span>{description ? <SectionInfo title={label} description={description} /> : label}</span>{children}</Container>;
}

function QuickStartForm({ item, profiles, create, back, close, onCreated, locale }: {
  item: QuickStart; profiles: Settings[]; create: (id: string, values: Record<string, string>) => Promise<unknown>;
  back: () => void; close: () => void; onCreated?: () => void; locale: Locale;
}) {
  const ui = locales[locale].ui;
  const profileCopy = localeMessages<{ profileForm: ProfileFormCopy }>(locale, "settingsPage").profileForm;
  const createProfileValue = "__create_model_profile__";
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(item.parameters.map((parameter) => [parameter.key, parameter.default ?? (parameter.type === "model_profile" ? profiles[0]?.profile_name ?? "" : "")] )));
  const [newProfile, setNewProfile] = useState<Settings>({ profile_name: "", provider: "azure-openai", model: "", endpoint: "", region: "us-east-1", secret_env: "AZURE_OPENAI_API_KEY", aws_profile: "" });
  const [review, setReview] = useState(false), [busy, setBusy] = useState(false), [graph, setGraph] = useState<WorkflowGraphDefinition | null>(null), [graphLoading, setGraphLoading] = useState(true), [graphError, setGraphError] = useState("");
  useEffect(() => {
    let active = true;
    api<WorkflowGraphDefinition | null>(`/api/quick-starts/${item.id}/preview-graph`, "POST").then((next) => active && setGraph(next)).catch((error: Error) => active && setGraphError(error.message)).finally(() => active && setGraphLoading(false));
    return () => { active = false; };
  }, [item.id]);
  const submit = async () => {
    setBusy(true);
    try {
      const inputs = { ...values }, profileParameter = item.parameters.find((parameter) => parameter.type === "model_profile");
      if (profileParameter && inputs[profileParameter.key] === createProfileValue) {
        inputs[profileParameter.key] = newProfile.profile_name;
        Object.assign(inputs, { __model_profile_mode: "create", __model_profile_provider: newProfile.provider, __model_profile_model: newProfile.model, __model_profile_endpoint: newProfile.endpoint, __model_profile_region: newProfile.region, __model_profile_secret_env: newProfile.secret_env, __model_profile_aws_profile: newProfile.aws_profile ?? "" });
      }
      await create(item.id, inputs);
      close(); onCreated?.();
    } catch { /* The parent displays creation failures through the shared toast. */ } finally { setBusy(false); }
  };
  const inputField = (parameter: QuickStart["parameters"][number]) => parameter.type === "select" ? <select value={values[parameter.key]} onChange={(event) => setValues({ ...values, [parameter.key]: event.target.value })}>{parameter.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input type={parameter.type === "url" ? "url" : "text"} value={values[parameter.key]} placeholder={parameter.placeholder} onChange={(event) => setValues({ ...values, [parameter.key]: event.target.value })} />;
  return <div className="quick-start-form">
    <button className="ghost" onClick={back}><ChevronLeft size={15} />{ui.quickStarts}</button>
    <div className="quick-start-form__heading"><Sparkles size={19} /><div><strong>{item.name}</strong><p>{item.description}</p></div></div>
    {!review && <section className="quick-start-workflow" aria-label={ui.workflowGraph}><strong>{ui.workflowGraph}</strong><p>{ui.quickStartWorkflowDescription}</p>{graphLoading ? <p className="hint">{ui.loadingGraph}</p> : graph?.nodes.length ? <WorkflowGraph nodes={graph.nodes} edges={graph.edges} /> : <p className="hint">{graphError || ui.noWorkflowGraph}</p>}</section>}
    {review ? <div className="quick-start-review"><p>{ui.quickStartReview}</p><dl>{item.parameters.map((parameter) => <><dt key={`${parameter.key}a`}>{parameter.label}</dt><dd key={`${parameter.key}b`}>{parameter.type === "model_profile" && values[parameter.key] === createProfileValue ? newProfile.profile_name || "—" : values[parameter.key] || "—"}</dd></>)}</dl></div> : <div className="modal-form">{item.parameters.map((parameter) => parameter.type !== "model_profile" ? <Field key={parameter.key} label={parameter.label} description={parameter.tooltip ?? parameter.description}>{inputField(parameter)}</Field> : <div className="quick-start-model-profile" key={parameter.key}>
      <Field label={parameter.label} description={parameter.tooltip ?? parameter.description} as="div"><select value={values[parameter.key]} onChange={(event) => setValues({ ...values, [parameter.key]: event.target.value })}>{profiles.map((profile) => <option key={profile.profile_name} value={profile.profile_name}>{profile.profile_name}</option>)}<option value={createProfileValue}>{profileCopy.createNewAiProfile.label}</option></select></Field>
      {values[parameter.key] === createProfileValue && <div className="quick-start-profile-form">
        <Field label={profileCopy.profileName.label} description={profileCopy.profileName.hint}><input value={newProfile.profile_name} onChange={(event) => setNewProfile({ ...newProfile, profile_name: event.target.value })} /></Field>
        <Field label={profileCopy.provider.label} description={profileCopy.provider.hint}><select value={newProfile.provider} onChange={(event) => setNewProfile({ ...newProfile, provider: event.target.value })}><option value="azure-openai">Azure OpenAI</option><option value="aws-bedrock">AWS Bedrock</option></select></Field>
        <Field label={profileCopy.modelDeployment.label} description={profileCopy.modelDeployment.hint}><input value={newProfile.model} onChange={(event) => setNewProfile({ ...newProfile, model: event.target.value })} /></Field>
        {newProfile.provider === "azure-openai" ? <><Field label={profileCopy.azureEndpoint.label} description={profileCopy.azureEndpoint.hint}><input type="url" placeholder="https://your-resource.openai.azure.com" value={newProfile.endpoint} onChange={(event) => setNewProfile({ ...newProfile, endpoint: event.target.value })} /></Field><Field label={profileCopy.secretEnv.label} description={profileCopy.secretEnv.hint}><input placeholder="AZURE_OPENAI_API_KEY" value={newProfile.secret_env} onChange={(event) => setNewProfile({ ...newProfile, secret_env: event.target.value })} /></Field></> : <><Field label={profileCopy.region.label} description={profileCopy.region.hint}><input placeholder="us-east-1" value={newProfile.region} onChange={(event) => setNewProfile({ ...newProfile, region: event.target.value })} /></Field><Field label={profileCopy.awsProfile.label} description={profileCopy.awsProfile.hint}><input placeholder="default" value={newProfile.aws_profile ?? ""} onChange={(event) => setNewProfile({ ...newProfile, aws_profile: event.target.value })} /></Field></>}
      </div>}
    </div>)}</div>}
    <div className="modal-actions">{review ? <><button className="ghost" onClick={() => setReview(false)}>{ui.edit}</button><button className="approve" disabled={busy} onClick={submit}>{busy ? ui.creating : ui.createAssetsAndBuild}</button></> : <button className="approve" onClick={() => setReview(true)}>{ui.review}<ChevronRight size={15} /></button>}</div>
  </div>;
}

function QuickStartCard({ item, translation, labels, pick }: { item: QuickStart; translation: QuickStartTranslation | null; labels?: { name: string; description: string }; pick: (item: QuickStart) => void }) {
  const display = translatedQuickStart(item, translation, labels);
  return <article className="quick-start-card"><button className="quick-start-card__select" onClick={() => pick(item)}><Sparkles size={18} /><span><strong>{display.name}</strong><small>{display.description}</small><em>{item.publisher?.name ?? "Community"} · v{item.version}</em></span><ChevronRight size={16} /></button></article>;
}

export function QuickStartModal({ open, initialQuickStartId, profiles, locale, create, onClose, onCreated }: { open: boolean; initialQuickStartId?: string; profiles: Settings[]; locale: Locale; create: (id: string, values: Record<string, string>) => Promise<unknown>; onClose: () => void; onCreated?: () => void }) {
  const ui = locales[locale].ui, [items, setItems] = useState<QuickStart[]>([]), [picked, setPicked] = useState<QuickStart | null>(null), [error, setError] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const translations = useTemplateTranslations<QuickStartTranslation>("quick-start", items.map((item) => item.id), locale);
  const translationCopy = locales[locale].templateTranslation, allTranslated = items.length > 0 && items.every((item) => Boolean(translations.content(item.id)));
  const labels = localeMessages<Record<string, { name: string; description: string }>>(locale, "quickStartLabels");
  useEffect(() => { if (!open) return; api<QuickStart[]>("/api/quick-starts").then((next) => { setItems(next); setPicked(initialQuickStartId ? next.find((item) => item.id === initialQuickStartId) ?? null : null); }).catch((fetchError: Error) => setError(fetchError.message)); }, [initialQuickStartId, open]);
  const importItem = async (selectedFile: File | undefined) => { if (!selectedFile) return; try { await upload("/api/quick-starts/import-package", selectedFile); setItems(await api("/api/quick-starts")); } catch (importError) { setError(importError instanceof Error ? importError.message : ui.importFailed); } finally { if (file.current) file.current.value = ""; } };
  return <Modal open={open} title={ui.quickStarts} onClose={onClose}>{!picked ? <div className="quick-start-picker"><div className="quick-start-picker__head"><p className="hint">{ui.quickStartsHint}</p><input className="visually-hidden" ref={file} type="file" accept="application/zip,.zip" onChange={(event) => importItem(event.target.files?.[0])} /><div className="template-picker-actions"><button className="ghost" type="button" disabled={translations.loading || translations.cacheLoading} onClick={allTranslated ? () => translations.showOriginal() : () => translations.translate()}><Languages size={15} />{translations.loading ? translationCopy.translating : translations.cacheLoading ? translationCopy.checkingCache : allTranslated ? translationCopy.showOriginal : translationCopy.translate}</button><button className="ghost" onClick={() => file.current?.click()}><FileUp size={15} />{ui.importQuickStart}</button></div></div><div className="quick-start-list">{translations.cacheLoading ? <p className="hint">{translationCopy.checkingCache}</p> : items.map((item) => <QuickStartCard key={item.id} item={item} translation={translations.content(item.id)} labels={labels[item.id]} pick={setPicked} />)}</div>{(error || translations.error) && <small className="hint">{error || translationCopy.failed}</small>}</div> : <QuickStartForm key={picked.id} item={translatedQuickStart(picked, translations.content(picked.id), labels[picked.id])} profiles={profiles} create={create} back={() => setPicked(null)} close={onClose} onCreated={onCreated} locale={locale} />}</Modal>;
}
