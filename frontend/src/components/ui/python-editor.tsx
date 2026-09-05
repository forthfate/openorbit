import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'

export function PythonEditor({value,onChange}:{value:string;onChange:(value:string)=>void}){
  return <CodeMirror
    aria-label="Runner Python source"
    value={value}
    height="min(56vh, 620px)"
    theme={oneDark}
    extensions={[python()]}
    onChange={onChange}
    basicSetup={{lineNumbers:true,highlightActiveLine:true,bracketMatching:true,foldGutter:true}}
  />
}
