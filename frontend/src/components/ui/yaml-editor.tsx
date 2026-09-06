import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'

export function YamlEditor({value,onChange}:{value:string;onChange:(value:string)=>void}){
  return <CodeMirror
    aria-label="Pipeline YAML"
    value={value}
    height="min(62vh, 680px)"
    theme={oneDark}
    extensions={[yaml()]}
    onChange={onChange}
    basicSetup={{lineNumbers:true,highlightActiveLine:true,bracketMatching:true,foldGutter:true}}
  />
}
