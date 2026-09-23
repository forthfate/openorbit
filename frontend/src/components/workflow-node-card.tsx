import { forwardRef, type ReactNode } from "react";

export type WorkflowNodeCardProps = {
  className: string;
  title: string;
  inputs?: string[];
  outputs?: string[];
  description?: string | null;
  leading?: ReactNode;
  trailing?: ReactNode;
};

export const WorkflowNodeCard = forwardRef<HTMLDivElement, WorkflowNodeCardProps>(
  ({ className, title, inputs, outputs, description, leading, trailing }, ref) => (
    <div ref={ref} className={className}>
      {leading}
      <header style={{ margin: 0 }}><small>Function</small><strong>{title}</strong></header>
      {description && <p>{description}</p>}
      <footer style={{ margin: 0 }}>{inputs?.map((port) => <span key={port}>← {port}</span>)}{outputs?.map((port) => <span key={port}>{port} →</span>)}</footer>
      {trailing}
    </div>
  ),
);

WorkflowNodeCard.displayName = "WorkflowNodeCard";
