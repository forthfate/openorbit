import type { Build } from "../domain/models";

const storageKey = (scope: "improvements") => `orbit.last-build.${scope}`;
const rangeStorageKey = (scope: "improvements") => `orbit.last-range.${scope}`;
const validRangeHours = new Set([0, 24, 72, 168, 720]);

export function preferredBuildId(
  scope: "improvements",
  builds: Build[],
  fallback: string,
): string {
  try {
    const saved = sessionStorage.getItem(storageKey(scope));
    return saved && builds.some((build) => build.id === saved) ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function savePreferredBuildId(scope: "improvements", buildId: string) {
  try {
    if (buildId) sessionStorage.setItem(storageKey(scope), buildId);
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function preferredRangeHours(scope: "improvements", fallback: number): number {
  try {
    const saved = Number(sessionStorage.getItem(rangeStorageKey(scope)));
    return validRangeHours.has(saved) ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function savePreferredRangeHours(scope: "improvements", hours: number) {
  try {
    if (validRangeHours.has(hours)) sessionStorage.setItem(rangeStorageKey(scope), String(hours));
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}
