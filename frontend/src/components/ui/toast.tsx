import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type ToastTone } from './toast-context'

type Toast={id:number;message:string;tone:ToastTone}

export function ToastProvider({children}:{children:ReactNode}){
  const [toasts,setToasts]=useState<Toast[]>([])
  const nextId=useRef(0)
  const timers=useRef(new Map<number,number>())
  const dismissToast=useCallback((id:number)=>{const timer=timers.current.get(id);if(timer!==undefined){window.clearTimeout(timer);timers.current.delete(id)}setToasts(current=>current.filter(toast=>toast.id!==id))},[])
  const pushToast=useCallback((message:string,tone:ToastTone='error')=>{if(!message)return;const id=++nextId.current;setToasts(current=>[{id,message,tone},...current]);timers.current.set(id,window.setTimeout(()=>dismissToast(id),10_000))},[dismissToast])
  useEffect(()=>()=>{timers.current.forEach(timer=>window.clearTimeout(timer));timers.current.clear()},[])
  return <ToastContext.Provider value={{pushToast,dismissToast}}>{children}<div className="toast-viewport" aria-live="polite" aria-relevant="additions">{toasts.map(toast=><div key={toast.id} className={`notice notice--${toast.tone} notice--auto-dismiss`} role={toast.tone==='error'?'alert':'status'}><span>{toast.message}</span><button className="toast-dismiss" type="button" aria-label="Dismiss notification" onClick={()=>dismissToast(toast.id)}>×</button></div>)}</div></ToastContext.Provider>
}
