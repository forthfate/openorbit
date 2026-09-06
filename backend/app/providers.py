"""Provider adapters. Secrets remain in environment variables, never dashboard state."""

from __future__ import annotations

import configparser
import hashlib
import hmac
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests


@dataclass(frozen=True)
class ModelSettings:
    provider: str = "azure-openai"
    model: str = ""
    endpoint: str = ""
    region: str = "us-east-1"
    secret_env: str = "AZURE_OPENAI_API_KEY"
    aws_profile: str = ""


class AzureOpenAIProvider:
    def complete(self, settings: ModelSettings, prompt: str) -> str:
        key = os.environ.get(settings.secret_env, "")
        if not key or not settings.endpoint or not settings.model:
            raise RuntimeError(
                "Azure OpenAI provider requires endpoint, model, and configured secret environment variable."
            )
        response = requests.post(
            f"{settings.endpoint.rstrip('/')}/responses",
            headers={"api-key": key, "Content-Type": "application/json"},
            json={"model": settings.model, "input": prompt},
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text
        # Azure's Responses endpoint may omit the convenience `output_text`
        # field and retain the generated text in message content blocks.
        parts = []
        for message in payload.get("output", []):
            if not isinstance(message, dict):
                continue
            for content in message.get("content", []):
                if (
                    isinstance(content, dict)
                    and content.get("type") == "output_text"
                    and isinstance(content.get("text"), str)
                ):
                    parts.append(content["text"])
        return "".join(parts)


def _aws_profile_credentials(profile: str) -> tuple[str, str, str]:
    """Resolve a named AWS CLI profile without requiring the boto3 SDK."""
    try:
        result = subprocess.run(
            ["aws", "configure", "export-credentials", "--profile", profile, "--format", "process"],
            capture_output=True,
            check=True,
            text=True,
            timeout=15,
        )
        exported = json.loads(result.stdout)
        access_key = str(exported.get("AccessKeyId", ""))
        secret_key = str(exported.get("SecretAccessKey", ""))
        session_token = str(exported.get("SessionToken", ""))
        if access_key and secret_key:
            return access_key, secret_key, session_token
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        pass

    shared_credentials = os.environ.get("AWS_SHARED_CREDENTIALS_FILE", "")
    credentials_path = (
        Path(shared_credentials).expanduser() if shared_credentials else Path.home() / ".aws" / "credentials"
    )
    parser = configparser.ConfigParser()
    parser.read(credentials_path)
    if not parser.has_section(profile):
        return "", "", ""
    section = parser[profile]
    return (
        section.get("aws_access_key_id", ""),
        section.get("aws_secret_access_key", ""),
        section.get("aws_session_token", ""),
    )


class BedrockProvider:
    def complete(self, settings: ModelSettings, prompt: str) -> str:
        access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        session_token = os.environ.get("AWS_SESSION_TOKEN", "")
        if settings.aws_profile:
            access_key, secret_key, session_token = _aws_profile_credentials(settings.aws_profile)
        if not access_key or not secret_key or not settings.model:
            raise RuntimeError(
                "AWS Bedrock requires a valid AWS CLI profile or available AWS credentials, and a model."
            )
        host = f"bedrock-runtime.{settings.region}.amazonaws.com"
        path = f"/model/{settings.model}/converse"
        payload = json.dumps({"messages": [{"role": "user", "content": [{"text": prompt}]}]})
        timestamp = datetime.now(UTC)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = timestamp.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        headers = {"content-type": "application/json", "host": host, "x-amz-date": amz_date}
        if session_token:
            headers["x-amz-security-token"] = session_token
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
        canonical_request = f"POST\n{path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        scope = f"{date_stamp}/{settings.region}/bedrock/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )

        def sign(key: bytes, value: str) -> bytes:
            return hmac.new(key, value.encode(), hashlib.sha256).digest()

        signing_key = sign(
            sign(sign(sign(("AWS4" + secret_key).encode(), date_stamp), settings.region), "bedrock"),
            "aws4_request",
        )
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
        )
        response = requests.post(f"https://{host}{path}", headers=headers, data=payload, timeout=180)
        response.raise_for_status()
        return response.json()["output"]["message"]["content"][0]["text"]
