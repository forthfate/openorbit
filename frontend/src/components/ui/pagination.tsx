import { locales, type Locale } from "../../locales";

export function Pagination({
  locale,
  page,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
}: {
  locale: Locale;
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const range = totalItems ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, totalItems)} / ${totalItems}` : "0";
  const ui = locales[locale].ui;
  return <div className="run-pagination"><span>{range}</span><div><button className="ghost" disabled={page===1} onClick={()=>onPageChange(page-1)}>{ui.previous}</button><span>{page} / {totalPages}</span><button className="ghost" disabled={page===totalPages} onClick={()=>onPageChange(page+1)}>{ui.next}</button></div></div>;
}
