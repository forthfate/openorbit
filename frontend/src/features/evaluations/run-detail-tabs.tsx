import type { ReactNode } from "react";
import { TooltipBox } from "../../components/ui/tooltip-box";

export type RunDetailTab =
  | "logs"
  | "supervisor"
  | "commits"
  | "result";

type Tab<T extends string> = { id: T; label: string };

export function RunDetailTabs<T extends string>({
  tabs,
  activeTab,
  onSelect,
}: {
  tabs: Tab<T>[];
  activeTab: T;
  onSelect: (tab: T) => void;
}) {
  return (
    <div className="run-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={activeTab === tab.id ? "active" : ""}
          onClick={() => onSelect(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function RunDetailTabPanel({
  description,
  hint,
  action,
  children,
}: {
  description: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="run-detail-tab-panel" role="tabpanel">
      {hint && <TooltipBox>{hint}</TooltipBox>}
      <div className="run-detail-tab-panel__intro">
        <p className="run-detail-tab-panel__description">{description}</p>
        {action}
      </div>
      {children}
    </section>
  );
}
