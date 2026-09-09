import type { ReactNode } from "react";

export function TooltipBox({ children }: { children: ReactNode }) {
  return <div className="tooltip-box">{children}</div>;
}
