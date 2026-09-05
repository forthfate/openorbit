import type { Improvement } from '../../domain/models'
import { DataTable, type Column } from '../../components/ui/data-table'
import { PanelHeader } from '../../components/ui/page-header'
import { StatusBadge } from '../../components/ui/status-badge'

const copy={en:{improvement:'Improvement',baseline:'Baseline',current:'Current',delta:'Δ success',commit:'Commit',pending:'pending',feedback:'AI feedback',panel:'PDCA and AI feedback',effect:'Improvement effect'},ko:{improvement:'개선사항',baseline:'기준',current:'현재',delta:'성공 변화',commit:'커밋',pending:'대기 중',feedback:'AI 피드백',panel:'PDCA 및 AI 피드백',effect:'개선 효과'},ja:{improvement:'改善項目',baseline:'基準',current:'現在',delta:'成功差分',commit:'コミット',pending:'保留中',feedback:'AIフィードバック',panel:'PDCAとAIフィードバック',effect:'改善効果'}}
export function ImprovementsPage({items}:{items:Improvement[]}){
  const stored=localStorage.getItem('orbit.locale'), t=copy[stored==='ko'||stored==='ja'?stored:'en']
  const columns:Column<Improvement>[]=[{id:'title',header:t.improvement,render:i=>i.title},{id:'pdca',header:'PDCA',render:i=><StatusBadge value={i.pdca}/>},{id:'baseline',header:t.baseline,render:i=>`${i.baseline_score}/10`},{id:'current',header:t.current,render:i=>`${i.current_score}/10`},{id:'delta',header:t.delta,render:i=>`${i.success_delta}%`},{id:'commit',header:t.commit,render:i=>i.commit??t.pending},{id:'feedback',header:t.feedback,render:i=>i.feedback}]
  return <><section className="panel improvement-panel"><PanelHeader title={t.panel}/><DataTable columns={columns} rows={items}/></section><section className="panel chart improvement-panel"><PanelHeader title={t.effect}/>{items.map(i=><div className="chart-row" key={i.id}><span>{i.title}</span><div><i style={{width:`${i.baseline_score*10}%`}}/><b style={{width:`${i.current_score*10}%`}}/></div><strong>+{i.success_delta}%</strong></div>)}</section></>
}
