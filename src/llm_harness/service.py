"""Authenticated optional HTTP transport for the Harness-owned run contract."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from harness_core.run_api import RunAPI, SCHEMA
from project_agent import run_agent


def handler(api, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self): self.dispatch()
        def do_POST(self): self.dispatch()
        def dispatch(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self.reply(401, {'schema': SCHEMA, 'error': 'unauthorized'})
            path = urlsplit(self.path)
            parts = path.path.strip('/').split('/')
            try:
                body = {}
                if self.command == 'POST':
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0 < size <= 200000:
                        raise ValueError('request must be 1..200000 bytes')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict) or body.get('schema') != SCHEMA:
                        raise ValueError('unsupported request schema')
                if parts == ['v1','capabilities'] and self.command == 'GET':
                    result = {'schema': SCHEMA, 'operations': ['submit','status','events','input','cancel','resume'],
                              'restart_policy': 'reconciliation_required_for_interrupted_dispatch'}
                elif parts == ['v1','runs'] and self.command == 'POST':
                    result = api.submit(body)
                    result = api.resume(result['run_id'])
                elif len(parts) in (3,4) and parts[:2] == ['v1','runs']:
                    run_id = parts[2]
                    action = parts[3] if len(parts) == 4 else 'status'
                    if action == 'status' and self.command == 'GET': result = api.status(run_id)
                    elif action == 'events' and self.command == 'GET': result = api.events(run_id, int(parse_qs(path.query).get('after', ['-1'])[0]))
                    elif action == 'input' and self.command == 'POST': result = api.input(run_id, body)
                    elif action == 'cancel' and self.command == 'POST': result = api.cancel(run_id)
                    elif action == 'resume' and self.command == 'POST': result = api.resume(run_id)
                    else: raise ValueError('unsupported operation')
                else:
                    return self.reply(404, {'schema': SCHEMA, 'error': 'not_found'})
                self.reply(200, result)
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(409, {'schema': SCHEMA, 'error': 'refused', 'message': str(exc)})
        def reply(self, status, result):
            payload = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
    return Handler


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8091)
    args = parser.parse_args()
    token = os.environ.get('HARNESS_SERVICE_TOKEN')
    if not token:
        parser.error('HARNESS_SERVICE_TOKEN is required')
    config = json.loads(args.config.read_text())
    if config.get('workspace_root'):
        config['workspace_root'] = Path(config['workspace_root']).resolve(strict=True)
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state / 'service.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        api = RunAPI(args.state, run_agent, config)
        ThreadingHTTPServer((args.bind,args.port),handler(api,token)).serve_forever()

if __name__ == '__main__': main()
