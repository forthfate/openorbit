import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Dashboard, ImprovementAnalytics, OrbitLog } from '../../domain/models'
import { MetricCard } from '../../components/ui/page-header'
import { SectionInfo } from '../../components/ui/section-info'
import { StatusBadge } from '../../components/ui/status-badge'
import { locales, type Locale } from '../../locales'
import { api } from '../../services/api'

const hero={en:{title:'Operate, supervise, and improve recurring AI automations.',description:'Connect runners and workflows, retain observable evidence, and keep every automated action within a controlled operating flow.'},ko:{title:'AI가 수행하는 자동화 작업을 실행하고, 감독하고, 개선합니다.',description:'러너와 워크플로를 연결하고 관찰 가능한 증거를 남기며, 모든 자동화 작업을 통제된 운영 흐름 안에서 관리합니다.'},ja:{title:'AIによる自動化を実行し、監督し、改善します。',description:'ランナーとワークフローをつなぎ、観測可能な証跡を残しながら、すべての自動化を統制された運用フローで管理します。'}}
const operations={en:{title:'Evaluation health',description:'A 24-hour operating summary from retained supervisor evidence.',feedback:'Feedback',accepted:'Accepted',issues:'Reported issues',score:'Supervisor score',trend:'Feedback and accepted changes',none:'No supervisor feedback in the last 24 hours.',previous:'vs previous 24h'},ko:{title:'평가 운영 상태',description:'보존된 감독관 증거를 기준으로 한 최근 24시간 운영 요약입니다.',feedback:'피드백',accepted:'수용',issues:'보고된 문제',score:'감독관 점수',trend:'피드백 및 수용된 개선',none:'최근 24시간 감독관 피드백이 없습니다.',previous:'이전 24시간 대비'},ja:{title:'評価の運用状態',description:'保持された監督者の証跡に基づく直近24時間の運用サマリーです。',feedback:'フィードバック',accepted:'受容',issues:'報告された問題',score:'監督者スコア',trend:'フィードバックと受容済み改善',none:'直近24時間の監督者フィードバックはありません。',previous:'前の24時間比'}}
const dashboardHelp={en:{trend:'Compare hourly supervisor feedback with the improvements accepted during the same period.',logs:'Review recorded Orbit events, including operational messages and errors.'},ko:{trend:'시간대별 감독관 피드백과 같은 기간에 수용된 개선을 비교합니다.',logs:'운영 메시지와 오류를 포함한 Orbit 이벤트 기록을 확인합니다.'},ja:{trend:'時間帯ごとの監督者フィードバックと、同じ期間に受容された改善を比較します。',logs:'運用メッセージとエラーを含む Orbit イベントの記録を確認します。'}}

function relativeRunTime(value:string|undefined,locale:Locale){
  if(!value)return '—'
  const elapsed=Math.max(0,Date.now()-new Date(value).getTime()),minutes=Math.floor(elapsed/60000)
  const [amount,unit]=minutes<60?[minutes,'minute'] as const:minutes<1440?[Math.floor(minutes/60),'hour'] as const:[Math.floor(minutes/1440),'day'] as const
  return new Intl.RelativeTimeFormat(locale==='ko'?'ko-KR':locale==='ja'?'ja-JP':'en-US',{numeric:'auto'}).format(-amount,unit)
}

