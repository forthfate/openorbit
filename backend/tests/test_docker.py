from app.docker import DockerStatus, preflight_docker


def test_docker_preflight_returns_a_safe_status():
    status = preflight_docker()
    assert isinstance(status, DockerStatus)
    assert isinstance(status.supported, bool)
    assert isinstance(status.available, bool)
    assert status.reason
