import { useCallback, useEffect, useRef, useState } from 'react'
import type { Build, Dashboard, ExecutionEnvironment, OrbitLog, Page, PromptTemplate, Run, RunnerAsset, Settings, SystemReadiness, TargetEnvironment, TargetTestCaseSet } from '../domain/models'
import { useToast, type ToastTone } from '../components/ui/toast-context'
import { localeMessages, resolveLocale } from '../locales'
import { api } from './api'

const defaults:Settings={profile_name:'Default',provider:'azure-openai',model:'',endpoint:'',region:'us-east-1',secret_env:'AZURE_OPENAI_API_KEY',aws_profile:''}

export function useControlRoom(page:Page){
  const ui=localeMessages<Record<string,string>>(resolveLocale(localStorage.getItem('orbit.locale')),'ui')
  const[data,setData]=useState<Dashboard|null>(null),[builds,setBuilds]=useState<Build[]>([]),[runners,setRunners]=useState<RunnerAsset[]>([]),[runs,setRuns]=useState<Run[]>([]),[orbitLogs,setOrbitLogs]=useState<OrbitLog[]>([]),[promptTemplates,setPromptTemplates]=useState<PromptTemplate[]>([]),[testCaseSets,setTestCaseSets]=useState<TargetTestCaseSet[]>([]),[executionEnvironments,setExecutionEnvironments]=useState<ExecutionEnvironment[]>([]),[targetEnvironments,setTargetEnvironments]=useState<TargetEnvironment[]>([]),[profiles,setProfiles]=useState<Settings[]>([]),[settings,setSettingsState]=useState<Settings>(defaults),[readiness,setReadiness]=useState<SystemReadiness|null>(null),[settingsTested,setSettingsTested]=useState(false),[loading,setLoading]=useState(true)
  const {pushToast}=useToast()
  const settingsLoaded=useRef(false),loadedPage=useRef<Page|null>(null)
  const setNotice=useCallback((message:string,tone:ToastTone='error')=>pushToast(message,tone),[pushToast])
  const setSettings=useCallback((values:Settings)=>{setSettingsState(values);setSettingsTested(false)},[])
  const loadProfiles=useCallback(()=>api<Settings[]>('/api/settings/profiles').then(setProfiles),[])
  const refresh=useCallback(()=>{
    if(loadedPage.current!==page){loadedPage.current=page;setLoading(true)}
    const requests:Promise<unknown>[]=[api<Run[]>('/api/runs').then(setRuns),api<SystemReadiness>('/api/system/readiness').then(setReadiness)]
    if(page==='dashboard')requests.push(api<Dashboard>('/api/dashboard').then(setData))
    if(page==='assets')requests.push(api<Build[]>('/api/builds').then(setBuilds),api<RunnerAsset[]>('/api/runners').then(setRunners),api<PromptTemplate[]>('/api/prompt-templates').then(setPromptTemplates),api<TargetTestCaseSet[]>('/api/target-test-case-sets').then(setTestCaseSets),api<ExecutionEnvironment[]>('/api/execution-environments').then(setExecutionEnvironments),api<TargetEnvironment[]>('/api/target-environments').then(setTargetEnvironments),loadProfiles(),api<Settings>('/api/settings').then((next)=>{if(!settingsLoaded.current){setSettingsState(next);settingsLoaded.current=true}}))
    if(page==='builds')requests.push(api<Build[]>('/api/builds').then(setBuilds),api<RunnerAsset[]>('/api/runners').then(setRunners),api<PromptTemplate[]>('/api/prompt-templates').then(setPromptTemplates),api<TargetTestCaseSet[]>('/api/target-test-case-sets').then(setTestCaseSets),api<ExecutionEnvironment[]>('/api/execution-environments').then(setExecutionEnvironments),api<TargetEnvironment[]>('/api/target-environments').then(setTargetEnvironments),loadProfiles())
    if(page==='runs')requests.push(api<Build[]>('/api/builds').then(setBuilds))
    if(page==='settings')requests.push(api<OrbitLog[]>('/api/orbit-logs').then(setOrbitLogs),loadProfiles(),api<Settings>('/api/settings').then((next)=>{if(!settingsLoaded.current){setSettingsState(next);settingsLoaded.current=true}}))
    return Promise.all(requests).catch(()=>setNotice(ui.apiConnectionFailed,'warning')).finally(()=>setLoading(false))
  },[loadProfiles,page,setNotice,ui])
  useEffect(()=>{refresh();const timer=window.setInterval(refresh,3000);return()=>window.clearInterval(timer)},[refresh])
  return{data,builds,workflows:[],runners,runs,orbitLogs,promptTemplates,testCaseSets,executionEnvironments,targetEnvironments,profiles,settings,readiness,setSettings,settingsTested,setSettingsTested,loading,setNotice,refresh,loadProfiles}
}
