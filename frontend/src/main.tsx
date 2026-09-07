import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AppShell } from './app/app-shell'
import { ConfirmDialog } from './components/ui/confirm-dialog'
import { ToastProvider } from './components/ui/toast'
import type { Page } from './domain/models'
import { DashboardPage } from './features/dashboard/page'
import { AssetsPage } from './features/assets/page'
import { EvaluationBuildsPage } from './features/evaluation-builds/page'
import { EvaluationsPage } from './features/evaluations/page'
import { ImprovementsPage } from './features/improvements/page'
import { SettingsPage } from './features/settings/page'
import { type Locale } from './locales'
import { api } from './services/api'
import { useControlRoom } from './services/use-control-room'
import './styles.css'
import './theme-overrides.css'

const localeStorageKey='orbit.locale'
const savedLocale=():Locale=>{const value=localStorage.getItem(localeStorageKey);return value==='ko'||value==='en'||value==='ja'?value:'en'}
const themeStorageKey='orbit.theme'
const savedTheme=()=>localStorage.getItem(themeStorageKey)==='forest'?'forest':'midnight'
const pages:Page[]=['dashboard','assets','builds','runs','improvements','settings']
const pageFromHash=():Page=>{const page=window.location.hash.slice(1);return pages.includes(page as Page)?page as Page:'dashboard'}

