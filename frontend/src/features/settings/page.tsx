import { useEffect, useState } from "react";
import { AlertTriangle, Database, Pencil, Plus, Save, Trash2 } from "lucide-react";
import type { Locale } from "../../locales";
import { localeMessages, localeOptions, locales } from "../../locales";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import { SectionInfo } from "../../components/ui/section-info";
import type { OrbitLog, Settings } from "../../domain/models";
import { api } from "../../services/api";
import { useToast } from "../../components/ui/toast-context";
import { ProfileForm, type ProfileFormCopy } from "../evaluation-builds/page";
import { OrbitLogs } from "./orbit-logs";

type ApplicationSettings = {
  manager_prompt_template: string;
  manager_output_locale: string;
  chat_model_profile_name: string;
};
type ApplicationData = { path: string; size_bytes: number };

type ManagerCopy = { title:string; description:string; warning:string; edit:string; content:string; save:string; cancel:string; empty:string; saved:string };

const profileBlank: Settings = {
  profile_name: "",
  provider: "azure-openai",
  model: "",
  endpoint: "",
  region: "us-east-1",
  secret_env: "AZURE_OPENAI_API_KEY",
  aws_profile: "",
};
type ProfileCopy = { title:string; description:string; create:string; edit:string; empty:string; delete:string; chatProfile:string; chatProfileHint:string; selectChatProfile:string; saveChatProfile:string; chatProfileSaved:string };
type StorageCopy = { title:string; description:string; location:string; locationHint:string; size:string; calculating:string; save:string; saved:string };
type SettingsCopy = { manager: ManagerCopy; profiles: ProfileCopy; storage: StorageCopy; profileForm: ProfileFormCopy };
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
  const t = locales[locale].common,
    settingsCopy = localeMessages<SettingsCopy>(locale, "settingsPage"),
    l = settingsCopy.manager,
    p = settingsCopy.profiles,
    sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails"),
    evaluation = locales[locale].evaluation;
  const [prompt, setPrompt] = useState(""),
    [chatProfile, setChatProfile] = useState(""),
    [dataPath, setDataPath] = useState(""),
    [dataSize, setDataSize] = useState<number | null>(null),
    [dataLoading, setDataLoading] = useState(true),
    [open, setOpen] = useState(false),
    [profileOpen, setProfileOpen] = useState(false);
  const { pushToast } = useToast();
  useEffect(() => {
    api<ApplicationSettings>("/api/application-settings")
      .then((values) => {
        setPrompt(values.manager_prompt_template);
        setChatProfile(values.chat_model_profile_name);
        if (values.manager_output_locale !== locale) {
          return api<ApplicationSettings>("/api/application-settings", "PUT", {
            manager_output_locale: locale,
          });
        }
      })
      .catch(() => pushToast("Unable to load operational prompt."));
  }, [locale, pushToast]);
  useEffect(() => {
    let mounted = true;
    api<ApplicationData>("/api/application-data")
      .then((values) => {
        if (!mounted) return;
        setDataPath(values.path);
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
  const saveProfile = () => save().then(() => setProfileOpen(false));
  const saveDataLocation = () => {
    setDataLoading(true);
    api<ApplicationData>("/api/application-data", "PUT", { path: dataPath })
      .then((values) => {
        setDataPath(values.path);
        setDataSize(values.size_bytes);
        pushToast(settingsCopy.storage.saved, "success");
      })
      .catch((error) => pushToast(error.message))
      .finally(() => setDataLoading(false));
  };
  const setLanguage = (nextLocale: Locale) => {
    setLocale(nextLocale);
    api<ApplicationSettings>("/api/application-settings", "PUT", {
      manager_output_locale: nextLocale,
    }).catch((error) => pushToast(error.message));
  };
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
      <section className="panel app-settings app-data-settings">
        <PanelHeader title={<SectionInfo title={settingsCopy.storage.title} description={sectionDetails.applicationData} />} />
        <p className="hint section-description">{settingsCopy.storage.description}</p>
        <label className="setting-row">
          <span>
            <strong>{settingsCopy.storage.location}</strong>
            <small>{settingsCopy.storage.locationHint}</small>
          </span>
          <div className="setting-actions">
            <input value={dataPath} onChange={(event) => setDataPath(event.target.value)} />
            <button className="approve" disabled={!dataPath || dataLoading} onClick={saveDataLocation}>
              <Save size={14} />
              {settingsCopy.storage.save}
            </button>
          </div>
        </label>
        <div className="app-data-size" aria-live="polite">
          <Database size={16} />
          <span>{settingsCopy.storage.size}</span>
          <strong>{dataLoading ? settingsCopy.storage.calculating : bytes(dataSize ?? 0)}</strong>
        </div>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={<SectionInfo title={p.title} description={sectionDetails.assetProfiles} />} />
            <p className="hint section-description">{p.description}</p>
          </div>
          <button
            className="approve"
            onClick={() => {
              setSettings(profileBlank);
              setProfileOpen(true);
            }}
          >
            <Plus size={14} />
            {p.create}
          </button>
        </div>
        <div className="catalog-list">
          {profiles.length ? (
            profiles.map((profile) => (
              <div className="catalog-row-wrap" key={profile.profile_name}>
                <button
                  className="catalog-row"
                  onClick={() => {
                    setSettings(profile);
                    setProfileOpen(true);
                  }}
                >
                  <strong>{profile.profile_name}</strong>
                  <span>
                    {profile.provider} · {profile.model || "—"}
                  </span>
                </button>
                <button
                  className="icon-button danger"
                  aria-label={`${p.delete} ${profile.profile_name}`}
                  onClick={() => onDeleteProfile(profile.profile_name)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))
          ) : (
            <p className="catalog-empty">{p.empty}</p>
          )}
        </div>
      </section>
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
              disabled={!chatProfile}
              onClick={saveChatProfile}
            >
              {p.saveChatProfile}
            </button>
          </div>
        </label>
      </section>
      <section className="panel app-settings">
        <div className="panel-title-action">
          <div className="panel-title-action__copy">
            <PanelHeader title={l.title} />
            <p className="hint section-description">{l.description}</p>
          </div>
          <button className="approve" onClick={() => setOpen(true)}>
            <Pencil size={14} />
            {l.edit}
          </button>
        </div>
        <p className="operational-prompt-warning" role="note">
          <AlertTriangle size={16} />
          {l.warning}
        </p>
        <p className="setting-prompt-preview">{prompt || l.empty}</p>
      </section>
      <OrbitLogs logs={logs} locale={locale} />
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
      <Modal
        open={profileOpen}
        title={settings.profile_name ? p.edit : p.create}
        onClose={() => setProfileOpen(false)}
      >
        <ProfileForm
          settings={settings}
          setSettings={setSettings}
          test={test}
          save={saveProfile}
          tested={tested}
          onClose={() => setProfileOpen(false)}
          t={evaluation}
          help={settingsCopy.profileForm}
        />
      </Modal>
    </>
  );
}
