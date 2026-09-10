import type { ReactNode } from 'react'
import { SectionInfo } from './section-info'
import { locales, resolveLocale } from '../../locales'

export function PanelHeader({title,description,action}:{title:ReactNode;description?:string;action?:ReactNode}){return <div className="panel-head"><h2>{description?<SectionInfo title={title} description={description}/>:title}</h2>{action}</div>}
export function MetricCard({label,value,detail}:{label:string;value:string;detail?:string}){const locale=resolveLocale(localStorage.getItem('orbit.locale'));const caption=detail??locales[locale].ui.liveLocalState;return <article className="metric"><p>{label}</p><strong>{value}</strong><small>{caption}</small></article>}
