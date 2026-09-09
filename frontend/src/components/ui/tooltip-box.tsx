import type { ReactNode } from "react";

export function TooltipBox({ children }: { children: ReactNode }) {
  return <aside className="tooltip-box">{children}</aside>;
}
