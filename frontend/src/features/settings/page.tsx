import { useEffect, useState } from 'react'
import { Pencil } from 'lucide-react'
import type { Locale } from '../../locales'
import { locales } from '../../locales'
import { Modal } from '../../components/ui/modal'
import { PanelHeader } from '../../components/ui/page-header'
import { api } from '../../services/api'

type ApplicationSettings={manager_prompt_template:string}

const copy={
  en:{title:'Operational manager prompt',description:'A console-wide operating prompt. It is separate from the reusable manager prompt templates selected by evaluation builds.',edit:'Edit prompt',content:'Prompt content',save:'Save',cancel:'Cancel',empty:'No operational prompt configured.',saved:'Saved.'},
  ko:{title:'운영 관리자 프롬프트',description:'콘솔 전체 운영에 사용하는 프롬프트입니다. 평가 빌드에서 선택하는 재사용 관리자 프롬프트 템플릿 자산과는 별개입니다.',edit:'프롬프트 편집',content:'프롬프트 본문',save:'저장',cancel:'취소',empty:'설정된 운영 프롬프트가 없습니다.',saved:'저장했습니다.'},
  ja:{title:'運用管理者プロンプト',description:'コンソール全体の運用に使うプロンプトです。評価ビルドで選択する再利用可能な管理者プロンプトテンプレートとは別に管理します。',edit:'プロンプトを編集',content:'プロンプト本文',save:'保存',cancel:'キャンセル',empty:'運用プロンプトは設定されていません。',saved:'保存しました。'},
}

export function SettingsPage({locale,setLocale,theme,setTheme}:{locale:Locale;setLocale:(locale:Locale)=>void;theme:string;setTheme:(theme:string)=>void}){
  const t=locales[locale].common, l=copy[locale]
  const [prompt,setPrompt]=useState(''),[open,setOpen]=useState(false),[notice,setNotice]=useState('')
  useEffect(()=>{api<ApplicationSettings>('/api/application-settings').then(values=>setPrompt(values.manager_prompt_template)).catch(()=>setNotice('Unable to load operational prompt.'))},[])
  const savePrompt=()=>api<ApplicationSettings>('/api/application-settings','PUT',{manager_prompt_template:prompt}).then(values=>{setPrompt(values.manager_prompt_template);setNotice(l.saved);setOpen(false)}).catch(error=>setNotice(error.message))
  return <><section className="panel app-settings"><PanelHeader title={t.applicationSettings}/><label className="setting-row"><span><strong>{t.language}</strong><small>{t.languageHint}</small></span><select value={locale} onChange={event=>setLocale(event.target.value as Locale)}><option value="en">English</option><option value="ko">한국어</option><option value="ja">日本語</option></select></label><label className="setting-row"><span><strong>{t.theme}</strong><small>{t.themeHint}</small></span><select value={theme} onChange={event=>setTheme(event.target.value)}><option value="forest">Forest dark</option><option value="midnight">Midnight</option></select></label></section><section className="panel app-settings"><div className="panel-title-action"><PanelHeader title={l.title}/><button className="approve" onClick={()=>setOpen(true)}><Pencil size={14}/>{l.edit}</button></div><p className="hint">{l.description}</p><p className="setting-prompt-preview">{prompt||l.empty}</p>{notice&&<p className="modal-hint">{notice}</p>}</section><Modal open={open} title={l.title} onClose={()=>setOpen(false)}><div className="modal-form"><label className="modal-setting-row"><span>{l.content}</span><textarea rows={16} value={prompt} onChange={event=>setPrompt(event.target.value)}/></label><p className="modal-hint">{l.description}</p><div className="modal-actions"><button className="ghost" onClick={()=>setOpen(false)}>{l.cancel}</button><button className="approve" onClick={savePrompt}>{l.save}</button></div></div></Modal></>
}
