import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

export function YamlEditor({value,onChange,label}:{value:string;label:string;onChange:(value:string)=>void}){
  return <CodeMirror
    value={value}
    height="min(62vh, 680px)"
    theme={oneDark}
    extensions={[yaml(), EditorView.contentAttributes.of({ 'aria-label': label })]}
    onChange={onChange}
    basicSetup={{lineNumbers:true,highlightActiveLine:true,bracketMatching:true,foldGutter:true}}
  />
}
