import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Braces,
  FileCode2,
  PanelLeftClose,
  Play,
  TriangleAlert,
  Settings,
  Sparkles,
} from "lucide-react";
import { SiGithub } from "react-icons/si";
import { useEffect, useState, type ReactNode } from "react";
import type { Page, SystemReadiness } from "../domain/models";
import type { Locale } from "../locales";
import { localeMessages, locales } from "../locales";
import { ChatAssistant } from "../components/chat-assistant";

const sidebarStorageKey = "orbit.sidebar.collapsed";

export function AppShell({
  page,
  setPage,
  locale,
  theme,
  headerAction,
  activeRunCount = 0,
  readiness,
  children,
}: {
  page: Page;
  setPage: (page: Page) => void;
  locale: Locale;
  theme: string;
  headerAction?: ReactNode;
  activeRunCount?: number;
  readiness: SystemReadiness | null;
  children: ReactNode;
}) {
  const t = locales[locale];
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(sidebarStorageKey) === "true",
  );
  const pageDescriptions = localeMessages<Record<Page, string>>(
    locale,
    "shell",
  );
  const appMeta = localeMessages<{ title: string; titleSeparator: string }>(
    locale,
    "appMeta",
  );
  const dashboardLinks = localeMessages<{
    repository: string;
    releases: string;
    openApi: string;
    sdkDocs: string;
  }>(locale, "dashboardLinks");
  const navigation: [Page, ReactNode, string][] = [
    ["dashboard", <Activity size={17} />, t.dashboard],
    ["assets", <Boxes size={17} />, t.assets],
    ["builds", <FileCode2 size={17} />, t.builds],
    ["runs", <Play size={17} />, t.runs],
    ["improvements", <BarChart3 size={17} />, t.improvements],
    ["settings", <Settings size={17} />, t.settings],
  ];
  const dashboardRepositoryLinks = page === "dashboard" && (
    <>
      <a
        className="dashboard-repository-link"
        href="https://github.com/forthfate/openorbit"
        target="_blank"
        rel="noreferrer"
      >
        <SiGithub size={16} />
        {dashboardLinks.repository}
      </a>
      <a
        className="dashboard-repository-link"
        href="https://github.com/forthfate/openorbit/releases"
        target="_blank"
        rel="noreferrer"
      >
        <BookOpen size={16} />
        {dashboardLinks.releases}
      </a>
      <a
        className="dashboard-repository-link"
        href="/api/docs"
        target="_blank"
        rel="noreferrer"
      >
        <Braces size={16} />
        {dashboardLinks.openApi}
      </a>
      <a
        className="dashboard-repository-link"
        href="/sdk-docs/sdk/"
        target="_blank"
        rel="noreferrer"
      >
        <BookOpen size={16} />
        {dashboardLinks.sdkDocs}
      </a>
    </>
  );
  const activeRunLabel = activeRunCount > 99 ? "99+" : String(activeRunCount);
  useEffect(
    () => localStorage.setItem(sidebarStorageKey, String(collapsed)),
    [collapsed],
  );
  useEffect(() => {
    document.title = `${appMeta.title}${appMeta.titleSeparator}${pageDescriptions[page]}`;
    document.documentElement.lang = locale;
  }, [appMeta, locale, page, pageDescriptions]);
  const navigationLabels = localeMessages<{
    expandNavigation: string;
    collapseNavigation: string;
    activeRuns: string;
    githubLabel: string;
    githubTitle: string;
  }>(locale, "navigationAccessibility");
  const readinessCopy = localeMessages<{
    title: string;
    description: string;
    openSettings: string;
    checks: Record<string, { title: string; details: Record<string, string> }>;
  }>(locale, "systemReadiness");
  const blockedChecks = readiness?.checks.filter((check) => check.status === "blocked") ?? [];
  const sidebarLabel = collapsed
    ? navigationLabels.expandNavigation
    : navigationLabels.collapseNavigation;
  return (
    <main
      className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}
      data-theme={theme === "midnight" ? "midnight" : undefined}
    >
      <aside className="app-sidebar">
        <button
          className="sidebar-toggle"
          type="button"
          aria-label={sidebarLabel}
          aria-expanded={!collapsed}
          title={sidebarLabel}
          onClick={() => setCollapsed((value) => !value)}
        >
          <PanelLeftClose size={18} />
        </button>
        {collapsed ? (
          <button
            className="brand brand--expand"
            type="button"
            aria-label={navigationLabels.expandNavigation}
            title={navigationLabels.expandNavigation}
            onClick={() => setCollapsed(false)}
          >
            <Sparkles size={20} />
          </button>
        ) : (
          <div className="brand">
            <Sparkles size={20} />
            <div>
              <span>{appMeta.title}</span>
              <small>{__OPENORBIT_VERSION__}</small>
            </div>
          </div>
        )}
        <nav className="app-navigation">
          {navigation.map(([id, icon, label]) => (
            <button
              className={page === id ? "active" : ""}
              onClick={() => setPage(id)}
              key={id}
              aria-label={label}
              title={collapsed ? label : undefined}
            >
              {icon}
              <span className="nav-label">{label}</span>
              {id === "runs" && activeRunCount > 0 && (
                <span
                  className="nav-run-count"
                  aria-label={navigationLabels.activeRuns.replace("{count}", String(activeRunCount))}
                >
                  {activeRunLabel}
                </span>
              )}
            </button>
          ))}
        </nav>
      </aside>
      <section className="app-content">
        <header>
          <div className="page-header-copy">
            <h1>{t[page]}</h1>
            <p className="sub">{pageDescriptions[page]}</p>
          </div>
          <div className="page-header-actions">
            {dashboardRepositoryLinks}
            {headerAction}
          </div>
        </header>
        {blockedChecks.length > 0 && (
          <section className="system-readiness-alert" role="alert" aria-live="polite">
            <TriangleAlert size={20} aria-hidden="true" />
            <div className="system-readiness-alert__copy">
              <strong>{readinessCopy.title}</strong>
              <p>{readinessCopy.description}</p>
              <ul>
                {blockedChecks.map((check) => {
                  const copy = readinessCopy.checks[check.id];
                  return <li key={check.id}><b>{copy?.title ?? check.id}</b>: {copy?.details[check.detail] ?? check.detail}</li>;
                })}
              </ul>
            </div>
            {blockedChecks.some((check) => check.settings_page === "settings") && (
              <button className="system-readiness-alert__action" type="button" onClick={() => setPage("settings")}>
                {readinessCopy.openSettings}
              </button>
            )}
          </section>
        )}
        {children}
        <footer>
          <span>© insighta cloud Inc.</span>
          <a
            className="github-link"
            href="https://github.com/forthfate/openorbit"
            target="_blank"
            rel="noreferrer"
            aria-label={navigationLabels.githubLabel}
            title={navigationLabels.githubTitle}
          >
            <SiGithub size={18} />
          </a>
        </footer>
      </section>
      <ChatAssistant />
    </main>
  );
}
