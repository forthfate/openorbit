import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./app/app-shell";
import { ConfirmDialog } from "./components/ui/confirm-dialog";
import { ToastProvider } from "./components/ui/toast";
import { SectionSkeleton } from "./components/ui/section-skeleton";
import type { Page, Run } from "./domain/models";
import { DashboardPage } from "./features/dashboard/page";
import { AssetsPage } from "./features/assets/page";
import { BuildsPage } from "./features/builds/page";
import { EvaluationsPage } from "./features/evaluations/page";
import { ImprovementsPage } from "./features/improvements/page";
import { SettingsPage } from "./features/settings/page";
import { localeMessages, locales, resolveLocale, type Locale } from "./locales";
import { api } from "./services/api";
import { useControlRoom } from "./services/use-control-room";
import "./styles.css";
import "./theme-overrides.css";

const localeStorageKey = "orbit.locale";
const savedLocale = (): Locale => {
  return resolveLocale(localStorage.getItem(localeStorageKey));
};
const themeStorageKey = "orbit.theme";
const savedTheme = () =>
  localStorage.getItem(themeStorageKey) === "forest" ? "forest" : "midnight";
const pages: Page[] = [
  "dashboard",
  "assets",
  "builds",
  "runs",
  "improvements",
  "settings",
];
const pageFromHash = (): Page => {
  const page = window.location.hash.slice(1);
  return pages.includes(page as Page) ? (page as Page) : "dashboard";
};
type ConfirmCopy = {
  title: string;
  description: string;
  cancel: string;
  confirm: string;
};

