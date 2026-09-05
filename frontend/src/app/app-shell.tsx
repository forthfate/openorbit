import { Activity, BarChart3, Boxes, FileCode2, Play, Settings, Sparkles } from 'lucide-react'
import { SiGithub } from 'react-icons/si'
import type { ReactNode } from 'react'
import type { Page } from '../domain/models'
import type { Locale } from '../locales'
import { locales } from '../locales'

export function AppShell({page,setPage,locale,theme,headerAction,children}:{page:Page;setPage:(page:Page)=>void;locale:Locale;theme:string;headerAction?:ReactNode;children:ReactNode}){
  const t=locales[locale]
  const navigation:[Page,ReactNode,string][]=[['dashboard',<Activity size={17}/>,t.dashboard],['assets',<Boxes size={17}/>,t.assets],['builds',<FileCode2 size={17}/>,t.builds],['runs',<Play size={17}/>,t.runs],['improvements',<BarChart3 size={17}/>,t.improvements],['settings',<Settings size={17}/>,t.settings]]
  return <main data-theme={theme==='midnight'?'midnight':undefined}><aside><div className="brand"><Sparkles size={20}/><span>OpenOrbit</span></div><nav>{navigation.map(([id,icon,label])=><button className={page===id?'active':''} onClick={()=>setPage(id)} key={id}>{icon}{label}</button>)}</nav></aside><section className="content"><header><h1>{t[page]}</h1>{headerAction}</header>{children}<footer><span>© insighta cloud Inc. · OpenOrbit v0.0.1</span><a className="github-link" href="https://github.com/forthfate/openorbit" target="_blank" rel="noreferrer" aria-label="OpenOrbit on GitHub" title="OpenOrbit GitHub repository"><SiGithub size={18}/></a></footer></section></main>
}
