import type { Build } from "./models";

export type AssetUsage = {
  profiles: Map<string, number>;
  executionEnvironments: Map<string, number>;
  targetEnvironments: Map<string, number>;
  runners: Map<string, number>;
  promptTemplates: Map<string, number>;
  testCaseSets: Map<string, number>;
};

const countReferences = (builds: Build[], key: keyof Build) => {
  const usage = new Map<string, number>();
  for (const build of builds) {
    const value = build[key];
    if (typeof value === "string" && value) {
      usage.set(value, (usage.get(value) ?? 0) + 1);
    }
  }
  return usage;
};

/** Counts current build references; historic run snapshots are intentionally excluded. */
export const buildAssetUsage = (builds: Build[]): AssetUsage => ({
  profiles: countReferences(builds, "model_profile_name"),
  executionEnvironments: countReferences(builds, "execution_environment_id"),
  targetEnvironments: countReferences(builds, "target_environment_id"),
  runners: countReferences(builds, "runner_id"),
  promptTemplates: countReferences(builds, "manager_template_id"),
  testCaseSets: countReferences(builds, "test_case_set_id"),
});
