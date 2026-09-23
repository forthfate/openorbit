import { addEdge, Background, BaseEdge, Controls, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow, type Connection, type Edge, type EdgeProps, type Node, type NodeProps, useEdgesState, useNodesState } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ChevronDown, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { VisualRunnerBlueprint, VisualRunnerEdge, VisualRunnerNode, VisualRunnerNodeKind } from "../domain/models";
import { localeMessageMap, locales, type Locale } from "../locales";
import { api } from "../services/api";
import { Modal } from "./ui/modal";
import { Tooltip } from "./ui/tooltip";
import { WorkflowNodeCard } from "./workflow-node-card";

export type { VisualRunnerBlueprint } from "../domain/models";

const phases = ["before_all", "before_each", "execute", "verify", "after_supervision", "after_each", "after_all"];
const visualNodeWidth = 250;
const visualNodeHeight = 140;
const phaseGroupPadding = 26;
const phaseGroupTitleHeight = 38;
const runnerLabels = localeMessageMap<Record<string, string>>("runnerLabels");
const blank = (): VisualRunnerBlueprint => ({ schema_version: 1, nodes: [], edges: [] });
const asFlowNode = (node: VisualRunnerNode): Node<VisualRunnerNode> => ({ id: node.id, position: node.position, data: node, type: "visual", zIndex: 3 });
const asFlowEdge = (edge: VisualRunnerEdge, index: number): Edge => ({ ...edge, id: `${edge.source}-${edge.target}-${index}`, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed }, data: { kind: edge.kind ?? "execution" }, sourceHandle: edge.source_port, targetHandle: edge.target_port });

type PaletteItem = { kind: VisualRunnerNodeKind; label: string; description?: string; phase?: string; inputs?: string[]; outputs?: string[]; config?: Record<string, unknown>; starter?: VisualStarter };
type VisualNodeCatalog = { kind: VisualRunnerNodeKind; group_key: string; title_key: string; description_key: string; display_name: string; default_inputs: string[]; default_outputs: string[]; default_config: Record<string, unknown>; is_custom_script: boolean };
type VisualStarter = { id: string; group_key: string; title_key: string; description_key: string; display_name?: string; blueprint: VisualRunnerBlueprint };
type CatalogResponse = { nodes: VisualNodeCatalog[]; starters: VisualStarter[] };
const textFor = (locale: Locale, key: string, fallback: string) => key.split(".").reduce<unknown>((value, part) => value && typeof value === "object" ? (value as Record<string, unknown>)[part] : undefined, locales[locale]) as string | undefined ?? fallback;
const catalogGroups = (locale: Locale, items: VisualNodeCatalog[], starters: VisualStarter[]): { id: string; label: string; items: PaletteItem[] }[] => {
  const groups = new Map<string, VisualNodeCatalog[]>();
  for (const item of items) groups.set(item.group_key, [...(groups.get(item.group_key) ?? []), item]);
  const nodeGroups = [...groups].map(([id, members]) => ({ id, label: textFor(locale, `visual.groups.${id}`, id), items: members.map((item) => ({ kind: item.kind, label: textFor(locale, item.title_key, item.display_name), description: textFor(locale, `visual.nodeGuidance.${item.kind}`, textFor(locale, item.description_key, "")), inputs: item.default_inputs, outputs: item.default_outputs, config: item.default_config })) }));
  return starters.length ? [{ id: "starters", label: textFor(locale, "visual.groups.starters", "Starter workflows"), items: starters.map((starter) => ({ kind: "custom_script", label: textFor(locale, starter.title_key, starter.display_name ?? starter.id), description: textFor(locale, starter.description_key, ""), starter })) }, ...nodeGroups] : nodeGroups;
};

