import os
import sys
from types import SimpleNamespace

from orbit.cli import main, parser


def test_cli_exposes_control_room_commands():
    args = parser().parse_args(["runs", "start", "insighta-user-simulation"])
    assert args.command == "runs"
    assert args.workflow_id == "insighta-user-simulation"


def test_cli_exposes_local_web_server_command():
    args = parser().parse_args(["run", "--host", "0.0.0.0", "--port", "8787", "--reload"])
    assert args.command == "run"
    assert args.host == "0.0.0.0"
    assert args.port == 8787
    assert args.reload is True


def test_cli_accepts_an_optional_data_directory_for_the_local_web_server():
    args = parser().parse_args(["run", "."])
    assert args.path == "."


def test_cli_run_path_overrides_app_data_for_the_server(monkeypatch, tmp_path):
    received = {}

    def run(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs

    monkeypatch.setattr(sys, "argv", ["orbit", "run", str(tmp_path)])
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    monkeypatch.setenv("ORBIT_APP_DATA", "/previous-location")

    main()

    assert received == {
        "args": ("app.main:app",),
        "kwargs": {"host": "127.0.0.1", "port": 3000, "reload": False},
    }
    assert os.environ["ORBIT_APP_DATA"] == str(tmp_path / ".orbit")


def test_cli_exposes_task_test_with_waiting():
    args = parser().parse_args(["tasks", "test", "insighta-user-simulation", "--wait", "--timeout", "42"])
    assert args.command == "tasks"
    assert args.task_command == "test"
    assert args.task_id == "insighta-user-simulation"
    assert args.wait is True
    assert args.timeout == 42


def test_cli_accepts_provider_settings():
    args = parser().parse_args(["settings", "set", "--provider", "aws-bedrock", "--region", "ap-northeast-1"])
    assert args.provider == "aws-bedrock"
    assert args.region == "ap-northeast-1"
