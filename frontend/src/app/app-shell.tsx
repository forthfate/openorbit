import { Activity, BarChart3, Boxes, FileCode2, Play, Settings, Sparkles } from 'lucide-react'
import { SiGithub } from 'react-icons/si'
import type { ReactNode } from 'react'
import type { Page } from '../domain/models'
import type { Locale } from '../locales'
import { localeMessages, locales } from '../locales'
import { ChatAssistant } from '../components/chat-assistant'

export function AppShell({page,setPage,locale,theme,headerAction,activeRunCount=0,children}:{page:Page;setPage:(page:Page)=>void;locale:Locale;theme:string;headerAction?:ReactNode;activeRunCount?:number;children:ReactNode}){
  const t=locales[locale]
  const pageDescriptions=localeMessages<Record<Page,string>>(locale,'shell')
  const navigation:[Page,ReactNode,string][]=[['dashboard',<Activity size={17}/>,t.dashboard],['assets',<Boxes size={17}/>,t.assets],['builds',<FileCode2 size={17}/>,t.builds],['runs',<Play size={17}/>,t.runs],['improvements',<BarChart3 size={17}/>,t.improvements],['settings',<Settings size={17}/>,t.settings]]
  const dashboardRepositoryLink=page==='dashboard'&&<a className="dashboard-repository-link" href="https://github.com/forthfate/openorbit" target="_blank" rel="noreferrer"><SiGithub size={16}/>GitHub Repository</a>
  const activeRunLabel=activeRunCount>99?'99+':String(activeRunCount)
  return <main data-theme={theme==='midnight'?'midnight':undefined}><aside><div className="brand"><Sparkles size={20}/><div><span>OpenOrbit</span><small>{__OPENORBIT_VERSION__}</small></div></div><nav>{navigation.map(([id,icon,label])=><button className={page===id?'active':''} onClick={()=>setPage(id)} key={id}>{icon}<span>{label}</span>{id==='runs'&&activeRunCount>0&&<span className="nav-run-count" aria-label={`${activeRunCount} active runs`}>{activeRunLabel}</span>}</button>)}</nav></aside><section className="content"><header><div className="page-header-copy"><h1>{t[page]}</h1><p className="sub">{pageDescriptions[page]}</p></div><div className="page-header-actions">{dashboardRepositoryLink}{headerAction}</div></header>{children}<footer><span>© insighta cloud Inc.</span><a className="github-link" href="https://github.com/forthfate/openorbit" target="_blank" rel="noreferrer" aria-label="OpenOrbit on GitHub" title="OpenOrbit GitHub repository"><SiGithub size={18}/></a></footer></section><ChatAssistant/></main>
}
