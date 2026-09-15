import { useEffect, useState } from "react";
import type { Locale } from "../locales";
import { api } from "./api";

export type TemplateTranslation<T> = { content: T; cached: boolean; profile_name: string };
type CachedTemplateTranslation<T> = { content: T | null };

export function useTemplateTranslations<T>(
  kind: "runner-template" | "quick-start" | "supervisor-result",
  templateIds: string[],
  locale: Locale,
) {
  const requestKey = (templateId: string) => `${kind}:${templateId}:${locale}`;
  const templateIdKey = [...new Set(templateIds)].sort().join("\u0000");
  const cacheKey = `${kind}:${locale}:${templateIdKey}`;
  const [results, setResults] = useState<Record<string, T>>({});
  const [visibleIds, setVisibleIds] = useState<Set<string>>(() => new Set());
  const [loadingIds, setLoadingIds] = useState<Set<string>>(() => new Set());
  const [loadedCacheKey, setLoadedCacheKey] = useState("");
  const [error, setError] = useState(false);

  const content = (templateId: string) =>
    visibleIds.has(requestKey(templateId)) ? results[requestKey(templateId)] ?? null : null;
  const isLoading = (requestedIds: string[]) =>
    requestedIds.some((templateId) => loadingIds.has(requestKey(templateId)));
  const cacheLoading = Boolean(templateIdKey) && loadedCacheKey !== cacheKey;

  useEffect(() => {
    const ids = templateIdKey ? templateIdKey.split("\u0000") : [];
    if (!ids.length) return;
    let active = true;
    Promise.allSettled(
      ids.map(async (templateId) => ({
        templateId,
        result: await api<CachedTemplateTranslation<T>>("/api/template-translations/cached", "POST", {
          kind,
          template_id: templateId,
          locale,
        }),
      })),
    ).then((responses) => {
      if (!active) return;
      const cached = responses
        .filter(
          (response): response is PromiseFulfilledResult<{
            templateId: string;
            result: CachedTemplateTranslation<T>;
          }> => response.status === "fulfilled" && response.value.result.content !== null,
        )
        .map(({ value }) => ({ templateId: value.templateId, content: value.result.content as T }));
      if (cached.length) {
        setResults((current) => ({
          ...current,
          ...Object.fromEntries(cached.map(({ templateId, content }) => [requestKey(templateId), content])),
        }));
        setVisibleIds((current) => new Set([...current, ...cached.map(({ templateId }) => requestKey(templateId))]));
      }
      setLoadedCacheKey(cacheKey);
    });
    return () => {
      active = false;
    };
  }, [cacheKey, kind, locale, templateIdKey]);

  const translate = async (requestedIds = templateIds) => {
    const ids = [...new Set(requestedIds)];
    const missingIds = ids.filter((templateId) => !results[requestKey(templateId)]);
    if (!missingIds.length) {
      setVisibleIds((current) => new Set([...current, ...ids.map(requestKey)]));
      return;
    }
    setLoadingIds((current) => new Set([...current, ...missingIds.map(requestKey)]));
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
    }
    const translatedIds = translated.map(({ value }) => value.templateId);
    const availableIds = ids.filter((templateId) =>
      Boolean(results[requestKey(templateId)]) || translatedIds.includes(templateId),
    );
    if (availableIds.length) {
      setVisibleIds((current) => new Set([...current, ...availableIds.map(requestKey)]));
    }
    if (translated.length !== responses.length) {
      setError(true);
    }
    setLoadingIds((current) => {
      const completed = new Set(missingIds.map(requestKey));
      return new Set([...current].filter((key) => !completed.has(key)));
    });
  };

  const showOriginal = (requestedIds = templateIds) => {
    const keys = new Set(requestedIds.map(requestKey));
    setVisibleIds((current) => new Set([...current].filter((key) => !keys.has(key))));
  };

  return { cacheLoading, content, error, loading: loadingIds.size > 0, isLoading, showOriginal, translate };
}
