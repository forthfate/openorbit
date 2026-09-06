import { Bot, Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../services/api'

type Message={role:'user'|'assistant';content:string}
type Position={x:number;y:number}
type DragTarget='launcher'|'window'
const positionKey='orbit.chat.position'
const windowPositionKey='orbit.chat.window.position'

const initialPosition=():Position=>{
  const saved=localStorage.getItem(positionKey)
  if(saved){try{const position=JSON.parse(saved) as Position;if(Number.isFinite(position.x)&&Number.isFinite(position.y))return position}catch{/* use default */}}
  return {x:Math.max(16,window.innerWidth-72),y:Math.max(16,window.innerHeight-72)}
}

const initialWindowPosition=():Position|null=>{
  const saved=localStorage.getItem(windowPositionKey)
  if(saved){try{const position=JSON.parse(saved) as Position;if(Number.isFinite(position.x)&&Number.isFinite(position.y))return position}catch{/* use default */}}
  return null
}

export function ChatAssistant(){
  const [open,setOpen]=useState(false),[messages,setMessages]=useState<Message[]>([]),[draft,setDraft]=useState(''),[sending,setSending]=useState(false),[position,setPosition]=useState<Position>(initialPosition),[windowPosition,setWindowPosition]=useState<Position|null>(initialWindowPosition)
  const drag=useRef<{target:DragTarget;startX:number;startY:number;x:number;y:number;moved:boolean}|null>(null)
  const suppressClick=useRef(false)
  const messageList=useRef<HTMLDivElement>(null)
  const chatWindow=useRef<HTMLElement>(null)
  useEffect(()=>{messageList.current?.scrollTo({top:messageList.current.scrollHeight})},[messages,sending])
  useEffect(()=>{localStorage.setItem(positionKey,JSON.stringify(position))},[position])
  useEffect(()=>{if(windowPosition)localStorage.setItem(windowPositionKey,JSON.stringify(windowPosition))},[windowPosition])
  useEffect(()=>{const move=(event:PointerEvent)=>{const active=drag.current;if(!active)return;const size=active.target==='window'&&chatWindow.current?chatWindow.current.getBoundingClientRect():{width:60,height:60};const x=Math.min(Math.max(12,active.x+event.clientX-active.startX),Math.max(12,window.innerWidth-size.width-12)),y=Math.min(Math.max(12,active.y+event.clientY-active.startY),Math.max(12,window.innerHeight-size.height-12));if(Math.abs(event.clientX-active.startX)>4||Math.abs(event.clientY-active.startY)>4)active.moved=true;if(active.target==='window')setWindowPosition({x,y});else setPosition({x,y})};const end=()=>{if(drag.current?.moved)suppressClick.current=true;drag.current=null};window.addEventListener('pointermove',move);window.addEventListener('pointerup',end);return()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end)}},[])
  const send=async()=>{const content=draft.trim();if(!content||sending)return;const history=messages.slice(-12);setDraft('');setMessages(current=>[...current,{role:'user',content}]);setSending(true);try{const result=await api<{response:string}>('/api/chat','POST',{content,history});setMessages(current=>[...current,{role:'assistant',content:result.response}])}catch(error){setMessages(current=>[...current,{role:'assistant',content:error instanceof Error?error.message:'Chat request failed.'}])}finally{setSending(false)}}
  const defaultWindowPosition={x:Math.max(16,position.x-332),y:Math.max(16,position.y-512)}
  if(!open)return <button className="chat-launcher" style={{left:position.x,top:position.y}} aria-label="Open chat assistant" onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);drag.current={target:'launcher',startX:event.clientX,startY:event.clientY,x:position.x,y:position.y,moved:false}}} onClick={()=>{if(suppressClick.current){suppressClick.current=false;return}setWindowPosition(current=>current??defaultWindowPosition);setOpen(true)}}><Bot size={22}/></button>
  const popupPosition=windowPosition??defaultWindowPosition
  return <section ref={chatWindow} className="chat-assistant" style={{left:popupPosition.x,top:popupPosition.y,right:'auto',bottom:'auto'}} aria-label="Chat assistant"><header onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);drag.current={target:'window',startX:event.clientX,startY:event.clientY,x:popupPosition.x,y:popupPosition.y,moved:false}}}><div><Bot size={18}/><strong>Orbit assistant</strong></div><button className="ghost" aria-label="Collapse chat" onPointerDown={event=>event.stopPropagation()} onClick={()=>setOpen(false)}><X size={18}/></button></header><div className="chat-messages" ref={messageList}>{messages.length===0&&<p className="chat-empty">Ask about your evaluation work, runners, or the control room.</p>}{messages.map((message,index)=><article key={index} className={`chat-message chat-message--${message.role}`}>{message.role==='assistant'?<ReactMarkdown remarkPlugins={[remarkGfm]} components={{a:props=><a {...props} target="_blank" rel="noreferrer"/>}}>{message.content}</ReactMarkdown>:message.content}</article>)}{sending&&<article className="chat-message chat-message--assistant">Thinking…</article>}</div><form onSubmit={event=>{event.preventDefault();send()}}><textarea aria-label="Message" rows={2} placeholder="Message Orbit…" value={draft} onChange={event=>setDraft(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}}}/><button className="approve" type="submit" disabled={!draft.trim()||sending} aria-label="Send message"><Send size={16}/></button></form></section>
}
