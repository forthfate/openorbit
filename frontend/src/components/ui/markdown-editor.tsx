import CodeMirror from "@uiw/react-codemirror";
import { markdown } from "@codemirror/lang-markdown";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";

export function MarkdownEditor({
  value,
  onChange,
  label,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder: string;
}) {
  return (
    <CodeMirror
      value={value}
      height="260px"
      theme={oneDark}
      placeholder={placeholder}
      extensions={[markdown(), EditorView.lineWrapping, EditorView.contentAttributes.of({ "aria-label": label })]}
      onChange={onChange}
      basicSetup={{ lineNumbers: true, highlightActiveLine: true, bracketMatching: true, foldGutter: true }}
    />
  );
}
