import pytest
from app.remote import RemoteInvocation


def test_remote_invocation_rejects_embedded_credentials():
    with pytest.raises(ValueError, match="without embedded credentials"):
        RemoteInvocation(endpoint="https://secret@example.com/invoke").validate()


def test_remote_invocation_accepts_https_contract():
    RemoteInvocation(endpoint="https://agent.example.com/invoke", payload={"task": "evaluate"}).validate()


def test_remote_invocation_accepts_custom_headers():
    RemoteInvocation(
        endpoint="https://agent.example.com/invoke",
        headers={"X-Evaluation-Source": "orbit", "Authorization": "Bearer test"},
    ).validate()
