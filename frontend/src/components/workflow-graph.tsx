import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

export type WorkflowGraphNode = { id: string; title: string; phase?: string | null; inputs?: string[]; outputs?: string[]; description?: string | null; status?: "idle" | "running" | "succeeded" | "failed" | "skipped" };
export type WorkflowGraphEdge = { source: string; target: string; kind?: "execution" | "data" | "condition" | "loop" | "error"; label?: string | null; source_port?: string | null; target_port?: string | null };
type GraphNodeData = WorkflowGraphNode;
type GraphZoneData = { title: string; annotation: string };
const nodeTypes = {
  orbit: ({ data }: NodeProps<Node<GraphNodeData>>) => <div className={`workflow-graph-node workflow-graph-node--${data.status ?? "idle"}`}><Handle type="target" position={Position.Left} /><header><small>Function</small><strong>{data.title}</strong></header>{data.description && <p>{data.description}</p>}<footer>{data.inputs?.map((port) => <span key={port}>← {port}</span>)}{data.outputs?.map((port) => <span key={port}>{port} →</span>)}</footer><Handle type="source" position={Position.Right} /></div>,
  zone: ({ data }: NodeProps<Node<GraphZoneData>>) => <div className="workflow-graph-zone"><strong>{data.title}</strong><small>{data.annotation}</small></div>,
};

const zoneTitle = (phase: string) => phase.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export function WorkflowGraph({ nodes, edges, className = "" }: { nodes: WorkflowGraphNode[]; edges: WorkflowGraphEdge[]; className?: string }) {
  const [flowNodes, flowEdges] = useMemo(() => {
    const phases = [...new Set(nodes.map((node) => node.phase ?? "Ungrouped"))];
    const grouped = new Map(phases.map((phase) => [phase, nodes.filter((node) => (node.phase ?? "Ungrouped") === phase)]));
    const rendered: Node[] = [];
    phases.forEach((phase, column) => {
      const functions = grouped.get(phase) ?? [];
      const zoneId = `zone:${phase}`;
      rendered.push({ id: zoneId, type: "zone", data: { title: zoneTitle(phase), annotation: "@runner.phase" }, position: { x: column * 340, y: 0 }, style: { width: 320, height: Math.max(210, functions.length * 210 + 72) }, draggable: false, selectable: false });
      functions.forEach((node, row) => rendered.push({ id: node.id, type: "orbit", data: node, position: { x: 30, y: 72 + row * 210 }, parentId: zoneId, extent: "parent" }));
    });
    const renderedEdges: Edge[] = edges.map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, label: edge.label ?? undefined, type: "smoothstep", animated: edge.kind === "loop", markerEnd: { type: MarkerType.ArrowClosed }, className: `workflow-graph-edge workflow-graph-edge--${edge.kind ?? "execution"}` }));
    return [rendered, renderedEdges];
  }, [nodes, edges]);
  return <div className={`workflow-graph ${className}`}><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView minZoom={0.2} nodesDraggable panOnDrag attributionPosition="top-left"><Background gap={20} size={1} /><Controls showInteractive={false} position="bottom-right" /></ReactFlow></div>;
}
