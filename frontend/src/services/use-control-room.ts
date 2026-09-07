import { useCallback, useEffect, useRef, useState } from 'react'
import type { Build, Dashboard, ExecutionEnvironment, OrbitLog, PromptTemplate, Run, RunnerAsset, Settings, TargetEnvironment, TargetTestCaseSet, Workflow } from '../domain/models'
import { useToast, type ToastTone } from '../components/ui/toast-context'
import { api } from './api'

const defaults:Settings={profile_name:'Default',provider:'azure-openai',model:'',endpoint:'',region:'us-east-1',secret_env:'AZURE_OPENAI_API_KEY',aws_profile:''}

export function useControlRoom(){
  const[data,setData]=useState<Dashboard|null>(null),[builds,setBuilds]=useState<Build[]>([]),[workflows,setWorkflows]=useState<Workflow[]>([]),[runners,setRunners]=useState<RunnerAsset[]>([]),[runs,setRuns]=useState<Run[]>([]),[orbitLogs,setOrbitLogs]=useState<OrbitLog[]>([]),[promptTemplates,setPromptTemplates]=useState<PromptTemplate[]>([]),[testCaseSets,setTestCaseSets]=useState<TargetTestCaseSet[]>([]),[executionEnvironments,setExecutionEnvironments]=useState<ExecutionEnvironment[]>([]),[targetEnvironments,setTargetEnvironments]=useState<TargetEnvironment[]>([]),[profiles,setProfiles]=useState<Settings[]>([]),[settings,setSettingsState]=useState<Settings>(defaults),[settingsTested,setSettingsTested]=useState(false)
  const {pushToast}=useToast()
  const settingsLoaded=useRef(false)
  const setNotice=useCallback((message:string,tone:ToastTone='error')=>pushToast(message,tone),[pushToast])
  const setSettings=useCallback((values:Settings)=>{setSettingsState(values);setSettingsTested(false)},[])
  const refresh=useCallback(()=>Promise.all([api<Dashboard>('/api/dashboard'),api<Build[]>('/api/evaluation-builds'),api<Workflow[]>('/api/workflows'),api<RunnerAsset[]>('/api/runners'),api<Run[]>('/api/runs'),api<OrbitLog[]>('/api/orbit-logs'),api<PromptTemplate[]>('/api/prompt-templates'),api<TargetTestCaseSet[]>('/api/target-test-case-sets'),api<ExecutionEnvironment[]>('/api/execution-environments'),api<TargetEnvironment[]>('/api/target-environments'),api<Settings>('/api/settings'),api<Settings[]>('/api/settings/profiles')]).then(([d,b,w,rr,r,o,t,tc,ee,te,s,p])=>{setData(d);setBuilds(b);setWorkflows(w);setRunners(rr);setRuns(r);setOrbitLogs(o);setPromptTemplates(t);setTestCaseSets(tc);setExecutionEnvironments(ee);setTargetEnvironments(te);setProfiles(p);if(!settingsLoaded.current){setSettingsState(s);settingsLoaded.current=true}}).catch(()=>setNotice('API connection failed.','warning')),[setNotice])
  useEffect(()=>{refresh();const timer=window.setInterval(refresh,3000);return()=>window.clearInterval(timer)},[refresh])
  return{data,builds,workflows,runners,runs,orbitLogs,promptTemplates,testCaseSets,executionEnvironments,targetEnvironments,profiles,settings,setSettings,settingsTested,setSettingsTested,setNotice,refresh}
}
