import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
export type Column<Row> = {
  id: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  sortValue?: (row: Row) => string | number | boolean | null | undefined;
};
import { locales, resolveLocale } from "../../locales";
export function DataTable<Row extends { id: string }>({
  columns,
  rows,
  empty,
  className = "",
  gridTemplateColumns,
  onRowClick,
}: {
  columns: Column<Row>[];
  rows: Row[];
  empty?: string;
  className?: string;
  gridTemplateColumns?: string;
  onRowClick?: (row: Row) => void;
}) {
  const template =
      gridTemplateColumns ?? `repeat(${columns.length},minmax(120px,1fr))`,
    locale = resolveLocale(localStorage.getItem("orbit.locale")),
    [sort, setSort] = useState<{ id: string; direction: "asc" | "desc" } | null>(null),
    sortedRows = useMemo(() => {
      if (!sort) return rows;
      const column = columns.find((item) => item.id === sort.id);
      if (!column?.sortValue) return rows;
      return [...rows].sort((left, right) => {
        const a = column.sortValue!(left), b = column.sortValue!(right);
        if (a == null) return b == null ? 0 : 1;
        if (b == null) return -1;
        const comparison = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
        return sort.direction === "asc" ? comparison : -comparison;
      });
    }, [columns, rows, sort]);
  return (
    <div className={`table ${className}`}>
      <div className="tr th" style={{ gridTemplateColumns: template }}>
        {columns.map((c) => {
          const active = sort?.id === c.id;
          if (!c.sortValue) return <span key={c.id}>{c.header}</span>;
          const Icon = active ? (sort.direction === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
          return <span key={c.id}><button className="table-sort" type="button" onClick={() => setSort(current => current?.id === c.id ? { id: c.id, direction: current.direction === "asc" ? "desc" : "asc" } : { id: c.id, direction: "asc" })} aria-label={`Sort by ${String(c.header)}`} aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>{c.header}<Icon size={13} aria-hidden="true" /></button></span>;
        })}
      </div>
      {sortedRows.length ? (
        sortedRows.map((row) => (
          <div
            className={`tr${onRowClick ? " tr--interactive" : ""}`}
            style={{ gridTemplateColumns: template }}
            key={row.id}
            onClick={(event) => {
              if (
                !(event.target as HTMLElement).closest(
                  "button,input,select,textarea",
                )
              )
                onRowClick?.(row);
            }}
          >
            {columns.map((c) => (
              <span key={c.id}>{c.render(row)}</span>
            ))}
          </div>
        ))
      ) : (
        <div className="empty">{empty ?? locales[locale].ui.emptyEntries}</div>
      )}
    </div>
  );
}
