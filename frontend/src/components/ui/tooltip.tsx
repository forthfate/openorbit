import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function Tooltip({content,children}:{content:ReactNode;children:ReactNode}){
  const triggerRef = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null)
  const [position, setPosition] = useState({ left: 0, bottom: 0 })
  const updatePosition = useCallback(() => {
    const bounds = triggerRef.current?.getBoundingClientRect()
    if (bounds) setPosition({ left: bounds.left, bottom: window.innerHeight - bounds.top + 9 })
  }, [])
  const show = () => { setPortalTarget(triggerRef.current?.closest(".app-shell") ?? document.body); updatePosition(); setOpen(true) }

  useEffect(() => {
    if (!open) return
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('resize', updatePosition)
    return () => { window.removeEventListener('scroll', updatePosition, true); window.removeEventListener('resize', updatePosition) }
  }, [open, updatePosition])

  return <span className="tooltip" ref={triggerRef} onMouseEnter={show} onMouseLeave={() => setOpen(false)} onFocus={show} onBlur={() => setOpen(false)}>{children}{open && portalTarget && createPortal(<span className="tooltip-content tooltip-content--visible" role="tooltip" style={position}>{content}</span>, portalTarget)}</span>
}
