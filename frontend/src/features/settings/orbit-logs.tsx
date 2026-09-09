import type { OrbitLog } from "../../domain/models";
import { SectionInfo } from "../../components/ui/section-info";
import { localeMessages, type Locale } from "../../locales";

type OrbitLogsCopy = { title: string; description: string; empty: string };

export function OrbitLogs({ logs, locale }: { logs: OrbitLog[]; locale: Locale }) {
  const t = localeMessages<OrbitLogsCopy>(locale, "settingsLogs");
  return (
    <section className="panel orbit-log-panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">ORBIT</p>
          <h2><SectionInfo title={t.title} description={t.description} /></h2>
          <p className="hint">{t.description}</p>
        </div>
      </div>
      <div className="orbit-log-output">
        {logs.length ? logs.map((log, index) => (
          <div key={`${log.time}-${index}`} className={log.status === "ERROR" ? "error-log" : ""}>
            <time>{log.time ? new Date(log.time).toLocaleTimeString() : "—"}</time>
            <strong>{log.name}</strong>
            <span>{log.message || log.status}</span>
          </div>
        )) : <p className="hint">{t.empty}</p>}
      </div>
    </section>
  );
}
