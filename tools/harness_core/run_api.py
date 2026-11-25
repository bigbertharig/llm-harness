"""Durable run-control contract independent of any Gateway or provider account store."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
from uuid import uuid4

SCHEMA = 'harness-control/1'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,96}', value):
        raise ValueError('invalid identifier')
    return value


class RunAPI:
    def __init__(self, root, engine, configuration):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.engine = engine
        self.configuration = configuration
        self.workers = {}
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, digest TEXT, task TEXT, state TEXT, receipt TEXT);
              CREATE TABLE IF NOT EXISTS inputs (id TEXT PRIMARY KEY, run TEXT, mode TEXT, content TEXT, applied INTEGER DEFAULT 0);
            """)
            # Restart cannot prove whether the previous worker dispatched a write.
            db.execute("UPDATE runs SET state='reconciliation_required' WHERE state='running'")

    def connect(self):
        return sqlite3.connect(self.root / 'runs.sqlite3', timeout=10)

    def submit(self, task):
        if not isinstance(task, dict) or task.get('schema') != SCHEMA:
            raise ValueError('unsupported run schema')
        request_id = identifier(task.get('request_id'))
        if set(task) - {'schema', 'request_id', 'prompt', 'agent_type', 'tool_profile', 'max_tokens', 'timeout_s', 'max_tool_calls'}:
            raise ValueError('unsupported task fields; provider, workspace and tools are service configuration')
        prompt = task.get('prompt')
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 100000:
            raise ValueError('prompt must be 1..100000 characters')
        if task.get('tool_profile', 'none') not in self.configuration.get('allowed_profiles', ['none']):
            raise ValueError('tool grant exceeds service authority')
        if task.get('agent_type', 'coding') not in ('coding', 'research'):
            raise ValueError('invalid agent type')
        for key, maximum, default in [('max_tokens',4096,1024),('timeout_s',600,180),('max_tool_calls',12,12)]:
            value = task.get(key, default)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('invalid ' + key)
        digest = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,digest FROM runs WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior[1] != digest:
                    raise ValueError('request_id reused for different arguments')
                run_id = prior[0]
            else:
                run_id = uuid4().hex
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,NULL)', (run_id, request_id, digest, json.dumps(task), 'queued'))
        return self.status(run_id)

    def status(self, run_id):
        identifier(run_id)
        with self.connect() as db:
            row = db.execute('SELECT state,receipt FROM runs WHERE id=?', (run_id,)).fetchone()
            pending = db.execute('SELECT id FROM inputs WHERE run=? AND applied=0 ORDER BY rowid', (run_id,)).fetchall()
        if row is None:
            raise ValueError('unknown run')
        return {'schema': SCHEMA, 'run_id': run_id, 'state': row[0],
                'receipt': json.loads(row[1]) if row[1] else None, 'pending_inputs': [x[0] for x in pending]}

    def input(self, run_id, packet):
        if packet.get('schema') != SCHEMA or packet.get('mode') not in ('queue', 'steer'):
            raise ValueError('unsupported input schema or mode')
        ident = identifier(packet.get('request_id'))
        content = packet.get('content')
        if not isinstance(content, str) or not 1 <= len(content) <= 100000:
            raise ValueError('invalid input content')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT run,mode,content FROM inputs WHERE id=?', (ident,)).fetchone()
            if row:
                if row != (run_id, packet['mode'], content):
                    raise ValueError('input request_id collision')
            else:
                state = db.execute('SELECT state FROM runs WHERE id=?', (run_id,)).fetchone()
                if state is None or state[0] not in ('queued','running'):
                    raise ValueError('run does not accept input')
                db.execute('INSERT INTO inputs(id,run,mode,content) VALUES (?,?,?,?)', (ident,run_id,packet['mode'],content))
        return self.status(run_id)

    def cancel(self, run_id):
        self.status(run_id)
        (self.root / (identifier(run_id) + '.cancel')).touch()
        with self.connect() as db:
            db.execute("UPDATE runs SET state='cancelled' WHERE id=? AND state='queued'", (run_id,))
        return self.status(run_id)

    def events(self, run_id, after=-1):
        self.status(run_id)
        if type(after) is not int or after < -1:
            raise ValueError('invalid event cursor')
        from .recorder import RunRecorder
        journal = self.root / 'journals'
        from .journal import EventJournal
        probe = EventJournal(journal, run_id)
        events, state = probe.read() if probe.path.exists() else ([], None)
        if after >= len(events):
            raise ValueError('event cursor exceeds durable sequence')
        return {'schema': SCHEMA, 'run_id': run_id, 'events': events[after+1:], 'next_sequence': len(events)}

    def resume(self, run_id):
        with self.lock:
            state = self.status(run_id)['state']
            if state == 'reconciliation_required':
                raise ValueError('interrupted dispatch requires reconciliation; automatic replay refused')
            if state != 'queued':
                return self.status(run_id)
            thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True)
            if run_id not in self.workers:
                self.workers[run_id] = thread
                thread.start()
        return self.status(run_id)

    def execute(self, run_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task,state FROM runs WHERE id=?', (run_id,)).fetchone()
            if not row or row[1] != 'queued': return
            db.execute("UPDATE runs SET state='running' WHERE id=?", (run_id,))
        task = json.loads(row[0])
        def inputs(boundary):
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute("SELECT id,mode,content FROM inputs WHERE run=? AND applied=0 AND (mode='steer' OR ?='turn_end') ORDER BY rowid", (run_id,boundary)).fetchall()
                for item in rows:
                    db.execute('UPDATE inputs SET applied=1 WHERE id=?', (item[0],))
            return [dict(zip(('id','mode','content'), row)) for row in rows]
        try:
            settings = {k:v for k,v in self.configuration.items() if k not in ('allowed_profiles','tool_servers')}
            profile = task.get('tool_profile','none')
            settings['agent_type'] = task.get('agent_type', 'coding')
            settings['tool_server'] = self.configuration.get('tool_servers', {}).get(profile)
            receipt = self.engine(**settings, **{k:v for k,v in task.items() if k not in ('schema','request_id','agent_type')},
                                  run_id=run_id, journal_root=self.root/'journals',
                                  cancel_path=self.root/(run_id+'.cancel'), input_source=inputs)
            state = receipt['run']['phase']
        except Exception as exc:
            receipt = {'error': type(exc).__name__, 'message': str(exc)}
            state = 'failed'
            try:
                from .recorder import RunRecorder
                journal = RunRecorder.resume(self.root / 'journals', run_id)
                if any(tool.state in ('executing', 'uncertain') for tool in journal.state.tools):
                    state = 'reconciliation_required'
                receipt['run'] = journal.receipt()
            except Exception:
                pass
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?,receipt=? WHERE id=?', (state,json.dumps(receipt),run_id))
