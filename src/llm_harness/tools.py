"""Resolve an installed tool; no sibling checkout assumptions."""
import importlib.util
from pathlib import Path
TOOLS = frozenset({'workspace_read_mcp', 'workspace_coding_mcp', 'workspace_git_mcp', 'github_public_mcp',
                   'google_workspace_mcp', 'gateway_reset_mcp', 'host_control_mcp', 'rig_info_mcp'})
def script(name):
    if name not in TOOLS:
        raise ValueError('unsupported installed tool')
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        raise ValueError('tool is not installed')
    return Path(spec.origin)
