import { useCallback, useEffect, useRef, useState } from 'react'
import type { Build, Dashboard, OrbitLog, PromptTemplate, Run, RunnerAsset, Settings, TargetTestCaseSet, Workflow } from '../domain/models'
import { api } from './api'

const defaults:Settings={profile_name:'Default',provider:'azure-openai',model:'',endpoint:'',region:'us-east-1',secret_env:'AZURE_OPENAI_API_KEY',aws_profile:''}

export function useControlRoom(){
  const[data,setData]=useState<Dashboard|null>(null),[builds,setBuilds]=useState<Build[]>([]),[workflows,setWorkflows]=useState<Workflow[]>([]),[runners,setRunners]=useState<RunnerAsset[]>([]),[runs,setRuns]=useState<Run[]>([]),[orbitLogs,setOrbitLogs]=useState<OrbitLog[]>([]),[promptTemplates,setPromptTemplates]=useState<PromptTemplate[]>([]),[testCaseSets,setTestCaseSets]=useState<TargetTestCaseSet[]>([]),[profiles,setProfiles]=useState<Settings[]>([]),[settings,setSettingsState]=useState<Settings>(defaults),[settingsTested,setSettingsTested]=useState(false),[notice,setNoticeState]=useState('')
  const settingsLoaded=useRef(false)
  const noticeTimer=useRef<number|undefined>(undefined)
  const setNotice=useCallback((message:string)=>{window.clearTimeout(noticeTimer.current);setNoticeState(message);if(message)noticeTimer.current=window.setTimeout(()=>setNoticeState(''),10_800)},[])
  const setSettings=useCallback((values:Settings)=>{setSettingsState(values);setSettingsTested(false)},[])
  const refresh=useCallback(()=>Promise.all([api<Dashboard>('/api/dashboard'),api<Build[]>('/api/evaluation-builds'),api<Workflow[]>('/api/workflows'),api<RunnerAsset[]>('/api/runners'),api<Run[]>('/api/runs'),api<OrbitLog[]>('/api/orbit-logs'),api<PromptTemplate[]>('/api/prompt-templates'),api<TargetTestCaseSet[]>('/api/target-test-case-sets'),api<Settings>('/api/settings'),api<Settings[]>('/api/settings/profiles')]).then(([d,b,w,rr,r,o,t,tc,s,p])=>{setData(d);setBuilds(b);setWorkflows(w);setRunners(rr);setRuns(r);setOrbitLogs(o);setPromptTemplates(t);setTestCaseSets(tc);setProfiles(p);if(!settingsLoaded.current){setSettingsState(s);settingsLoaded.current=true}}).catch(()=>setNotice('API connection failed.')),[setNotice])
  useEffect(()=>{refresh();const timer=window.setInterval(refresh,3000);return()=>window.clearInterval(timer)},[refresh])
  useEffect(()=>()=>window.clearTimeout(noticeTimer.current),[])
  return{data,builds,workflows,runners,runs,orbitLogs,promptTemplates,testCaseSets,profiles,settings,setSettings,settingsTested,setSettingsTested,notice,setNotice,refresh}
}
