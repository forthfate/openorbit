import { useEffect, useState } from "react";
import { AlertTriangle, Pencil, Plus, Trash2 } from "lucide-react";
import type { Locale } from "../../locales";
import { localeMessages, localeOptions, locales } from "../../locales";
import { Modal } from "../../components/ui/modal";
import { PanelHeader } from "../../components/ui/page-header";
import type { Settings } from "../../domain/models";
import { api } from "../../services/api";
import { useToast } from "../../components/ui/toast-context";
import { ProfileForm, type ProfileFormCopy } from "../evaluation-builds/page";

type ApplicationSettings = {
  manager_prompt_template: string;
  chat_model_profile_name: string;
};

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
type SettingsCopy = { manager: ManagerCopy; profiles: ProfileCopy; profileForm: ProfileFormCopy };

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
  onDeleteProfile: (profileName: string) => void;
}) {
  const t = locales[locale].common,
    settingsCopy = localeMessages<SettingsCopy>(locale, "settingsPage"),
    l = settingsCopy.manager,
    p = settingsCopy.profiles,
    evaluation = locales[locale].evaluation;
  const [prompt, setPrompt] = useState(""),
    [chatProfile, setChatProfile] = useState(""),
    [open, setOpen] = useState(false),
    [profileOpen, setProfileOpen] = useState(false);
  const { pushToast } = useToast();
  useEffect(() => {
    api<ApplicationSettings>("/api/application-settings")
      .then((values) => {
        setPrompt(values.manager_prompt_template);
        setChatProfile(values.chat_model_profile_name);
      })
      .catch(() => pushToast("Unable to load operational prompt."));
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
  return (
    <>
      <section className="panel app-settings">
        <PanelHeader title={t.applicationSettings} />
        <label className="setting-row">
          <span>
            <strong>{t.language}</strong>
            <small>{t.languageHint}</small>
          </span>
          <select
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
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
          <PanelHeader title={p.title} />
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
        <PanelHeader title={p.chatProfile} description={p.chatProfileHint} />
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
          <PanelHeader title={l.title} />
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
