import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

export function PythonEditor({value,onChange,ariaLabel}:{value:string;onChange:(value:string)=>void;ariaLabel:string}){
  return <CodeMirror
    aria-label={ariaLabel}
    value={value}
    height="min(56vh, 620px)"
    theme={oneDark}
    // Keep long comments, URLs, and embedded data inside the modal rather than
    // letting one line widen the editor and push the save action off screen.
    extensions={[python(),EditorView.lineWrapping]}
    onChange={onChange}
    basicSetup={{lineNumbers:true,highlightActiveLine:true,bracketMatching:true,foldGutter:true}}
  />
}
