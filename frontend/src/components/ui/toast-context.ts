import { createContext, useContext } from 'react'

export type ToastTone='success'|'warning'|'error'
type ToastContextValue={pushToast:(message:string,tone?:ToastTone)=>void;dismissToast:(id:number)=>void}

export const ToastContext=createContext<ToastContextValue|null>(null)

export function useToast(){
  const context=useContext(ToastContext)
  if(!context)throw new Error('useToast must be used within ToastProvider')
  return context
}
