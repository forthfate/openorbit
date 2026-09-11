import { Background, BaseEdge, Controls, EdgeLabelRenderer, Handle, MarkerType, Position, ReactFlow, type EdgeProps, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from "react";

export type WorkflowGraphNode = { id: string; title: string; phase?: string | null; inputs?: string[]; outputs?: string[]; description?: string | null; status?: "idle" | "running" | "succeeded" | "failed" | "skipped" };
export type WorkflowGraphEdge = { source: string; target: string; kind?: "execution" | "data" | "condition" | "loop" | "error"; label?: string | null; source_port?: string | null; target_port?: string | null };
type GraphNodeData = WorkflowGraphNode;
type GraphZoneData = { title: string; annotation: string };
type NodeSize = { width: number; height: number };
type Measurements = { key: string; sizes: Record<string, NodeSize> };
const lifecyclePhases = ["before_all", "before_each", "execute", "verify", "after_each", "after_all"];
const NodeMeasurementContext = createContext<(id: string, size: NodeSize) => void>(() => undefined);
function LoopEdge({ sourceX, sourceY, targetX, targetY, label, labelStyle, markerEnd, style }: EdgeProps) {
  const routeY = Math.min(sourceY, targetY) - 160;
  const path = `M ${sourceX},${sourceY} L ${sourceX},${routeY} L ${targetX},${routeY} L ${targetX},${targetY}`;
  return <><BaseEdge path={path} markerEnd={markerEnd} style={style} /><EdgeLabelRenderer>{label && <div className="nodrag nopan" style={{ position: "absolute", transform: `translate(-50%, -50%) translate(${(sourceX + targetX) / 2}px,${routeY}px)`, ...labelStyle, background: "var(--surface-raised)", border: "1px solid var(--line)", borderRadius: 4, padding: "3px 5px", pointerEvents: "all" }}>{label}</div>}</EdgeLabelRenderer></>;
}
function OrbitNode({ id, data }: NodeProps<Node<GraphNodeData>>) {
  const reportSize = useContext(NodeMeasurementContext);
  const element = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return;
    const report = () => reportSize(id, { width: node.offsetWidth, height: node.offsetHeight });
    report();
    const observer = new ResizeObserver(report);
    observer.observe(node);
    return () => observer.disconnect();
  }, [id, reportSize]);
  return <div ref={element} className={`workflow-graph-node workflow-graph-node--${data.status ?? "idle"}`}><Handle type="target" position={Position.Left} /><header style={{ margin: 0 }}><small>Function</small><strong>{data.title}</strong></header>{data.description && <p>{data.description}</p>}<footer style={{ margin: 0 }}>{data.inputs?.map((port) => <span key={port}>← {port}</span>)}{data.outputs?.map((port) => <span key={port}>{port} →</span>)}</footer><Handle type="source" position={Position.Right} /></div>;
}
const nodeTypes = {
  orbit: OrbitNode,
  zone: ({ data }: NodeProps<Node<GraphZoneData>>) => <div className="workflow-graph-zone"><strong>{data.title}</strong><small>{data.annotation}</small></div>,
};
const edgeTypes = { loop: LoopEdge };
const zoneTitle = (phase: string) => phase.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const height = (node: WorkflowGraphNode) => Math.max(108, 60 + (node.description ? Math.ceil(node.description.length / 32) * 16 + 18 : 0) + Math.ceil([...(node.inputs ?? []), ...(node.outputs ?? [])].length / 2) * 18);

export function WorkflowGraph({ nodes, edges, className = "" }: { nodes: WorkflowGraphNode[]; edges: WorkflowGraphEdge[]; className?: string }) {
  const [measurements, setMeasurements] = useState<Measurements>({ key: "", sizes: {} });
  const measurementKey = JSON.stringify(nodes.map(({ id, title, phase, inputs, outputs, description }) => ({ id, title, phase, inputs, outputs, description })));
  const onMeasure = useCallback((id: string, size: NodeSize) => setMeasurements((current) => {
    const sizes = current.key === measurementKey ? current.sizes : {};
    return current.key === measurementKey && sizes[id]?.width === size.width && sizes[id]?.height === size.height ? current : { key: measurementKey, sizes: { ...sizes, [id]: size } };
  }), [measurementKey]);
  const measured = useMemo(() => measurements.key === measurementKey ? measurements.sizes : {}, [measurementKey, measurements]);
  const measurementsReady = nodes.length === 0 || nodes.every((node) => measured[node.id]);
  const layout = useMemo(() => {
    const presentPhases = [...new Set(nodes.map((node) => node.phase ?? "Ungrouped"))];
    const phases = [...lifecyclePhases.filter((phase) => presentPhases.includes(phase)), ...presentPhases.filter((phase) => !lifecyclePhases.includes(phase))];
    const byPhase = new Map(phases.map((phase) => [phase, nodes.filter((node) => (node.phase ?? "Ungrouped") === phase)]));
    const rendered: Node[] = phases.flatMap((phase, column) => {
      const zoneId = `zone:${phase}`;
      let y = 72;
      const functions = byPhase.get(phase) ?? [];
      const children = functions.map((node) => {
        const size = measured[node.id] ?? { width: 250, height: height(node) };
        const child = { id: node.id, type: "orbit", data: node, position: { x: 30, y }, parentId: zoneId, extent: "parent" } as Node;
        y += size.height + 48;
        return child;
      });
      return [
        { id: zoneId, type: "zone", data: { title: zoneTitle(phase), annotation: "@runner.phase" }, position: { x: column * 340, y: 0 }, style: { width: 310, height: Math.max(210, y - (functions.length ? 48 : 0) + 64) }, draggable: false, selectable: false } as Node,
        ...children,
      ];
    });
    return { nodes: rendered, edges: edges.map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, label: edge.label ?? undefined, labelStyle: { fill: "var(--muted)", fontFamily: "'DM Mono', monospace", fontSize: 10 }, labelBgStyle: { fill: "var(--surface-raised)", stroke: "var(--line)", strokeWidth: 1 }, labelBgPadding: [5, 3] as [number, number], labelBgBorderRadius: 4, type: edge.kind === "loop" ? "loop" : "smoothstep", animated: edge.kind === "loop", markerEnd: { type: MarkerType.ArrowClosed }, className: `workflow-graph-edge workflow-graph-edge--${edge.kind ?? "execution"}` })) };
  }, [nodes, edges, measured]);
  return <div className={`workflow-graph ${className}`} style={{ visibility: measurementsReady ? "visible" : "hidden" }}><NodeMeasurementContext.Provider value={onMeasure}><ReactFlow nodes={layout.nodes} edges={layout.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView minZoom={0.2} nodesDraggable={false} panOnDrag attributionPosition="top-left"><Background gap={20} size={1} /><Controls showInteractive={false} position="bottom-right" /></ReactFlow></NodeMeasurementContext.Provider></div>;
}
