import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Database, ExternalLink, Pencil, RotateCcw, Save } from "lucide-react";
import type { Locale } from "../../locales";
import { localeMessages, localeOptions, locales } from "../../locales";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import { DataTable, type Column } from "../../components/ui/data-table";
import type { OrbitLog, Settings } from "../../domain/models";
import { api } from "../../services/api";
import { useToast } from "../../components/ui/toast-context";
import { ProfileCatalog } from "../assets/page";
import { OrbitLogs } from "./orbit-logs";
import { useAssistantUiBridge } from "../../components/assistant-ui-bridge";
import { JsonEditor } from "../../components/ui/json-editor";

type ApplicationSettings = {
  manager_prompt_template: string;
  manager_output_locale: string;
  chat_model_profile_name: string;
  coding_agent_provider: "none" | "kiro" | "claude-code" | "codex";
};
type ApplicationData = { path: string; size_bytes: number };

type ManagerCopy = { title:string; description:string; warning:string; edit:string; content:string; save:string; cancel:string; empty:string; saved:string };

type ProfileCopy = { title:string; description:string; create:string; edit:string; empty:string; delete:string; chatProfile:string; chatProfileHint:string; selectChatProfile:string; saveChatProfile:string; chatProfileSaved:string };
type CodingAgentCopy = { title:string; description:string; select:string; none:string; save:string; saved:string };
type McpCopy = { title:string; description:string; edit:string; save:string; reset:string; openInVsCode:string; name:string; url:string; status:string; enabled:string; disabled:string; noServers:string; saved:string };
type StorageCopy = { title:string; description:string; location:string; locationHint:string; size:string; calculating:string; save:string; saved:string };
type SettingsCopy = { manager: ManagerCopy; profiles: ProfileCopy; codingAgent: CodingAgentCopy; mcp: McpCopy; storage: StorageCopy };
type McpServer = { id: string; name: string; url: string; enabled: boolean };
const defaultMcpConfig = JSON.stringify(
  { mcpServers: { openorbit: { url: "http://127.0.0.1:3000/mcp/" } } },
  null,
  2,
);
const bytes = (value: number) => {
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = value ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1) : 0;
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
};