export default function App(){
  const [page,setPageState]=useState<Page>(pageFromHash)
  const [locale,setLocaleState]=useState<Locale>(savedLocale)
  const [theme,setThemeState]=useState(savedTheme)
  const [deletingBuild,setDeletingBuild]=useState<string|null>(null)
  const [confirmingEmergencyStop,setConfirmingEmergencyStop]=useState(false)
  const room=useControlRoom()
  useEffect(()=>{const sync=()=>setPageState(pageFromHash());if(!window.location.hash)window.history.replaceState(null,'','#dashboard');window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync)},[])
  const setPage=(next:Page)=>{if(window.location.hash===`#${next}`)setPageState(next);else window.location.hash=next}
  const setLocale=(value:Locale)=>{localStorage.setItem(localeStorageKey,value);setLocaleState(value)}
  const setTheme=(value:string)=>{localStorage.setItem(themeStorageKey,value);setThemeState(value)}
  const test=()=>api<{response:string}>('/api/settings/hello','POST',room.settings).then(r=>{room.setSettingsTested(true);room.setNotice(`Test succeeded: ${r.response}`,'success')}).catch(e=>room.setNotice(e.message))
  const stop=()=>api('/api/runs/emergency-stop','POST').then(()=>{room.setNotice('All active runs stopped','warning');room.refresh()}).catch(e=>room.setNotice(e.message))
  const confirmEmergencyStop=()=>{setConfirmingEmergencyStop(false);stop()}
  const stopRun=(id:string)=>api(`/api/runs/${id}/cancel`,'POST').then(()=>{room.setNotice('Evaluation stopped','warning');room.refresh()}).catch(e=>room.setNotice(e.message))
  const deleteRuns=(ids:string[])=>Promise.all(ids.map(id=>api(`/api/runs/${encodeURIComponent(id)}`,'DELETE'))).then(()=>{room.setNotice(`${ids.length} evaluation run${ids.length===1?'':'s'} deleted`,'success');return room.refresh()}).catch(e=>{room.setNotice(e.message);throw e})
  const approveRun=(id:string)=>api(`/api/runs/${id}/approve`,'POST').then(()=>{room.setNotice('Evaluation approved','success');room.refresh()}).catch(e=>room.setNotice(e.message))
  const rejectRun=(id:string)=>api(`/api/runs/${id}/reject`,'POST').then(()=>{room.setNotice('Evaluation rejected','warning');room.refresh()}).catch(e=>room.setNotice(e.message))
  const save=()=>{if(!room.settingsTested){const error=new Error('Test the configuration before saving.');room.setNotice(error.message,'warning');return Promise.reject(error)}return api('/api/settings','PUT',room.settings).then(()=>{room.setSettingsTested(false);room.setNotice('AI settings saved','success');return room.refresh()})}
  const invoke=(id:string)=>api(`/api/evaluation-builds/${id}/runs`,'POST').then(()=>{room.setNotice('Evaluation started','success');room.refresh()}).catch(e=>room.setNotice(e.message))
  const testBuild=(id:string)=>api(`/api/evaluation-builds/${id}/tests`,'POST').then(()=>{room.setNotice('Evaluation test started','success');room.refresh()}).catch(e=>room.setNotice(e.message))
  const createBuild=(values:unknown)=>api('/api/evaluation-builds','POST',values).then(()=>{room.setNotice('Evaluation build created','success');room.refresh()}).catch(e=>room.setNotice(e.message))
  const updateBuild=(id:string,values:unknown)=>api(`/api/evaluation-builds/${id}`,'PUT',values).then(()=>{room.setNotice('Evaluation build updated','success');room.refresh()}).catch(e=>room.setNotice(e.message))
  const deleteAsset=(kind:'profile'|'template'|'test-set'|'runner'|'workflow'|'execution-environment'|'target-environment',id:string)=>{const path={profile:`/api/settings/profiles/${encodeURIComponent(id)}`,template:`/api/prompt-templates/${id}`,'test-set':`/api/target-test-case-sets/${id}`,runner:`/api/runners/${id}`,workflow:`/api/workflows/${id}`,'execution-environment':`/api/execution-environments/${id}`,'target-environment':`/api/target-environments/${id}`}[kind];api(path,'DELETE').then(()=>{room.setNotice('Asset deleted','success');room.refresh()}).catch(e=>room.setNotice(e.message))}
  const deleteBuild=(id:string)=>setDeletingBuild(id)
  const confirmDeleteBuild=()=>{if(!deletingBuild)return;const id=deletingBuild;setDeletingBuild(null);api(`/api/evaluation-builds/${id}`,'DELETE').then(()=>{room.setNotice('Evaluation build deleted','success');room.refresh()}).catch(e=>room.setNotice(e.message))}
  const createWorkflow=(values:unknown)=>api('/api/workflows/clone','POST',values).then(()=>room.refresh())
  const updateWorkflow=(id:string,values:unknown)=>api(`/api/workflows/${id}`,'PUT',values).then(()=>room.refresh())
  const content={dashboard:<DashboardPage data={room.data} logs={room.orbitLogs} locale={locale} onOpenRun={()=>setPage('runs')} onOpenBuild={()=>setPage('builds')}/>,assets:<AssetsPage locale={locale} workflows={room.workflows} runners={room.runners} promptTemplates={room.promptTemplates} testCaseSets={room.testCaseSets} executionEnvironments={room.executionEnvironments} targetEnvironments={room.targetEnvironments} onRefresh={room.refresh} onCreateWorkflow={createWorkflow} onUpdateWorkflow={updateWorkflow} onDelete={deleteAsset}/>,builds:<EvaluationBuildsPage locale={locale} builds={room.builds} workflows={room.workflows} runs={room.runs} profiles={room.profiles} promptTemplates={room.promptTemplates} testCaseSets={room.testCaseSets} executionEnvironments={room.executionEnvironments} targetEnvironments={room.targetEnvironments} onInvoke={invoke} onTest={testBuild} onCreate={createBuild} onUpdate={updateBuild} onDelete={deleteBuild}/>,runs:<EvaluationsPage locale={locale} runs={room.runs} onStop={stopRun} onApprove={approveRun} onReject={rejectRun} onEmergencyStop={()=>setConfirmingEmergencyStop(true)} onDeleteRuns={deleteRuns}/>,improvements:<ImprovementsPage/>,settings:<SettingsPage locale={locale} setLocale={setLocale} theme={theme} setTheme={setTheme} profiles={room.profiles} settings={room.settings} setSettings={room.setSettings} test={test} save={save} tested={room.settingsTested} onDeleteProfile={id=>deleteAsset('profile',id)}/>}[page]
  const confirmation={en:{title:'Delete evaluation build?',description:'This permanently removes the evaluation build and its configuration.',cancel:'Cancel',confirm:'Delete'},ko:{title:'평가 빌드를 삭제할까요?',description:'평가 빌드와 해당 설정이 영구적으로 삭제됩니다.',cancel:'취소',confirm:'삭제'},ja:{title:'評価ビルドを削除しますか？',description:'評価ビルドとその設定が完全に削除されます。',cancel:'キャンセル',confirm:'削除'}}[locale]
  const emergencyConfirmation={en:{title:'Stop all active evaluations?',description:'This immediately cancels every active evaluation run. This action cannot be undone.',cancel:'Cancel',confirm:'Emergency stop'},ko:{title:'모든 활성 평가를 긴급 정지할까요?',description:'현재 실행 중인 모든 평가가 즉시 취소됩니다. 이 작업은 되돌릴 수 없습니다.',cancel:'취소',confirm:'긴급 정지'},ja:{title:'すべての実行中評価を緊急停止しますか？',description:'実行中の評価がすべて直ちにキャンセルされます。この操作は元に戻せません。',cancel:'キャンセル',confirm:'緊急停止'}}[locale]
  return <AppShell page={page} setPage={setPage} locale={locale} theme={theme}><div className="page-stack">{content}</div><ConfirmDialog open={deletingBuild!==null} title={confirmation.title} description={confirmation.description} cancelLabel={confirmation.cancel} confirmLabel={confirmation.confirm} onCancel={()=>setDeletingBuild(null)} onConfirm={confirmDeleteBuild}/><ConfirmDialog open={confirmingEmergencyStop} title={emergencyConfirmation.title} description={emergencyConfirmation.description} cancelLabel={emergencyConfirmation.cancel} confirmLabel={emergencyConfirmation.confirm} onCancel={()=>setConfirmingEmergencyStop(false)} onConfirm={confirmEmergencyStop}/></AppShell>
}

createRoot(document.getElementById('root')!).render(<ToastProvider><App /></ToastProvider>)
