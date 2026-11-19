import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "host_control_mcp.py"
spec = importlib.util.spec_from_file_location("host_control_mcp", SCRIPT)
host_control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_control)


def test_configured_targets_and_network(tmp_path):
    config_file = tmp_path / "hosts.json"
    config_file.write_text(json.dumps({
        "local_targets": {"pi": None, "rig": "192.168.40.3"},
        "private_cidr": "192.168.40.0/24", "ssh_user": "operator"}))
    config = host_control.load_config(config_file)
    with patch.object(host_control.subprocess, "run") as proc:
        proc.return_value.returncode = 0
        proc.return_value.stdout = "ok"
        proc.return_value.stderr = ""
        assert host_control.run("run_local_command", {
            "target": "rig", "command": "true"}, "local", config)["exit_code"] == 0
        assert "operator@192.168.40.3" in proc.call_args.args[0]
        host_control.run("run_private_command", {
            "host": "192.168.40.9", "command": "true"}, "full", config)
        assert "operator@192.168.40.9" in proc.call_args.args[0]
    try:
        host_control.run("run_private_command", {
            "host": "192.168.41.9", "command": "true"}, "full", config)
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-scope private host accepted")


def test_missing_or_invalid_config_fails_closed(tmp_path):
    missing = tmp_path / "missing.json"
    try:
        host_control.load_config(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing config accepted")
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"local_targets": {"pi": None},
        "private_cidr": "0.0.0.0/0", "ssh_user": "operator"}))
    try:
        host_control.load_config(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("public network accepted")
