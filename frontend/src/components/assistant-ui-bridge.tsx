/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from "react";

type ControlKind = "text" | "select" | "radio" | "checkbox" | "number";
type UiControl = {
  id: string;
  label: string;
  kind: ControlKind;
  value: string | number | boolean | null;
  options?: { value: string; label: string; enabled?: boolean }[];
  enabled?: boolean;
  setValue: (value: unknown) => void | Promise<void>;
};
type UiAction = {
  id: string;
  label: string;
  requiresConfirmation?: boolean;
  run: (value: unknown) => void | Promise<void>;
};
type UiComponent = {
  id: string;
  parentId?: string;
  title: string;
  getState: () => Record<string, unknown>;
  controls?: UiControl[];
  actions?: UiAction[];
};
export type AssistantUiCommand =
  | { type: "get_context"; component_id?: string }
  | { type: "interact"; component_id: string; revision: number; operation: "set_control_value" | "invoke_action"; target_id: string; value?: unknown };
type AssistantUiBridge = {
  sessionId: string;
  register: (component: UiComponent) => () => void;
  handleCommand: (command: AssistantUiCommand) => Promise<Record<string, unknown>>;
};

const BridgeContext = createContext<AssistantUiBridge | null>(null);
const sessionStorageKey = "orbit.assistant.ui-session";

const sessionId = () => {
  const existing = sessionStorage.getItem(sessionStorageKey);
  if (existing) return existing;
  const next = crypto.randomUUID();
  sessionStorage.setItem(sessionStorageKey, next);
  return next;
};

export function AssistantUiProvider({ children }: { children: ReactNode }) {
  const components = useRef(new Map<string, UiComponent>());
  const revision = useRef(0);
  const register = useCallback((component: UiComponent) => {
    components.current.set(component.id, component);
    revision.current += 1;
    return () => {
      components.current.delete(component.id);
      revision.current += 1;
    };
  }, []);
  const contextSnapshot = useCallback((componentId?: string) => {
    const registered = [...components.current.values()];
    const listed = registered
      .filter(
        (component) =>
          !componentId ||
          component.id === componentId ||
          component.parentId === componentId ||
          component.id.startsWith(`${componentId}.`),
      )
      .map((component) => ({
        id: component.id,
        parent_id: component.parentId,
        title: component.title,
        state: component.getState(),
        controls: (component.controls ?? []).filter((control) => control.enabled !== false).map((control) => ({
          id: control.id,
          label: control.label,
          kind: control.kind,
          value: control.value,
          options: control.options?.filter((option) => option.enabled !== false),
        })),
        actions: (component.actions ?? []).map((action) => ({
          id: action.id,
          label: action.label,
          requires_confirmation: Boolean(action.requiresConfirmation),
        })),
      }));
    const result = {
      ok: true,
      revision: revision.current,
      components: listed,
      diagnostics: {
        requested_component_id: componentId ?? null,
        registered_component_ids: registered.map((component) => component.id),
        matched_component_ids: listed.map((component) => component.id),
      },
    };
    console.info("[Orbit Assistant UI] context snapshot", result);
    return result;
  }, []);
  const handleCommand = useCallback(async (command: AssistantUiCommand) => {
    console.info("[Orbit Assistant UI] command received", command);
    if (command.type === "get_context") return contextSnapshot(command.component_id);
    if (command.revision !== revision.current)
      return { ok: false, error: "The UI changed after this context was read.", error_code: "stale_revision", revision: revision.current };
    const component = components.current.get(command.component_id);
    if (!component) return { ok: false, error: "The requested UI component is no longer visible." };
    if (command.operation === "set_control_value") {
      const control = component.controls?.find((item) => item.id === command.target_id && item.enabled !== false);
      if (!control) return { ok: false, error: "The requested UI control is unavailable." };
      if (control.options && !control.options.some((option) => option.value === command.value && option.enabled !== false))
        return { ok: false, error: "The requested option is unavailable." };
      await control.setValue(command.value);
    } else {
      const action = component.actions?.find((item) => item.id === command.target_id);
      if (!action) return { ok: false, error: "The requested UI action is unavailable." };
      await action.run(command.value);
      if (action.requiresConfirmation)
        return { ok: true, status: "confirmation_required", revision: revision.current };
    }
    return { ok: true, revision: revision.current, context: contextSnapshot(command.component_id) };
  }, [contextSnapshot]);
  const value = useMemo(() => ({ sessionId: sessionId(), register, handleCommand }), [handleCommand, register]);
  return <BridgeContext.Provider value={value}>{children}</BridgeContext.Provider>;
}

export function useAssistantUiBridge() {
  const bridge = useContext(BridgeContext);
  if (!bridge) throw new Error("AssistantUiProvider is required.");
  return bridge;
}
