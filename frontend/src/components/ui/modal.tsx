import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { locales, resolveLocale } from "../../locales";

export function Modal({
  open,
  title,
  onClose,
  children,
  className = "",
  headerActions,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  headerActions?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);
  if (!open) return null;
  const locale = resolveLocale(localStorage.getItem("orbit.locale")),
    close = locales[locale].ui.closeDialog;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`modal ${className}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <h2>{title}</h2>
          <div className="modal-header-actions">
            {headerActions}
            <button className="modal-close" aria-label={close} onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </header>
        {children}
      </section>
    </div>
  );
}
