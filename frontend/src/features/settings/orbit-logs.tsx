import type { OrbitLog } from "../../domain/models";
import { intlLocales, localeMessages, type Locale } from "../../locales";
import { SectionInfo } from "../../components/ui/section-info";

type OrbitLogsCopy = { title: string; description: string; empty: string };

export function OrbitLogs({ logs, locale }: { logs: OrbitLog[]; locale: Locale }) {
  const t = localeMessages<OrbitLogsCopy>(locale, "settingsLogs"), sectionDetails = localeMessages<Record<string, string>>(locale, "sectionDetails");
  return (
    <section className="panel orbit-log-panel">
      <div className="panel-head">
        <div>
          <h2><SectionInfo title={t.title} description={sectionDetails.orbitLogs} /></h2>
          <p className="hint section-description">{t.description}</p>
        </div>
      </div>
      <div className="orbit-log-output">
        {logs.length ? logs.map((log, index) => (
          <div key={`${log.time}-${index}`} className={log.status === "ERROR" ? "error-log" : ""}>
            <time>{log.time ? new Date(log.time).toLocaleTimeString(intlLocales[locale]) : "—"}</time>
            <strong>{log.name}</strong>
            <span>{log.message || log.status}</span>
          </div>
        )) : <p className="hint">{t.empty}</p>}
      </div>
    </section>
  );
}
