from orbit.cli import parser


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
