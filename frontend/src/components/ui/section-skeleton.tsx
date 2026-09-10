import { Skeleton } from "./skeleton";

export function SectionSkeleton({ rows = 3, metrics = false, chart = false }: { rows?: number; metrics?: boolean; chart?: boolean }) {
  return <section className="panel section-skeleton" role="status" aria-label="Loading section">
    <Skeleton className="section-skeleton__title" />
    <Skeleton className="section-skeleton__hint" />
    {metrics ? <div className="section-skeleton__metrics">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="section-skeleton__metric" />)}</div> : <div className="section-skeleton__rows">{Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="section-skeleton__row" />)}</div>}
    {chart && <Skeleton className="section-skeleton__chart" />}
  </section>;
}