export function SettingsPage({
  locale,
  setLocale,
  theme,
  setTheme,
  profiles,
  settings,
  setSettings,
  test,
  save,
  tested,
  logs,
  onDeleteProfile,
}: {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  theme: string;
  setTheme: (theme: string) => void;
  profiles: Settings[];
  settings: Settings;
  setSettings: (settings: Settings) => void;
  test: () => void;
  save: () => Promise<unknown>;
  tested: boolean;
  logs: OrbitLog[];
  onDeleteProfile: (profileName: string) => void;
}) {
  const { register: registerAssistantUi } = useAssistantUiBridge();
  const t = locales[locale].common,
    settingsCopy = localeMessages<SettingsCopy>(locale, "settingsPage"),
    l = settingsCopy.manager,
    p = settingsCopy.profiles,
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails");
  const [prompt, setPrompt] = useState(""),
    [chatProfile, setChatProfile] = useState(""),
    [codingAgent, setCodingAgent] = useState<ApplicationSettings["coding_agent_provider"]>("none"),
    [mcpConfig, setMcpConfig] = useState(""),
    [mcpOpen, setMcpOpen] = useState(false),
    [dataPath, setDataPath] = useState(""),
    [dataPathDraft, setDataPathDraft] = useState(""),
    [dataSize, setDataSize] = useState<number | null>(null),
    [dataLoading, setDataLoading] = useState(true),
    [dataEditing, setDataEditing] = useState(false),
    [open, setOpen] = useState(false);
  const { pushToast } = useToast();
  useEffect(() => {
    api<ApplicationSettings>("/api/application-settings")
      .then((values) => {
        setPrompt(values.manager_prompt_template);
        setChatProfile(values.chat_model_profile_name);
        setCodingAgent(values.coding_agent_provider ?? "none");
      })
      .catch(() => pushToast(locales[locale].ui.operationalPromptLoadFailed));
  }, [locale, pushToast]);
  useEffect(() => { api<{ content: string }>("/api/assistant-mcp-config").then((value) => setMcpConfig(value.content)).catch((error) => pushToast(error.message)); }, [pushToast]);
  useEffect(() => {
    let mounted = true;
    api<ApplicationData>("/api/application-data")
      .then((values) => {
        if (!mounted) return;
        setDataPath(values.path);
        setDataPathDraft(values.path);
        setDataSize(values.size_bytes);
      })
      .catch((error) => mounted && pushToast(error.message))
      .finally(() => mounted && setDataLoading(false));
    return () => { mounted = false; };
  }, [pushToast]);
  const saveApplication = () =>
    api<ApplicationSettings>("/api/application-settings", "PUT", {
      manager_prompt_template: prompt,
      chat_model_profile_name: chatProfile,
      coding_agent_provider: codingAgent,
    })
      .then((values) => {
        setPrompt(values.manager_prompt_template);
        setChatProfile(values.chat_model_profile_name);
        pushToast(l.saved, "success");
        setOpen(false);
      })
      .catch((error) => pushToast(error.message));
  const saveChatProfile = () =>
    api<ApplicationSettings>("/api/application-settings", "PUT", {
      manager_prompt_template: prompt,
      chat_model_profile_name: chatProfile,
    })
      .then((values) => {
        setChatProfile(values.chat_model_profile_name);
        pushToast(p.chatProfileSaved, "success");
      })
      .catch((error) => pushToast(error.message));
  const saveCodingAgent = () =>
    api<ApplicationSettings>("/api/application-settings", "PUT", {
      coding_agent_provider: codingAgent,
    })
      .then((values) => {
        setCodingAgent(values.coding_agent_provider);
        pushToast(settingsCopy.codingAgent.saved, "success");
      })
      .catch((error) => pushToast(error.message));
  const mcpServers = useMemo(() => {
    try {
      const value = JSON.parse(mcpConfig) as { mcpServers?: unknown };
      if (!value.mcpServers || typeof value.mcpServers !== "object" || Array.isArray(value.mcpServers)) return [];
      return Object.entries(value.mcpServers).map(([name, config]) => {
        const details = config && typeof config === "object" && !Array.isArray(config)
          ? config as Record<string, unknown>
          : {};
        return {
          id: name,
          name,
          url: typeof details.url === "string" ? details.url : "—",
          enabled: details.enabled !== false && details.disabled !== true,
        };
      });
    } catch { return []; }
  }, [mcpConfig]);
  const mcpColumns = useMemo<Column<McpServer>[]>(() => [
    { id: "name", header: settingsCopy.mcp.name, render: (server) => <strong>{server.name}</strong>, sortValue: (server) => server.name },
    { id: "url", header: settingsCopy.mcp.url, render: (server) => server.url, sortValue: (server) => server.url },
    {
      id: "status",
      header: settingsCopy.mcp.status,
      render: (server) => server.enabled ? settingsCopy.mcp.enabled : settingsCopy.mcp.disabled,
      sortValue: (server) => server.enabled,
    },
  ], [settingsCopy.mcp]);
  const saveMcpConfig = () => api<{ content: string }>("/api/assistant-mcp-config", "PUT", { content: mcpConfig }).then((value) => { setMcpConfig(value.content); setMcpOpen(false); pushToast(settingsCopy.mcp.saved, "success"); }).catch((error) => pushToast(error.message));
  const saveDataLocation = () => {
    setDataLoading(true);
    api<ApplicationData>("/api/application-data", "PUT", { path: dataPathDraft })
      .then((values) => {
        setDataPath(values.path);
        setDataPathDraft(values.path);
        setDataSize(values.size_bytes);
        pushToast(settingsCopy.storage.saved, "success");
        setDataEditing(false);
      })
      .catch((error) => pushToast(error.message))
      .finally(() => setDataLoading(false));
  };
  const setLanguage = useCallback((nextLocale: Locale) => {
    setLocale(nextLocale);
    api<ApplicationSettings>("/api/application-settings", "PUT", {
      manager_output_locale: nextLocale,
    }).catch((error) => pushToast(error.message));
  }, [pushToast, setLocale]);
  const settingsUi = useMemo(
    () => ({
      id: "settings.application",
      title: "Application settings",
      getState: () => ({ locale, theme, coding_agent_provider: codingAgent, editing_data_location: dataEditing }),
      controls: [
        {
          id: "locale",
          label: "Language",
          kind: "select" as const,
          value: locale,
          options: localeOptions.map((option) => ({ value: option.id, label: option.label })),
          setValue: (value: unknown) => {
            if (typeof value === "string" && localeOptions.some((option) => option.id === value))
              setLanguage(value as Locale);
          },
        },
        {
          id: "theme",
          label: "Theme",
          kind: "select" as const,
          value: theme,
          options: [
            { value: "forest", label: "Forest dark" },
            { value: "midnight", label: "Midnight" },
          ],
          setValue: (value: unknown) => {
            if (value === "forest" || value === "midnight") setTheme(value);
          },
        },
        {
          id: "coding_agent_provider",
          label: "Coding Agent",
          kind: "select" as const,
          value: codingAgent,
          options: [
            { value: "none", label: settingsCopy.codingAgent.none },
            { value: "kiro", label: "Kiro" },
            { value: "claude-code", label: "Claude Code" },
            { value: "codex", label: "Codex" },
          ],
          setValue: (value: unknown) => {
            if (["none", "kiro", "claude-code", "codex"].includes(String(value)))
              setCodingAgent(value as ApplicationSettings["coding_agent_provider"]);
          },
        },
        ...(dataEditing ? [{
          id: "application_data_path",
          label: "Application data location",
          kind: "text" as const,
          value: dataPathDraft,
          setValue: (value: unknown) => {
            if (typeof value === "string") setDataPathDraft(value);
          },
        }] : []),
      ],
      actions: [
        {
          id: "edit_application_data_location",
          label: "Edit application data location",
          run: () => setDataEditing(true),
        },
      ],
    }),
    [codingAgent, dataEditing, dataPathDraft, locale, setLanguage, setTheme, settingsCopy.codingAgent.none, theme],
  );
  useEffect(() => registerAssistantUi(settingsUi), [registerAssistantUi, settingsUi]);
  return (
    <>
      <section className="panel app-settings">
        <PanelHeader title={<SectionInfo title={t.applicationSettings} description={sectionDetails.applicationSettings} />} />
        <p className="hint section-description">{t.applicationSettingsDescription}</p>
        <label className="setting-row">
          <span>
            <strong>{t.language}</strong>
            <small>{t.languageHint}</small>
          </span>
          <select
            value={locale}
            onChange={(event) => setLanguage(event.target.value as Locale)}
          >
              {localeOptions.map((language) => <option key={language.id} value={language.id}>{language.label}</option>)}
          </select>
        </label>
        <label className="setting-row">
          <span>
            <strong>{t.theme}</strong>
            <small>{t.themeHint}</small>
          </span>
          <select
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          >
            <option value="forest">Forest dark</option>
            <option value="midnight">Midnight</option>
          </select>
        </label>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={<SectionInfo title={settingsCopy.mcp.title} description={settingsCopy.mcp.description} />} />
            <p className="hint section-description">{settingsCopy.mcp.description}</p>
          </div>
          <button className="approve" onClick={() => setMcpOpen(true)}><Pencil size={14} />{settingsCopy.mcp.edit}</button>
        </div>
        <div className="settings-section-content">
          <DataTable
            className="mcp-server-table"
            columns={mcpColumns}
            rows={mcpServers}
            empty={settingsCopy.mcp.noServers}
            gridTemplateColumns="minmax(140px,.8fr) minmax(280px,2fr) 110px"
          />
        </div>
      </section>
      <section className="panel app-settings app-data-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={<SectionInfo title={settingsCopy.storage.title} description={sectionDetails.applicationData} />} />
            <p className="hint section-description">{settingsCopy.storage.description}</p>
          </div>
          {!dataEditing && <button className="approve" onClick={() => { setDataPathDraft(dataPath); setDataEditing(true); }}>
            <Pencil size={14} />
            {l.edit}
          </button>}
        </div>
        <div className="setting-row">
          <div className="settings-summary">
            <span className="settings-summary-label">{settingsCopy.storage.location}</span>
            <span className="settings-summary-detail">{settingsCopy.storage.locationHint}</span>
          </div>
          {dataEditing ? (
            <div className="app-data-path-actions">
              <input value={dataPathDraft} onChange={(event) => setDataPathDraft(event.target.value)} />
              <div className="app-data-edit-actions">
                <button className="ghost" onClick={() => { setDataPathDraft(dataPath); setDataEditing(false); }}>
                  {l.cancel}
                </button>
                <button className="approve" disabled={!dataPathDraft || dataLoading} onClick={saveDataLocation}>
                  <Save size={14} />
                  {settingsCopy.storage.save}
                </button>
              </div>
            </div>
          ) : (
            <div className="app-data-path-actions">
              <p className="setting-prompt-preview app-data-path">{dataPath}</p>
            </div>
          )}
        </div>
        <div className="app-data-size" aria-live="polite">
          <Database size={16} />
          <span>{settingsCopy.storage.size}</span>
          <strong>{dataLoading ? settingsCopy.storage.calculating : bytes(dataSize ?? 0)}</strong>
        </div>
      </section>
      <ProfileCatalog
        locale={locale}
        profiles={profiles}
        settings={settings}
        setSettings={setSettings}
        test={test}
        save={save}
        tested={tested}
        loading={false}
        onDelete={onDeleteProfile}
      />
      <section className="panel app-settings">
        <PanelHeader title={<SectionInfo title={p.chatProfile} description={sectionDetails.systemAiModel} />} />
        <p className="hint section-description">{p.chatProfileHint}</p>
        <label className="setting-row">
          <span>
            <strong>{p.selectChatProfile}</strong>
            <small>{p.chatProfileHint}</small>
          </span>
          <div className="setting-actions">
            <select
              aria-label={p.chatProfile}
              value={chatProfile}
              onChange={(event) => setChatProfile(event.target.value)}
            >
              <option value="">{p.selectChatProfile}</option>
              {profiles.map((profile) => (
                <option key={profile.profile_name} value={profile.profile_name}>
                  {profile.profile_name} · {profile.model || profile.provider}
                </option>
              ))}
            </select>
            <button
              className="approve"
              onClick={saveChatProfile}
            >
              {p.saveChatProfile}
            </button>
          </div>
        </label>
      </section>
      <section className="panel app-settings">
        <PanelHeader title={<SectionInfo title={settingsCopy.codingAgent.title} description={sectionDetails.orbitAssistantCodingAgent} />} />
        <p className="hint section-description">{settingsCopy.codingAgent.description}</p>
        <label className="setting-row">
          <span>
            <strong>{settingsCopy.codingAgent.select}</strong>
            <small>{settingsCopy.codingAgent.description}</small>
          </span>
          <div className="setting-actions">
            <select aria-label={settingsCopy.codingAgent.title} value={codingAgent} onChange={(event) => setCodingAgent(event.target.value as ApplicationSettings["coding_agent_provider"])}>
              <option value="none">{settingsCopy.codingAgent.none}</option>
              <option value="kiro">Kiro</option>
              <option value="claude-code">Claude Code</option>
              <option value="codex">Codex</option>
            </select>
            <button className="approve" onClick={saveCodingAgent}>{settingsCopy.codingAgent.save}</button>
          </div>
        </label>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={l.title} description={sectionDetails.managerPrompt} />
            <p className="hint section-description">{l.description}</p>
          </div>
          <button className="approve" onClick={() => setOpen(true)}>
            <Pencil size={14} />
            {l.edit}
          </button>
        </div>
        <div className="settings-section-content">
          <p className="operational-prompt-warning" role="note">
            <AlertTriangle size={16} />
            {l.warning}
          </p>
          <p className="setting-prompt-preview">{prompt || l.empty}</p>
        </div>
      </section>
      <OrbitLogs logs={logs} locale={locale} />
      <Modal open={mcpOpen} title={settingsCopy.mcp.title} onClose={() => setMcpOpen(false)}>
        <div className="modal-form">
          <JsonEditor value={mcpConfig} onChange={setMcpConfig} label={settingsCopy.mcp.title} />
          <div className="modal-actions">
            <button className="ghost" onClick={() => setMcpConfig(defaultMcpConfig)}>
              <RotateCcw size={14} />
              {settingsCopy.mcp.reset}
            </button>
            <button className="ghost" onClick={() => api("/api/assistant-mcp-config/open-vscode", "POST").catch((error) => pushToast(error.message))}>
              <ExternalLink size={14} />
              {settingsCopy.mcp.openInVsCode}
            </button>
            <button className="approve" onClick={saveMcpConfig}>
              <Save size={14} />
              {settingsCopy.mcp.save}
            </button>
          </div>
        </div>
      </Modal>
      <Modal open={open} title={l.title} onClose={() => setOpen(false)}>
        <div className="modal-form">
          <label className="modal-setting-row">
            <span>{l.content}</span>
            <textarea
              rows={16}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </label>
          <p className="operational-prompt-warning" role="note">
            <AlertTriangle size={16} />
            {l.warning}
          </p>
          <div className="modal-actions">
            <button className="ghost" onClick={() => setOpen(false)}>
              {l.cancel}
            </button>
            <button className="approve" onClick={saveApplication}>
              {l.save}
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}
