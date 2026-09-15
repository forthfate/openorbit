import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import CodeMirror from "@uiw/react-codemirror";
import { html } from "@codemirror/lang-html";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { CodeXml, Image } from "lucide-react";
import type { SavedDataFile } from "../../domain/models";
import { Modal } from "./modal";

export type EvidenceArtifact = { id?: string; name?: string; screenshot?: string; html?: string };

export function visualEvidenceArtifacts(files: SavedDataFile[]): EvidenceArtifact[] {
  return files.reduce<EvidenceArtifact[]>((artifacts, file, index) => {
    const path = file.relative_path ?? file.path;
    if (!path) return artifacts;
    const name = file.label || file.filename || `#${index + 1}`;
    const contentType = file.content_type?.toLowerCase();
    const extension = path.toLowerCase().split(".").at(-1);
    if (contentType?.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(extension ?? "")) {
      artifacts.push({ id: path, name, screenshot: path });
    }
    if (contentType === "text/html" || ["html", "htm"].includes(extension ?? "")) {
      artifacts.push({ id: path, name, html: path });
    }
    return artifacts;
  }, []);
}

function artifactUrl(runId: string, iteration: number, path: string) {
  const normalized = path.replaceAll("\\", "/"), marker = `/loop-${iteration}/`;
  const relative = normalized.includes(marker) ? normalized.split(marker).at(-1)! : normalized;
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${iteration}/${relative.split("/").map(encodeURIComponent).join("/")}`;
}

function HtmlEvidenceViewer({ url }: { url: string }) {
  const [result, setResult] = useState<{ url: string; source?: string; error?: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((source) => setResult({ url, source }))
      .catch((reason: unknown) => {
        if ((reason as { name?: string }).name !== "AbortError") setResult({ url, error: String(reason) });
      });
    return () => controller.abort();
  }, [url]);
  if (!result || result.url !== url) return <p className="hint">Loading HTML…</p>;
  if (result.error) return <pre className="persona-evidence__error">{result.error}</pre>;
  return <CodeMirror aria-label="HTML evidence source" value={result.source ?? ""} editable={false} height="min(60vh, 640px)" theme={oneDark} extensions={[html(), EditorView.lineWrapping]} basicSetup={{ lineNumbers: true, highlightActiveLine: true, bracketMatching: true, foldGutter: true }} />;
}

export function EvidenceViewer({ runId, iteration, artifacts, className, imageLabel, htmlLabel, imageTitle, htmlTitle }: { runId: string; iteration: number; artifacts: EvidenceArtifact[]; className?: string; imageLabel: string; htmlLabel: string; imageTitle: string; htmlTitle: string }) {
  const [evidenceModal, setEvidenceModal] = useState<{ kind: "image" | "html"; artifacts: EvidenceArtifact[] } | null>(null);
  const imageArtifacts = artifacts.filter((artifact) => artifact.screenshot);
  const htmlArtifacts = artifacts.filter((artifact) => artifact.html);
  const modalArtifacts = evidenceModal?.artifacts.filter((artifact) => evidenceModal.kind === "image" ? Boolean(artifact.screenshot) : Boolean(artifact.html)) ?? [];
  if (!imageArtifacts.length && !htmlArtifacts.length) return null;
  return <><span className={className}>{imageArtifacts.length > 0 && <button className="ghost icon-button" type="button" aria-label={imageLabel} title={imageLabel} onClick={() => setEvidenceModal({ kind: "image", artifacts: imageArtifacts })}><Image size={16} /></button>}{htmlArtifacts.length > 0 && <button className="ghost icon-button" type="button" aria-label={htmlLabel} title={htmlLabel} onClick={() => setEvidenceModal({ kind: "html", artifacts: htmlArtifacts })}><CodeXml size={16} /></button>}</span>{evidenceModal && createPortal(<Modal open title={evidenceModal.kind === "image" ? imageTitle : htmlTitle} onClose={() => setEvidenceModal(null)} className="modal--evidence">{modalArtifacts.map((artifact, index) => <figure className="persona-evidence" key={`${artifact.id ?? index}-${evidenceModal.kind}`}><figcaption>{artifact.name ?? artifact.id ?? `#${index + 1}`}</figcaption>{evidenceModal.kind === "image" ? <img src={artifactUrl(runId, iteration, artifact.screenshot!)} alt={artifact.name ?? artifact.id ?? ""} /> : <HtmlEvidenceViewer url={artifactUrl(runId, iteration, artifact.html!)} />}</figure>)}</Modal>, document.body)}</>;
}
