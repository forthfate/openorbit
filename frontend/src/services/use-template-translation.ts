import { useState } from "react";
import type { Locale } from "../locales";
import { api } from "./api";

export type TemplateTranslation<T> = { content: T; cached: boolean; profile_name: string };

export function useTemplateTranslations<T>(
  kind: "runner-template" | "quick-start" | "supervisor-result",
  templateIds: string[],
  locale: Locale,
) {
  const requestKey = (templateId: string) => `${kind}:${templateId}:${locale}`;
  const [results, setResults] = useState<Record<string, T>>({});
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const content = (templateId: string) => visible ? results[requestKey(templateId)] ?? null : null;

  const translate = async () => {
    const missingIds = templateIds.filter((templateId) => !results[requestKey(templateId)]);
    if (!missingIds.length) {
      setVisible(true);
      return;
    }
    setLoading(true);
    setError(false);
    const responses = await Promise.allSettled(
      missingIds.map(async (templateId) => ({
        templateId,
        result: await api<TemplateTranslation<T>>("/api/template-translations", "POST", {
          kind,
          template_id: templateId,
          locale,
        }),
      })),
    );
    const translated = responses.filter(
      (response): response is PromiseFulfilledResult<{ templateId: string; result: TemplateTranslation<T> }> =>
        response.status === "fulfilled",
    );
    if (translated.length) {
      setResults((current) => ({
        ...current,
        ...Object.fromEntries(translated.map(({ value }) => [requestKey(value.templateId), value.result.content])),
      }));
      setVisible(true);
    }
    if (translated.length !== responses.length) {
      setError(true);
    }
    setLoading(false);
  };

  return { content, error, loading, showOriginal: () => setVisible(false), translate };
}
