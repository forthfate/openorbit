import { CircleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Tooltip } from './tooltip'

export function SectionInfo({title,description}:{title:ReactNode;description:string}){
  return <span className="panel-title-with-tooltip">{title}<Tooltip content={description}><CircleAlert size={15} aria-label={description}/></Tooltip></span>
}