function VisualNode({ data }: NodeProps<Node<VisualRunnerNode>>) {
  return <WorkflowNodeCard className="workflow-graph-node" title={data.title} inputs={data.inputs} outputs={data.outputs} leading={<Handle type="target" position={Position.Left} />} trailing={<Handle type="source" position={Position.Right} />} />;
}
type PhaseGroupData = { title: string; phase: string; count: number };
function VisualPhaseGroup({ data }: NodeProps<Node<PhaseGroupData>>) {
  return <div className="visual-runner-phase-group"><strong>{data.title}</strong><small>{data.count}</small></div>;
}
function VisualLoopEdge({ sourceX, sourceY, targetX, targetY, label, labelStyle, markerEnd, style }: EdgeProps) {
  const routeY = Math.min(sourceY, targetY) - 160;
  const outletX = sourceX + 40;
  const inletX = targetX - 40;
  const path = `M ${sourceX},${sourceY} L ${outletX},${sourceY} L ${outletX},${routeY} L ${inletX},${routeY} L ${inletX},${targetY} L ${targetX},${targetY}`;
  return <><BaseEdge path={path} markerEnd={markerEnd} style={style} /><EdgeLabelRenderer>{label && <div className="nodrag nopan" style={{ position: "absolute", transform: `translate(-50%, -50%) translate(${(sourceX + targetX) / 2}px,${routeY}px)`, ...labelStyle, background: "var(--surface-raised)", border: "1px solid var(--line)", borderRadius: 4, padding: "3px 5px", pointerEvents: "all" }}>{label}</div>}</EdgeLabelRenderer></>;
}
const nodeTypes = { visual: VisualNode, phase_group: VisualPhaseGroup };
const edgeTypes = { loop: VisualLoopEdge };
const phaseLabel = (phase: string) => phase.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const edgeLabelProps = {
  labelStyle: { fill: "var(--muted)", fontFamily: "'DM Mono', monospace", fontSize: 10 },
  labelBgStyle: { fill: "var(--surface-raised)", stroke: "var(--line)", strokeWidth: 1 },
  labelBgPadding: [5, 3] as [number, number],
  labelBgBorderRadius: 4,
};
const isBackEdge = (edge: Edge, nodes: Node<VisualRunnerNode>[]) => {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target) return false;
  if (source.id === target.id) return true;
  const sourcePhase = phases.indexOf(source.data.phase);
  const targetPhase = phases.indexOf(target.data.phase);
  if (sourcePhase >= 0 && targetPhase >= 0 && targetPhase !== sourcePhase) return targetPhase < sourcePhase;
  return nodes.indexOf(target) < nodes.indexOf(source);
};

function PaletteMaterialTooltip({ item, copy }: { item: PaletteItem; copy: Record<string, string> }) {
  const ports = (values: string[] | undefined, empty: string) => values?.length ? values.join(", ") : empty;
  return <div className="visual-runner-palette-tooltip">
    <strong>{item.label}</strong>
    {item.description && <p>{item.description}</p>}
    <dl>
      <div><dt>{copy.nodeType}</dt><dd><code>{item.starter ? copy.starterWorkflow : item.kind}</code></dd></div>
      <div><dt>{copy.inputs}</dt><dd><code>{ports(item.inputs, copy.noInputs)}</code></dd></div>
      <div><dt>{copy.outputs}</dt><dd><code>{ports(item.outputs, copy.noOutputs)}</code></dd></div>
    </dl>
  </div>;
}

