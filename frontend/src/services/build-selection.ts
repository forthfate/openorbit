import type { Build } from "../domain/models";

const storageKey = (scope: "improvements" | "issues") => `orbit.last-build.${scope}`;

export function preferredBuildId(
  scope: "improvements" | "issues",
  builds: Build[],
  fallback: string,
): string {
  try {
    const saved = localStorage.getItem(storageKey(scope));
    return saved && builds.some((build) => build.id === saved) ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function savePreferredBuildId(scope: "improvements" | "issues", buildId: string) {
  try {
    if (buildId) localStorage.setItem(storageKey(scope), buildId);
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}
