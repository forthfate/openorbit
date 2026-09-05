import type { Dashboard, OrbitLog } from '../../domain/models'
import { MetricCard } from '../../components/ui/page-header'
import { StatusBadge } from '../../components/ui/status-badge'
import { locales, type Locale } from '../../locales'

const hero={en:{title:'Operate, supervise, and improve recurring AI automations.',description:'Connect runners and workflows, retain observable evidence, and keep every automated action within a controlled operating flow.'},ko:{title:'AI가 수행하는 자동화 작업을 실행하고, 감독하고, 개선합니다.',description:'러너와 워크플로를 연결하고 관찰 가능한 증거를 남기며, 모든 자동화 작업을 통제된 운영 흐름 안에서 관리합니다.'},ja:{title:'AIによる自動化を実行し、監督し、改善します。',description:'ランナーとワークフローをつなぎ、観測可能な証跡を残しながら、すべての自動化を統制された運用フローで管理します。'}}

function relativeRunTime(value:string|undefined,locale:Locale){
  if(!value)return '—'
  const elapsed=Math.max(0,Date.now()-new Date(value).getTime()),minutes=Math.floor(elapsed/60000)
  const [amount,unit]=minutes<60?[minutes,'minute'] as const:minutes<1440?[Math.floor(minutes/60),'hour'] as const:[Math.floor(minutes/1440),'day'] as const
  return new Intl.RelativeTimeFormat(locale==='ko'?'ko-KR':locale==='ja'?'ja-JP':'en-US',{numeric:'auto'}).format(-amount,unit)
}

export function DashboardPage({data,logs,onOpenBuild,onOpenRun,locale}:{data:Dashboard|null;logs:OrbitLog[];onOpenBuild:(id?:string)=>void;onOpenRun:()=>void;locale:Locale}){
  const t=locales[locale].common,h=hero[locale],recent=data?.recent_runs??[],errors=recent.filter(run=>run.status==='failed').length
  const openBuild=(id?:string)=>{if(id)sessionStorage.setItem('orbit.selectedBuild',id);onOpenBuild(id)}
  return <><section className="dashboard-hero"><p>ORBIT CONTROL PLANE</p><strong>{h.title}</strong><span>{h.description}</span></section><div className="metrics"><MetricCard label={t.totalEval} value={`${data?.metrics.evaluation_builds??0}`}/><MetricCard label={t.completedEval} value={`${data?.metrics.completed_evaluations??0}`}/><MetricCard label={t.totalRunning} value={`${data?.active_runs.length??0}`}/><MetricCard label={t.totalError} value={`${errors}`}/></div><section className="recent-evaluations">{recent.map(run=>{const active=['queued','running','awaiting_approval'].includes(run.status),completed=['succeeded','failed','cancelled'].includes(run.status),eventTime=completed?run.finished_at:run.created_at,eventLabel=completed?(locale==='ko'?'완료':locale==='ja'?'完了':'Completed'):(locale==='ko'?'생성':locale==='ja'?'作成':'Created');return <button className="evaluation-card" key={run.id} onClick={()=>active?onOpenRun():openBuild(run.evaluation_build_id)}><small>{`${eventLabel} · ${relativeRunTime(eventTime,locale)}`}</small><strong>{run.evaluation_build_name??run.workflow_name}</strong><span>{run.current_phase??run.status}</span><StatusBadge value={run.status}/></button>})}</section><section className="panel orbit-log-panel"><div className="panel-head"><div><p className="eyebrow">ORBIT</p><h2>{locale==='ko'?'Orbit 운영 로그':'Orbit operational logs'}</h2></div></div><div className="orbit-log-output">{logs.length?logs.map((log,index)=><div key={`${log.time}-${index}`} className={log.status==='ERROR'?'error-log':''}><time>{log.time?new Date(log.time).toLocaleTimeString():'—'}</time><strong>{log.name}</strong><span>{log.message||log.status}</span></div>):<p className="hint">No Orbit events recorded yet.</p>}</div></section></>
}
