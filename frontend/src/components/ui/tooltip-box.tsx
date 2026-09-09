import { CircleHelp } from "lucide-react";
import type { ReactNode } from "react";

export function TooltipBox({ children }: { children: ReactNode }) {
  return (
    <div className="tooltip-box" role="note">
      <CircleHelp aria-hidden="true" size={16} />
      <span>{children}</span>
    </div>
  );
}
