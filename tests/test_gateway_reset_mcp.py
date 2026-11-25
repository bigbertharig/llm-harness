import argparse
import importlib.util
import io
import json
from pathlib import Path
import pytest
SPEC = importlib.util.spec_from_file_location('gateway_reset_mcp', Path(__file__).parents[1] / 'tools/gateway_reset_mcp.py')
reset = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(reset)


def test_reset_uses_authenticated_owner_api(monkeypatch):
    monkeypatch.setenv('LLM_GATEWAY_API_KEY', 'fixture-key')
    calls = []
    def send(request, **kwargs):
        calls.append(request)
        return io.BytesIO(json.dumps({'schema': 'gateway-reset/1', 'scheduled': True}).encode())
    monkeypatch.setattr(reset, 'urlopen', send)
    args = argparse.Namespace(gateway='http://localhost:8080', conversation_id='abc123')
    assert reset.schedule(args, {'confirmation': 'restart pi-gateway', 'recovery_note': 'continue', 'request_id': 'request1'})['scheduled']
    request = calls[0]
    assert request.full_url == 'http://localhost:8080/v1/operations/restart'
    assert request.get_header('Authorization') == 'Bearer fixture-key'
    assert json.loads(request.data)['request_id'] == 'request1'
    assert 'sqlite3' not in Path(reset.__file__).read_text()
    assert 'subprocess' not in Path(reset.__file__).read_text()


def test_reset_requires_authority(monkeypatch):
    monkeypatch.delenv('LLM_GATEWAY_API_KEY', raising=False)
    with pytest.raises(ValueError, match='API_KEY'):
        reset.schedule(argparse.Namespace(), {'confirmation': 'restart pi-gateway'})
    with pytest.raises(ValueError, match='confirmation'):
        reset.schedule(argparse.Namespace(), {'confirmation': 'yes'})
