"""Direct provider capabilities supplied by the caller, never inferred from a rig."""
from urllib.parse import urlsplit
import re

SCHEMA = 'harness-direct-provider/1'

def validate_direct_provider(config, endpoint, route, model):
    if not isinstance(config, dict) or config.get('schema') != SCHEMA:
        raise ValueError('unsupported direct provider schema')
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('provider endpoint must be HTTP(S) without credentials, query or fragment')
    if config.get('route') != route or config.get('model') != model or not route or not model:
        raise ValueError('direct provider route/model identity mismatch')
    for key in ('context_length', 'output_limit'):
        if type(config.get(key)) is not int or config[key] <= 0:
            raise ValueError(f'{key} must be a positive integer')
    if config['output_limit'] > config['context_length']:
        raise ValueError('output limit exceeds context length')
    key = config.get('api_key_env', 'HARNESS_PROVIDER_API_KEY')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
        raise ValueError('api_key_env must name an environment variable')
    return dict(config, id=route, provider='direct')
