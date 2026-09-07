import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  Braces,
  FileCode2,
  PanelLeftClose,
  Play,
  Settings,
  Sparkles,
} from "lucide-react";
import { SiGithub } from "react-icons/si";
import { useEffect, useState, type ReactNode } from "react";
import type { Page } from "../domain/models";
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
  children,
}: {
  page: Page;
  setPage: (page: Page) => void;
  locale: Locale;
  theme: string;
  headerAction?: ReactNode;
  activeRunCount?: number;
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
  const dashboardLinks = localeMessages<{
    repository: string;
    releases: string;
    openApi: string;
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
    </>
  );
  const activeRunLabel = activeRunCount > 99 ? "99+" : String(activeRunCount);
  useEffect(
    () => localStorage.setItem(sidebarStorageKey, String(collapsed)),
    [collapsed],
  );
  const sidebarLabel = collapsed ? "Expand navigation" : "Collapse navigation";
  return (
    <main
      className={collapsed ? "sidebar-collapsed" : undefined}
      data-theme={theme === "midnight" ? "midnight" : undefined}
    >
      <aside>
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
            aria-label="Expand navigation"
            title="Expand navigation"
            onClick={() => setCollapsed(false)}
          >
            <Sparkles size={20} />
          </button>
        ) : (
          <div className="brand">
            <Sparkles size={20} />
            <div>
              <span>OpenOrbit</span>
              <small>{__OPENORBIT_VERSION__}</small>
            </div>
          </div>
        )}
        <nav>
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
                  aria-label={`${activeRunCount} active runs`}
                >
                  {activeRunLabel}
                </span>
              )}
            </button>
          ))}
        </nav>
      </aside>
      <section className="content">
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
        {children}
        <footer>
          <span>© insighta cloud Inc.</span>
          <a
            className="github-link"
            href="https://github.com/forthfate/openorbit"
            target="_blank"
            rel="noreferrer"
            aria-label="OpenOrbit on GitHub"
            title="OpenOrbit GitHub repository"
          >
            <SiGithub size={18} />
          </a>
        </footer>
      </section>
      <ChatAssistant />
    </main>
  );
}
