import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";

export function JsonEditor({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  return <CodeMirror value={value} height="min(62vh, 680px)" theme={oneDark} extensions={[json(), EditorView.contentAttributes.of({ "aria-label": label })]} onChange={onChange} basicSetup={{ lineNumbers: true, highlightActiveLine: true, bracketMatching: true, foldGutter: true }} />;
}
