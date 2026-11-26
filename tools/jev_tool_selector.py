"""Optional Jev choice over tools already allowed by a Harness profile."""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'

def select(messages: list[dict], server: dict, timeout: float) -> dict:
    """Return a Choice response; the agent loop validates it before use."""
    key = os.environ.get('TYPESAFE_API_KEY')
    if not key:
        raise ValueError('TYPESAFE_API_KEY is required for Jev tool selection')
    definitions = {row['name']: row for row in server['definitions']}
    criteria = {name: definitions[name].get('description') or name
                for name in server['tools']}
    criteria['model_decides'] = 'The main model should decide whether to use a tool or answer directly.'
    body = {'model': 'jev-latest',
            'state': {'conversation': messages[-8:]},
            'questions': {'next_tool': {
                'type': 'choice',
                'instructions': 'Which allowed tool should be used next? Choose model_decides if the answer is uncertain, more reasoning is needed, or no tool is needed.',
                'criteria': criteria}}}
    request = Request(ENDPOINT, data=json.dumps(body).encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + key,
                               'Content-Type': 'application/json'})
    with urlopen(request, timeout=max(1, min(timeout, 10))) as response:
        packet = json.load(response)
    return {'answer': packet['answers']['next_tool'],
            'model': packet.get('model'), 'usage': packet.get('usage', {})}
