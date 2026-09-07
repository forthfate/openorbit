import type { ReactNode } from 'react'
import { SectionInfo } from './section-info'
import { localeMessages, locales, resolveLocale } from '../../locales'

export function PanelHeader({title,description,action}:{title:ReactNode;description?:string;action?:ReactNode}){const locale=resolveLocale(localStorage.getItem('orbit.locale')),sectionHints=localeMessages<Record<string,string>>(locale,'sectionHints'),hint=description??(typeof title==='string'?sectionHints[title]:undefined);return <div className="panel-head"><h2>{hint?<SectionInfo title={title} description={hint}/>:title}</h2>{action}</div>}
export function MetricCard({label,value,detail}:{label:string;value:string;detail?:string}){const locale=resolveLocale(localStorage.getItem('orbit.locale'));const caption=detail??locales[locale].ui.liveLocalState;return <article className="metric"><p>{label}</p><strong>{value}</strong><small>{caption}</small></article>}
