import { useState } from "react";
import type { Locale } from "../locales";
import { api } from "./api";

export type TemplateTranslation<T> = { content: T; cached: boolean; profile_name: string };

export function useTemplateTranslation<T>(
  kind: "runner-template" | "quick-start",
  templateId: string,
  locale: Locale,
) {
  const requestKey = `${kind}:${templateId}:${locale}`;
  const [result, setResult] = useState<{ key: string; content: T } | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const content = result?.key === requestKey ? result.content : null;

  const translate = async () => {
    if (content) {
      setVisible(true);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const result = await api<TemplateTranslation<T>>("/api/template-translations", "POST", {
        kind,
        template_id: templateId,
        locale,
      });
      setResult({ key: requestKey, content: result.content });
      setVisible(true);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  return { content: visible ? content : null, error, loading, showOriginal: () => setVisible(false), translate };
}