export default function App() {
  const [page, setPageState] = useState<Page>(pageFromHash);
  const [locale, setLocaleState] = useState<Locale>(savedLocale);
  const [theme, setThemeState] = useState(savedTheme);
  const [deletingBuild, setDeletingBuild] = useState<string | null>(null);
  const [confirmingEmergencyStop, setConfirmingEmergencyStop] = useState(false);
  const [quickStartRequest, setQuickStartRequest] = useState(0);
  const [quickStartSelection, setQuickStartSelection] = useState<string>();
  const room = useControlRoom();
  const ui = locales[locale].ui;
  useEffect(() => {
    const sync = () => setPageState(pageFromHash());
    if (!window.location.hash)
      window.history.replaceState(null, "", "#dashboard");
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const setPage = (next: Page) => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    if (window.location.hash === `#${next}`) setPageState(next);
    else window.location.hash = next;
  };
  const setLocale = (value: Locale) => {
    localStorage.setItem(localeStorageKey, value);
    setLocaleState(value);
  };
  const setTheme = (value: string) => {
    localStorage.setItem(themeStorageKey, value);
    setThemeState(value);
  };
  const openQuickStart = (id?: string) => {
    setQuickStartSelection(id);
    setQuickStartRequest((value) => value + 1);
    setPage("builds");
  };
  const test = () =>
    api<{ response: string }>("/api/settings/hello", "POST", room.settings)
      .then((r) => {
        room.setSettingsTested(true);
        room.setNotice(`Test succeeded: ${r.response}`, "success");
      })
      .catch((e) => room.setNotice(e.message));
  const stop = () =>
    api("/api/runs/emergency-stop", "POST")
      .then(() => {
        room.setNotice(ui.allRunsStopped, "warning");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const confirmEmergencyStop = () => {
    setConfirmingEmergencyStop(false);
    stop();
  };
  const stopRun = (id: string) =>
    api(`/api/runs/${id}/cancel`, "POST")
      .then(() => {
        room.setNotice(ui.evaluationStopped, "warning");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const retryRun = (id: string, restartFromFirst: boolean) =>
    api(`/api/runs/${id}/retry`, "POST", { restart_from_first: restartFromFirst })
      .then(() => {
        room.setNotice("Evaluation retry started.", "warning");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const deleteRuns = (ids: string[]) =>
    Promise.all(
      ids.map((id) => api(`/api/runs/${encodeURIComponent(id)}`, "DELETE")),
    )
      .then(() => {
        room.setNotice(
          `${ids.length} run${ids.length === 1 ? "" : "s"} deleted`,
          "success",
        );
        return room.refresh();
      })
      .catch((e) => {
        room.setNotice(e.message);
        throw e;
      });
  const approveRun = (id: string) =>
    api(`/api/runs/${id}/approve`, "POST")
      .then(() => {
        room.setNotice(ui.evaluationApproved, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const rejectRun = (id: string) =>
    api(`/api/runs/${id}/reject`, "POST")
      .then(() => {
        room.setNotice(ui.evaluationRejected, "warning");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const save = () => {
    return api("/api/settings", "PUT", room.settings).then(() => {
      room.setSettingsTested(false);
      room.setNotice(ui.aiSettingsSaved, "success");
      return room.refresh();
    });
  };
  const invoke = (id: string) =>
    api(`/api/builds/${id}/runs`, "POST")
      .then(() => {
        room.setNotice(ui.evaluationStarted, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const testBuild = (id: string) =>
    api<Run>(`/api/builds/${id}/tests`, "POST")
      .then((run) => {
        room.setNotice(ui.evaluationTestStarted, "success");
        return run;
      })
      .catch((e) => {
        room.setNotice(e.message);
        throw e;
      });
  const createBuild = (values: unknown) =>
    api("/api/builds", "POST", values)
      .then(() => {
        room.setNotice(ui.buildCreated, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const createQuickStart = (id: string, inputs: Record<string, string>) =>
    api(`/api/quick-starts/${encodeURIComponent(id)}/instantiate`, "POST", {
      inputs,
    })
      .then(() => {
        room.setNotice(ui.quickStartCreated, "success");
        return room.refresh();
      })
      .catch((e) => {
        room.setNotice(e.message);
        throw e;
      });
  const updateBuild = (id: string, values: unknown) =>
    api(`/api/builds/${id}`, "PUT", values)
      .then(() => {
        room.setNotice(ui.buildUpdated, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  const deleteAsset = (
    kind:
      | "profile"
      | "template"
      | "test-set"
      | "runner"
      | "workflow"
      | "execution-environment"
      | "target-environment",
    id: string,
  ) => {
    const path = {
      profile: `/api/settings/profiles/${encodeURIComponent(id)}`,
      template: `/api/prompt-templates/${id}`,
      "test-set": `/api/target-test-case-sets/${id}`,
      runner: `/api/runners/${id}`,
      workflow: `/api/workflows/${id}`,
      "execution-environment": `/api/execution-environments/${id}`,
      "target-environment": `/api/target-environments/${id}`,
    }[kind];
    api(path, "DELETE")
      .then(() => {
        room.setNotice(ui.assetDeleted, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  };
  const deleteBuild = (id: string) => setDeletingBuild(id);
  const confirmDeleteBuild = () => {
    if (!deletingBuild) return;
    const id = deletingBuild;
    setDeletingBuild(null);
    api(`/api/builds/${id}`, "DELETE")
      .then(() => {
        room.setNotice(ui.buildDeleted, "success");
        room.refresh();
      })
      .catch((e) => room.setNotice(e.message));
  };
  const createWorkflow = (values: unknown) =>
    api("/api/workflows/clone", "POST", values).then(() => room.refresh());
  const updateWorkflow = (id: string, values: unknown) =>
    api(`/api/workflows/${id}`, "PUT", values).then(() => room.refresh());
  const content = {
    dashboard: (
      <DashboardPage
        data={room.data}
        loading={room.loading}
        locale={locale}
        onOpenRun={() => setPage("runs")}
        onOpenBuild={() => setPage("builds")}
        onOpenQuickStart={openQuickStart}
      />
    ),
    assets: (
      <AssetsPage
        locale={locale}
        workflows={room.workflows}
        runners={room.runners}
        promptTemplates={room.promptTemplates}
        testCaseSets={room.testCaseSets}
        executionEnvironments={room.executionEnvironments}
        targetEnvironments={room.targetEnvironments}
        profiles={room.profiles}
        loading={room.loading}
        settings={room.settings}
        setSettings={room.setSettings}
        test={test}
        save={save}
        tested={room.settingsTested}
        onRefresh={room.refresh}
        onCreateWorkflow={createWorkflow}
        onUpdateWorkflow={updateWorkflow}
        onDelete={deleteAsset}
      />
    ),
    builds: (
      room.loading ? <SectionSkeleton rows={6} /> : <BuildsPage
        locale={locale}
        builds={room.builds}
        runners={room.runners}
        profiles={room.profiles}
        promptTemplates={room.promptTemplates}
        testCaseSets={room.testCaseSets}
        executionEnvironments={room.executionEnvironments}
        targetEnvironments={room.targetEnvironments}
        onInvoke={invoke}
        onTest={testBuild}
        onCreate={createBuild}
        onUpdate={updateBuild}
        onDelete={deleteBuild}
        onQuickStartCreate={createQuickStart}
        quickStartRequest={quickStartRequest}
        quickStartSelection={quickStartSelection}
        onQuickStartRequestHandled={() => {
          setQuickStartRequest(0);
          setQuickStartSelection(undefined);
        }}
      />
    ),
    runs: (
      room.loading ? <SectionSkeleton rows={7} /> : <EvaluationsPage
        locale={locale}
        runs={room.runs}
        onStop={stopRun}
        onRetry={retryRun}
        onApprove={approveRun}
        onReject={rejectRun}
        onEmergencyStop={() => setConfirmingEmergencyStop(true)}
        onDeleteRuns={deleteRuns}
      />
    ),
    improvements: <ImprovementsPage />,
    settings: (
      room.loading ? <>
        <SectionSkeleton rows={2} />
        <SectionSkeleton rows={2} />
        <SectionSkeleton rows={3} />
        <SectionSkeleton rows={1} />
        <SectionSkeleton rows={3} />
        <SectionSkeleton rows={4} />
      </> : <SettingsPage
        locale={locale}
        setLocale={setLocale}
        theme={theme}
        setTheme={setTheme}
        profiles={room.profiles}
        settings={room.settings}
        setSettings={room.setSettings}
        test={test}
        save={save}
        tested={room.settingsTested}
        logs={room.orbitLogs}
        onDeleteProfile={(id) => deleteAsset("profile", id)}
      />
    ),
  }[page];
  const confirmations = localeMessages<{
    deleteBuild: ConfirmCopy;
    emergencyStop: ConfirmCopy;
  }>(locale, "confirmations");
  const confirmation = confirmations.deleteBuild;
  const emergencyConfirmation = confirmations.emergencyStop;
  return (
    <AppShell
      page={page}
      setPage={setPage}
      locale={locale}
      theme={theme}
      activeRunCount={
        room.runs.filter((run) =>
          ["queued", "awaiting_approval", "running"].includes(run.status),
        ).length
      }
    >
      <div className="page-stack">{content}</div>
      <ConfirmDialog
        open={deletingBuild !== null}
        title={confirmation.title}
        description={confirmation.description}
        cancelLabel={confirmation.cancel}
        confirmLabel={confirmation.confirm}
        onCancel={() => setDeletingBuild(null)}
        onConfirm={confirmDeleteBuild}
      />
      <ConfirmDialog
        open={confirmingEmergencyStop}
        title={emergencyConfirmation.title}
        description={emergencyConfirmation.description}
        cancelLabel={emergencyConfirmation.cancel}
        confirmLabel={emergencyConfirmation.confirm}
        onCancel={() => setConfirmingEmergencyStop(false)}
        onConfirm={confirmEmergencyStop}
      />
    </AppShell>
  );
}

createRoot(document.getElementById("root")!).render(
  <ToastProvider>
    <App />
  </ToastProvider>,
);
