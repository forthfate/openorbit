import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef } from 'react'

export function AssistantTerminal({active}:{active:boolean}){
  const host=useRef<HTMLDivElement>(null)
  const resizeTerminal=useRef<()=>void>(()=>undefined)
  useEffect(()=>{
    if(!host.current)return
    const terminal=new Terminal({cursorBlink:true,fontSize:12,theme:{background:'#101614',foreground:'#e9eee9'}})
    const fit=new FitAddon();terminal.loadAddon(fit);terminal.open(host.current);fit.fit()
    const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/terminal`)
    socket.onopen=()=>{terminal.focus();socket.send(JSON.stringify({type:'resize',cols:terminal.cols,rows:terminal.rows}))}
    socket.onmessage=event=>terminal.write(event.data)
    socket.onclose=()=>terminal.write('\r\n[Terminal session ended]')
    const input=terminal.onData(data=>socket.readyState===WebSocket.OPEN&&socket.send(JSON.stringify({type:'input',data})))
    const resize=()=>{fit.fit();if(socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'resize',cols:terminal.cols,rows:terminal.rows}))}
    resizeTerminal.current=resize
    window.addEventListener('resize',resize)
    return()=>{resizeTerminal.current=()=>undefined;input.dispose();window.removeEventListener('resize',resize);socket.close();terminal.dispose()}
  },[])
  useEffect(()=>{if(active)requestAnimationFrame(()=>{resizeTerminal.current();host.current?.querySelector<HTMLTextAreaElement>('.xterm-helper-textarea')?.focus()})},[active])
  return <div className={`assistant-terminal ${active?'assistant-terminal--active':''}`} ref={host}/>
}
