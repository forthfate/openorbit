"""Bounded HTTP invocation for a server-hosted evaluation target."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class RemoteInvocation:
    endpoint: str
    method: str = "POST"
    timeout_seconds: int = 60
    auth_secret_env: str = ""
    auth_header: str = "Authorization"
    headers: dict[str, str] | None = None
    payload: dict | None = None

    def validate(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError(
                "Remote agent endpoint must be an absolute http(s) URL without embedded credentials."
            )
        if self.method not in {"GET", "POST", "PUT"}:
            raise ValueError("Remote agent method must be GET, POST, or PUT.")
        if not 1 <= self.timeout_seconds <= 900:
            raise ValueError("Remote agent timeout must be between 1 and 900 seconds.")
        if self.headers is not None:
            if len(self.headers) > 32:
                raise ValueError("Remote agent supports at most 32 custom headers.")
            for name, value in self.headers.items():
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or any(character in name for character in "\r\n:")
                ):
                    raise ValueError("Remote agent header names must be valid HTTP header names.")
                if not isinstance(value, str) or "\r" in value or "\n" in value:
                    raise ValueError("Remote agent header values must be single-line strings.")

    def invoke(self) -> tuple[int, str]:
        self.validate()
        headers = {"Content-Type": "application/json"}
        headers.update(self.headers or {})
        if self.auth_secret_env:
            secret = os.environ.get(self.auth_secret_env, "")
            if not secret:
                raise ValueError(
                    f"Remote agent secret environment variable is not set: {self.auth_secret_env}"
                )
            headers[self.auth_header] = secret
        response = requests.request(
            self.method, self.endpoint, headers=headers, json=self.payload, timeout=self.timeout_seconds
        )
        return response.status_code, response.text[:12_000]
