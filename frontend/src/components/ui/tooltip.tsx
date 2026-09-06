import type { ReactNode } from 'react'

export function Tooltip({content,children}:{content:string;children:ReactNode}){
  return <span className="tooltip" tabIndex={0}>{children}<span className="tooltip-content" role="tooltip">{content}</span></span>
}
