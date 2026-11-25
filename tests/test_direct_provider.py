import json
import sys
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from project_agent import run_agent
from harness_core.providers import validate_direct_provider

CONFIG = {'schema': 'harness-direct-provider/1', 'route': 'local-model', 'model': 'my-model',
          'context_length': 4096, 'output_limit': 128}


def test_direct_provider_real_http_no_roster_or_ready_header(tmp_path, monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, dict(self.headers), body))
            result = {'id': 'fake-1', 'model': 'my-model', 'choices': [{'message': {'content': 'done'}, 'finish_reason': 'stop'}]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        receipt = run_agent(gateway=f'http://127.0.0.1:{server.server_port}', route='local-model',
                            expected_model='my-model', prompt='finish', agent_type='coding',
                            provider=CONFIG, journal_root=tmp_path)
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert receipt['error'] is None
    assert receipt['provider_mode'] == 'direct'
    assert receipt['limits']['effective_output_tokens'] == 128
    assert receipt['run']['durable']
    assert [r[0] for r in requests] == ['/v1/chat/completions']
    assert not any(k.lower() == 'x-require-ready' for k in requests[0][1])
    assert 'temperature' not in requests[0][2]


@pytest.mark.parametrize('change', [{'schema': 'future'}, {'route': 'other'}, {'output_limit': 0}, {'context_length': True}, {'api_key_env': 'bad-key'}])
def test_invalid_direct_capabilities_refused(change):
    with pytest.raises(ValueError):
        validate_direct_provider({**CONFIG, **change}, 'http://localhost', 'local-model', 'my-model')


def test_direct_cancel_before_provider(tmp_path):
    cancel = tmp_path / 'cancel'; cancel.touch()
    def forbidden(*args): raise AssertionError('cancelled run called provider')
    receipt = run_agent(gateway='http://localhost', route='local-model', expected_model='my-model',
                        prompt='finish', agent_type='coding', provider=CONFIG, cancel_path=cancel, complete=forbidden)
    assert receipt['error'] == 'cancelled'
    assert receipt['run']['phase'] == 'cancelled'
