#!/usr/bin/env python3
"""Freeze/check model-facing schemas using discovery only; no tool execution."""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).parents[1]
SNAPSHOT=ROOT/'tools/mcp_schemas.json'


def collect():
    with tempfile.TemporaryDirectory(prefix='mcp-schemas-') as temp:
        commands={'rig_search':['mcp_servers/rig_search/mcp_server.py'],
          'local_agents':['tools/gateway_subagent_mcp.py','--cloud-parent','--receipt-dir',temp],
          'google_workspace':['tools/google_workspace_mcp.py'],
          'gateway_reset':['tools/gateway_reset_mcp.py','--conversation-id','fixture'],
          'rig_info':['tools/rig_info_mcp.py'],'workspace_read':['tools/workspace_read_mcp.py','--root',temp],
          'workspace_git':['tools/workspace_git_mcp.py','--root',temp],'github_public':['tools/github_public_mcp.py'],
          'local_control':['tools/host_control_mcp.py','--scope','local'],
          'private_control':['tools/host_control_mcp.py','--scope','full']}
        schemas={}
        for name,args in commands.items():
            result=subprocess.run([sys.executable,*args],input=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n',
                                  cwd=ROOT,capture_output=True,text=True,timeout=15,check=True)
            tools=json.loads(result.stdout)['result']['tools']
            schemas[name]={row['name']:row['inputSchema'] for row in tools}
        return {'schema':'harness-mcp-schemas/1','servers':schemas}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['check','sync']);args=parser.parse_args()
    actual=collect()
    if args.mode=='sync':SNAPSHOT.write_text(json.dumps(actual,indent=2,sort_keys=True)+'\n')
    elif json.loads(SNAPSHOT.read_text())!=actual:raise SystemExit('MCP schema snapshot is stale; review and sync before publishing')
    print('current')

if __name__=='__main__':main()
