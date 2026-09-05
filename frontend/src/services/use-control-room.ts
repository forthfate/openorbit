import { useCallback, useEffect, useRef, useState } from 'react'
import type { Build, Dashboard, Improvement, OrbitLog, PromptTemplate, Run, RunnerAsset, Settings, Workflow } from '../domain/models'
import { api } from './api'

const defaults:Settings={profile_name:'Default',provider:'azure-openai',model:'',endpoint:'',region:'us-east-1',secret_env:'AZURE_OPENAI_API_KEY',aws_profile:''}

export function useControlRoom(){
  const[data,setData]=useState<Dashboard|null>(null),[builds,setBuilds]=useState<Build[]>([]),[workflows,setWorkflows]=useState<Workflow[]>([]),[runners,setRunners]=useState<RunnerAsset[]>([]),[runs,setRuns]=useState<Run[]>([]),[activeRuns,setActiveRuns]=useState<Run[]>([]),[improvements,setImprovements]=useState<Improvement[]>([]),[orbitLogs,setOrbitLogs]=useState<OrbitLog[]>([]),[promptTemplates,setPromptTemplates]=useState<PromptTemplate[]>([]),[profiles,setProfiles]=useState<Settings[]>([]),[settings,setSettingsState]=useState<Settings>(defaults),[settingsTested,setSettingsTested]=useState(false),[notice,setNoticeState]=useState('')
  const settingsLoaded=useRef(false)
  const noticeTimer=useRef<number|undefined>(undefined)
  const setNotice=useCallback((message:string)=>{window.clearTimeout(noticeTimer.current);setNoticeState(message);if(message)noticeTimer.current=window.setTimeout(()=>setNoticeState(''),10_800)},[])
  const setSettings=useCallback((values:Settings)=>{setSettingsState(values);setSettingsTested(false)},[])
  const refresh=useCallback(()=>Promise.all([api<Dashboard>('/api/dashboard'),api<Build[]>('/api/evaluation-builds'),api<Workflow[]>('/api/workflows'),api<RunnerAsset[]>('/api/runners'),api<Run[]>('/api/runs'),api<Run[]>('/api/active-evaluations'),api<Improvement[]>('/api/improvements'),api<OrbitLog[]>('/api/orbit-logs'),api<PromptTemplate[]>('/api/prompt-templates'),api<Settings>('/api/settings'),api<Settings[]>('/api/settings/profiles')]).then(([d,b,w,rr,r,a,i,o,t,s,p])=>{setData(d);setBuilds(b);setWorkflows(w);setRunners(rr);setRuns(r);setActiveRuns(a);setImprovements(i);setOrbitLogs(o);setPromptTemplates(t);setProfiles(p);if(!settingsLoaded.current){setSettingsState(s);settingsLoaded.current=true}}).catch(()=>setNotice('API connection failed.')),[setNotice])
  useEffect(()=>{refresh();const timer=window.setInterval(refresh,3000);return()=>window.clearInterval(timer)},[refresh])
  useEffect(()=>()=>window.clearTimeout(noticeTimer.current),[])
  return{data,builds,workflows,runners,runs,activeRuns,improvements,orbitLogs,promptTemplates,profiles,settings,setSettings,settingsTested,setSettingsTested,notice,setNotice,refresh}
}