function OperationalHealth({locale}:{locale:Locale}){
  const [analytics,setAnalytics]=useState<ImprovementAnalytics>()
  useEffect(()=>{const refresh=()=>api<ImprovementAnalytics>('/api/improvement-analytics?hours=24').then(setAnalytics).catch(()=>setAnalytics(undefined));refresh();const timer=window.setInterval(refresh,15000);return()=>window.clearInterval(timer)},[])
  const copy=operations[locale],help=dashboardHelp[locale],summary=analytics?.operational_summary
  const trend=useMemo(()=>{
    const grouped=new Map<string,{time:string;feedback:number;accepted:number}>()
    for(const item of analytics?.iteration_trends??[])for(const point of item.points){
      const time=new Date(point.recorded_at).toISOString().slice(0,13)
      const row=grouped.get(time)??{time,feedback:0,accepted:0}
      row.feedback+=point.feedback_count;row.accepted+=point.accepted_count;grouped.set(time,row)
    }
    return [...grouped.values()].sort((a,b)=>a.time.localeCompare(b.time))
  },[analytics])
  const score=summary?.average_score===null||summary?.average_score===undefined?'—':`${summary.average_score}/10`
  const delta=summary?.score_delta===null||summary?.score_delta===undefined?'':` ${summary.score_delta>0?'+':''}${summary.score_delta}`
  return <section className="panel dashboard-health"><div className="panel-head"><div><p className="eyebrow">IMPROVEMENT RESULTS</p><h2><SectionInfo title={copy.title} description={copy.description}/></h2><p className="hint">{copy.description}</p></div></div><div className="dashboard-health-metrics"><MetricCard label={copy.feedback} value={`${summary?.feedback??0}`}/><MetricCard label={copy.accepted} value={`${summary?.accepted??0}`}/><MetricCard label={copy.issues} value={`${summary?.issues??0}`}/><MetricCard label={copy.score} value={score} detail={delta?`${delta} ${copy.previous}`:undefined}/></div><article className="dashboard-feedback-chart"><h3><SectionInfo title={copy.trend} description={help.trend}/></h3>{trend.length?<ResponsiveContainer width="100%" height={180}><BarChart data={trend} margin={{left:-20}}><CartesianGrid vertical={false}/><XAxis dataKey="time" tickFormatter={value=>new Date(`${value}:00:00Z`).toLocaleTimeString(locale==='ko'?'ko-KR':locale==='ja'?'ja-JP':'en-US',{hour:'2-digit',minute:'2-digit'})}/><YAxis allowDecimals={false}/><Tooltip labelFormatter={value=>new Date(`${String(value)}:00:00Z`).toLocaleString()}/><Legend/><Bar dataKey="feedback" name={copy.feedback} fill="#f1d292" radius={[4,4,0,0]}/><Bar dataKey="accepted" name={copy.accepted} fill="#79c99e" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer>:<p className="hint">{copy.none}</p>}</article></section>
}

export function DashboardPage({data,logs,onOpenBuild,onOpenRun,locale}:{data:Dashboard|null;logs:OrbitLog[];onOpenBuild:(id?:string)=>void;onOpenRun:()=>void;locale:Locale}){
  const t=locales[locale].common,h=hero[locale],help=dashboardHelp[locale],recent=data?.recent_runs??[],errors=recent.filter(run=>run.status==='failed').length
  const openBuild=(id?:string)=>{if(id)sessionStorage.setItem('orbit.selectedBuild',id);onOpenBuild(id)}
  return <><section className="dashboard-hero"><p>ORBIT CONTROL PLANE</p><strong>{h.title}</strong><span>{h.description}</span></section><div className="metrics"><MetricCard label={t.totalEval} value={`${data?.metrics.evaluation_builds??0}`}/><MetricCard label={t.completedEval} value={`${data?.metrics.completed_evaluations??0}`}/><MetricCard label={t.totalRunning} value={`${data?.active_runs.length??0}`}/><MetricCard label={t.totalError} value={`${errors}`}/></div><section className="recent-evaluations">{recent.map(run=>{const active=['queued','running','awaiting_approval'].includes(run.status),completed=['succeeded','failed','cancelled'].includes(run.status),eventTime=completed?run.finished_at:run.created_at,eventLabel=completed?(locale==='ko'?'완료':locale==='ja'?'完了':'Completed'):(locale==='ko'?'생성':locale==='ja'?'作成':'Created');return <button className="evaluation-card" key={run.id} onClick={()=>active?onOpenRun():openBuild(run.evaluation_build_id)}><small>{`${eventLabel} · ${relativeRunTime(eventTime,locale)}`}</small><strong>{run.evaluation_build_name??run.workflow_name}</strong><span>{run.current_phase??run.status}</span><StatusBadge value={run.status}/></button>})}</section><OperationalHealth locale={locale}/><section className="panel orbit-log-panel"><div className="panel-head"><div><p className="eyebrow">ORBIT</p><h2><SectionInfo title={locale==='ko'?'Orbit 운영 로그':locale==='ja'?'Orbit 運用ログ':'Orbit operational logs'} description={help.logs}/></h2></div></div><div className="orbit-log-output">{logs.length?logs.map((log,index)=><div key={`${log.time}-${index}`} className={log.status==='ERROR'?'error-log':''}><time>{log.time?new Date(log.time).toLocaleTimeString():'—'}</time><strong>{log.name}</strong><span>{log.message||log.status}</span></div>):<p className="hint">No Orbit events recorded yet.</p>}</div></section></>
}
