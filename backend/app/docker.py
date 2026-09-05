"""Linux-only Docker availability checks and safe executor configuration."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DockerStatus:
    supported: bool
    available: bool
    reason: str
    version: str | None = None


def preflight_docker() -> DockerStatus:
    """Return Docker Engine availability without creating images or containers."""
    if platform.system() != "Linux":
        return DockerStatus(False, False, "Docker parallel execution is supported on Linux only.")
    executable = shutil.which("docker")
    if not executable:
        return DockerStatus(True, False, "Docker CLI is not installed or not on PATH.")
    result = subprocess.run(
        [executable, "version", "--format", "{{.Server.Version}}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return DockerStatus(True, False, "Docker daemon is not reachable.")
    return DockerStatus(True, True, "Docker Engine is ready.", result.stdout.strip())
