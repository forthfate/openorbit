import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3001" });

test("imports a Quick Start ZIP package through the UI", async ({ page }) => {
  const suffix = Date.now().toString();
  const quickStartId = `example.e2e-package-${suffix}`;
  const packageRoot = mkdtempSync(join(tmpdir(), "orbit-quick-start-"));
  const packageDirectory = join(packageRoot, "e2e-package");
  const archive = join(packageRoot, "e2e-package.zip");
  const catalog = resolve(process.cwd(), "..", "templates", "quick-starts", "openorbit.ai-experience-improvement");
  const applicationData = process.env.ORBIT_APP_DATA
    ?? join(process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share"), "orbit");
  const applicationPackage = join(applicationData, "quick-starts", quickStartId);

  try {
    mkdirSync(packageDirectory);
    const manifest = JSON.parse(readFileSync(join(catalog, "manifest.json"), "utf8"));
    manifest.id = quickStartId;
    manifest.name = `E2E ZIP Quick Start ${suffix}`;
    writeFileSync(join(packageDirectory, "manifest.json"), JSON.stringify(manifest, null, 2));
    copyFileSync(join(catalog, "runner.py"), join(packageDirectory, "runner.py"));
    writeFileSync(join(packageDirectory, "README.md"), "# E2E ZIP package\n");
    writeFileSync(join(packageDirectory, "LICENSE"), "OpenOrbit License\n");
    execFileSync(
      "python3",
      [
        "-c",
        "import pathlib, sys, zipfile; root = pathlib.Path(sys.argv[2]); archive = zipfile.ZipFile(sys.argv[1], 'w'); [archive.write(path, path.relative_to(root.parent)) for path in root.rglob('*') if path.is_file()]; archive.close()",
        archive,
        packageDirectory,
      ],
    );

    await page.goto("/builds");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByRole("button", { name: "Start with Quick Start" }).click();
    await page.locator('input[type="file"]').setInputFiles(archive);
    await expect(page.getByText(manifest.name, { exact: true })).toBeVisible();
  } finally {
    rmSync(applicationPackage, { recursive: true, force: true });
    rmSync(packageRoot, { recursive: true, force: true });
  }
});

test("imports a Runner Template ZIP package through the UI", async ({ page }) => {
  const suffix = Date.now().toString();
  const templateId = `e2e-runner-${suffix}`;
  const packageRoot = mkdtempSync(join(tmpdir(), "orbit-runner-template-"));
  const packageDirectory = join(packageRoot, "e2e-runner");
  const archive = join(packageRoot, "e2e-runner.zip");
  const applicationData = process.env.ORBIT_APP_DATA
    ?? join(process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share"), "orbit");
  const applicationPackage = join(applicationData, "runner-templates", templateId);

  try {
    mkdirSync(packageDirectory);
    writeFileSync(
      join(packageDirectory, "template.json"),
      JSON.stringify({ id: templateId, name: `E2E ZIP Runner ${suffix}`, description: "UI ZIP import test." }),
    );
    writeFileSync(join(packageDirectory, "runner.py"), "from orbit_sdk import runner\n");
    writeFileSync(join(packageDirectory, "README.md"), "# E2E ZIP runner\n");
    writeFileSync(join(packageDirectory, "LICENSE"), "OpenOrbit License\n");
    execFileSync(
      "python3",
      [
        "-c",
        "import pathlib, sys, zipfile; root = pathlib.Path(sys.argv[2]); archive = zipfile.ZipFile(sys.argv[1], 'w'); [archive.write(path, path.relative_to(root.parent)) for path in root.rglob('*') if path.is_file()]; archive.close()",
        archive,
        packageDirectory,
      ],
    );

    await page.goto("/assets");
    const runners = page
      .locator("section.panel.app-settings")
      .filter({ has: page.getByRole("heading", { name: /^Runners/ }) });
    await runners.getByRole("button", { name: "Create", exact: true }).click();
    await page.locator('input[type="file"]').setInputFiles(archive);
    await expect(page.getByText(`E2E ZIP Runner ${suffix}`, { exact: true })).toBeVisible();
  } finally {
    rmSync(applicationPackage, { recursive: true, force: true });
    rmSync(packageRoot, { recursive: true, force: true });
  }
});