export function VisualRunnerEditor({ blueprint, locale, onClose, onApply }: { blueprint?: VisualRunnerBlueprint; locale: Locale; onClose: () => void; onApply: (value: VisualRunnerBlueprint, source: string) => void }) {
  const copy = runnerLabels[locale];
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<VisualRunnerNode>>((blueprint ?? blank()).nodes.map(asFlowNode));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>((blueprint ?? blank()).edges.map(asFlowEdge));
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState("actions");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState<CatalogResponse>({ nodes: [], starters: [] });
  const phaseGroups = useMemo<Node<PhaseGroupData>[]>(() => phases.flatMap((phase) => {
    const members = nodes.filter((node) => node.data.phase === phase);
    if (!members.length) return [];
    const left = Math.min(...members.map((node) => node.position.x));
    const top = Math.min(...members.map((node) => node.position.y));
    const right = Math.max(...members.map((node) => node.position.x + visualNodeWidth));
    const bottom = Math.max(...members.map((node) => node.position.y + visualNodeHeight));
    const width = right - left + phaseGroupPadding * 2;
    const height = bottom - top + phaseGroupPadding * 2 + phaseGroupTitleHeight;
    return [{
      id: `phase-group:${phase}`,
      type: "phase_group",
      position: { x: left - phaseGroupPadding, y: top - phaseGroupPadding - phaseGroupTitleHeight },
      data: { title: phaseLabel(phase), phase, count: members.length },
      style: { width, height },
      // These nodes are derived on each canvas change, so React Flow cannot
      // retain its normal measurement pass for them. Supply their dimensions
      // to prevent its unmeasured-node visibility guard from hiding a group.
      measured: { width, height },
      draggable: false,
      selectable: false,
      connectable: false,
      // React Flow renders the grid background above its zero layer. Keep the
      // display-only group above that layer but below the executable nodes.
      zIndex: 2,
    }];
  }), [nodes]);
  // React Flow's editor state intentionally tracks executable nodes only.
  // Phase groups are display-only nodes and are excluded from persistence.
  const flowNodes = useMemo(() => [...phaseGroups as unknown as Node<VisualRunnerNode>[], ...nodes], [nodes, phaseGroups]);
  const flowEdges = useMemo(() => edges.map((edge) => {
    const loop = (edge.data?.kind as VisualRunnerEdge["kind"] | undefined) === "loop" || isBackEdge(edge, nodes);
    return { ...edge, ...edgeLabelProps, type: loop ? "loop" : "smoothstep", animated: loop };
  }), [edges, nodes]);
  const current = useMemo(() => nodes.find((node) => node.id === selectedNode)?.data, [nodes, selectedNode]);
  const currentEdge = useMemo(() => edges.find((edge) => edge.id === selectedEdge), [edges, selectedEdge]);
  const source = currentEdge && nodes.find((node) => node.id === currentEdge.source)?.data;
  const target = currentEdge && nodes.find((node) => node.id === currentEdge.target)?.data;
  useEffect(() => { api<CatalogResponse>("/api/visual-runners/catalog").then(setCatalog).catch(() => undefined); }, []);
  const catalogPalette = useMemo(() => catalogGroups(locale, catalog.nodes, catalog.starters), [catalog, locale]);
  const add = (item: PaletteItem) => { const id = `${item.kind}_${nodes.length + 1}`; const node: VisualRunnerNode = { id, kind: item.kind, title: item.label, phase: item.phase ?? "execute", inputs: item.inputs ?? [], outputs: item.outputs ?? [], config: item.config ?? {}, script: "# Write Python here. Put JSON-safe values in outputs.\n", position: { x: 120 + nodes.length * 36, y: 120 + nodes.length * 36 } }; setNodes((items) => [...items, asFlowNode(node)]); setSelectedNode(id); setSelectedEdge(null); };
  const addStarter = (starter: VisualStarter) => {
    const prefix = `${starter.id}_${nodes.length + 1}`;
    const starterNodes = starter.blueprint.nodes.map((node) => ({ ...node, id: `${prefix}_${node.id}`, title: textFor(locale, (node as VisualRunnerNode & { title_key?: string }).title_key ?? "", node.title), script: node.script ?? "" }));
    const starterEdges = starter.blueprint.edges.map((edge) => ({ ...edge, source: `${prefix}_${edge.source}`, target: `${prefix}_${edge.target}` }));
    setNodes((items) => [...items, ...starterNodes.map(asFlowNode)]);
    setEdges((items) => [...items, ...starterEdges.map((edge, index) => asFlowEdge(edge, edges.length + index))]);
    setSelectedNode(starterNodes[0].id);
    setSelectedEdge(null);
  };
  const patchNode = (value: Partial<VisualRunnerNode>) => current && setNodes((items) => items.map((node) => node.id === current.id ? { ...node, data: { ...node.data, ...value } } : node));
  const patchEdge = (value: Partial<Edge>) => currentEdge && setEdges((items) => items.map((edge) => edge.id === currentEdge.id ? { ...edge, ...value } : edge));
  const connect = (connection: Connection) => setEdges((items) => addEdge({ ...connection, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed }, data: { kind: "execution" } }, items));
  const save = async () => { const value: VisualRunnerBlueprint = { schema_version: 1, nodes: nodes.map((node) => ({ ...node.data, position: node.position })), edges: edges.map((edge) => ({ source: edge.source, target: edge.target, kind: (edge.data?.kind as VisualRunnerEdge["kind"]) ?? "execution", source_port: edge.sourceHandle ?? undefined, target_port: edge.targetHandle ?? undefined, label: typeof edge.label === "string" ? edge.label : undefined })) }; setSaving(true); setError(""); try { const result = await api<{ blueprint: VisualRunnerBlueprint; source: string }>("/api/visual-runners/preview", "POST", { blueprint: value }); onApply(result.blueprint, result.source); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); } finally { setSaving(false); } };
  const updateConfig = (text: string) => { try { const config = JSON.parse(text); if (!config || Array.isArray(config) || typeof config !== "object") throw new Error(); patchNode({ config }); setError(""); } catch { setError("Configuration must be a JSON object."); } };
  const updateWhen = (text: string) => { try { patchNode({ when: text.trim() ? JSON.parse(text) : undefined }); setError(""); } catch { setError("Run condition must be valid JSON."); } };
  return <Modal open title={copy.visualEditorTitle} onClose={onClose} className="modal--visual-runner"><div className="visual-runner-editor"><section className="visual-runner-palette"><strong>{copy.visualNodes}</strong>{catalogPalette.map((group) => <div className="visual-runner-palette-group" key={group.id}><button className="visual-runner-palette-group__trigger" type="button" aria-expanded={openGroup === group.id} onClick={() => setOpenGroup(openGroup === group.id ? "" : group.id)}>{group.label}<ChevronDown size={14} /></button>{openGroup === group.id && <div className="visual-runner-palette-group__items">{group.items.map((item) => <Tooltip key={item.starter?.id ?? item.kind} content={<PaletteMaterialTooltip item={item} copy={copy} />}><button className="ghost" type="button" onClick={() => item.starter ? addStarter(item.starter) : add(item)}>{item.label}</button></Tooltip>)}</div>}</div>)}</section><div className="visual-runner-canvas"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={connect} onNodeClick={(_, node) => { if (node.type !== "phase_group") { setSelectedNode(node.id); setSelectedEdge(null); } }} onEdgeClick={(_, edge) => { setSelectedEdge(edge.id); setSelectedNode(null); }} attributionPosition="top-left" fitView><Background gap={20} /><Controls position="bottom-right" /></ReactFlow></div><section className="visual-runner-inspector">{current ? <><strong>{current.title}</strong><label>{copy.nodeTitle}<input value={current.title} onChange={(event) => patchNode({ title: event.target.value })} /></label><label>{copy.phase}<select value={current.phase} onChange={(event) => patchNode({ phase: event.target.value })}>{phases.map((phase) => <option key={phase}>{phaseLabel(phase)}</option>)}</select></label><label>{copy.inputs}<input value={current.inputs.join(", ")} onChange={(event) => patchNode({ inputs: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label><label>{copy.outputs}<input value={current.outputs.join(", ")} onChange={(event) => patchNode({ outputs: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>{current.kind === "custom_script" && <label>{copy.customScript}<textarea value={current.script} onChange={(event) => patchNode({ script: event.target.value })} /></label>}<label>Configuration (JSON)<textarea value={JSON.stringify(current.config, null, 2)} onChange={(event) => updateConfig(event.target.value)} /></label><label>Run when (JSON)<textarea value={current.when === undefined ? "" : JSON.stringify(current.when, null, 2)} placeholder='{"$exists":{"$input":"value"}}' onChange={(event) => updateWhen(event.target.value)} /></label></> : currentEdge && source && target ? <><strong>{copy.connection}</strong><label>{copy.connectionType}<select value={(currentEdge.data?.kind as string) ?? "execution"} onChange={(event) => patchEdge({ data: { kind: event.target.value } })}><option value="execution">{copy.execution}</option><option value="data">{copy.data}</option><option value="condition">{copy.condition}</option><option value="loop">{copy.loop}</option></select></label>{currentEdge.data?.kind === "data" && <><label>{copy.sourceOutput}<select value={currentEdge.sourceHandle ?? ""} onChange={(event) => patchEdge({ sourceHandle: event.target.value, data: { kind: "data" } })}><option value="">{copy.selectOutput}</option>{source.outputs.map((port) => <option key={port}>{port}</option>)}</select></label><label>{copy.targetInput}<select value={currentEdge.targetHandle ?? ""} onChange={(event) => patchEdge({ targetHandle: event.target.value, data: { kind: "data" } })}><option value="">{copy.selectInput}</option>{target.inputs.map((port) => <option key={port}>{port}</option>)}</select></label></>}<label>{copy.label}<input value={typeof currentEdge.label === "string" ? currentEdge.label : ""} onChange={(event) => patchEdge({ label: event.target.value })} /></label></> : <p>{copy.selectVisualItem}</p>}</section></div><div className="modal-actions"><small className="hint">{error}</small><button className="approve" type="button" disabled={saving} onClick={save}><Save size={14} />{copy.applyVisualRunner}</button></div></Modal>;
}
