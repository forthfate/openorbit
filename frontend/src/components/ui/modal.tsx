import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

export function Modal({open,title,onClose,children,className=''}:{open:boolean;title:string;onClose:()=>void;children:ReactNode;className?:string}){
  useEffect(()=>{
    if(!open)return
    const closeOnEscape=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose()}
    document.addEventListener('keydown',closeOnEscape)
    return()=>document.removeEventListener('keydown',closeOnEscape)
  },[open,onClose])
  if(!open)return null
  const locale=localStorage.getItem('orbit.locale'), close=locale==='ko'?'대화상자 닫기':locale==='ja'?'ダイアログを閉じる':'Close dialog'
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={event=>event.stopPropagation()}><header className="modal-header"><h2>{title}</h2><button className="modal-close" aria-label={close} onClick={onClose}><X size={18}/></button></header>{children}</section></div>
}
