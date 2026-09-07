from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build the control-room bundle before packaging a wheel from source."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if os.environ.get("OPENORBIT_SKIP_FRONTEND_BUILD") == "1":
            return
        root = Path(self.root)
        if not shutil.which("pnpm"):
            raise RuntimeError(
                "Building OpenOrbit from Git requires Node.js 24+ and pnpm. "
                "Install them, then run the pip command again."
            )
        subprocess.run(["pnpm", "run", "build"], cwd=root, check=True)
