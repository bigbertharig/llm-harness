#!/usr/bin/env python3
"""Standalone wheel acceptance: external workspace, fresh HOME, fake provider and installed MCP."""
import argparse,json,os,subprocess,tempfile,threading,sys,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--wheel',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='harness-isolated-') as temp:
        root=Path(temp);env=dict(os.environ,HOME=str(root/'home'));env.pop('PYTHONPATH',None)
        (root/'home').mkdir();workspace=root/'external-project';workspace.mkdir();(workspace/'example.txt').write_text('independent project')
        venv=root/'venv';subprocess.run([sys.executable,'-m','venv',str(venv)],check=True,capture_output=True)
        python=venv/'bin/python'
        result=subprocess.run([str(python),'-m','pip','install',str(a.wheel.resolve())],capture_output=True,text=True,env=env)
        if result.returncode: raise RuntimeError(result.stderr[-2000:])
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(self.path)
                if len(calls)==1:
                    name=next(t['function']['name'] for t in body['tools'] if t['function']['name'].endswith('list_workspace_files'))
                    message={'role':'assistant','content':'','tool_calls':[{'id':'call1','type':'function','function':{'name':name,'arguments':'{}'}}]};reason='tool_calls'
                else: message={'role':'assistant','content':'Read the independent project.'};reason='stop'
                data={'id':'fake-provider','model':'custom','choices':[{'message':message,'finish_reason':reason}]}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        config=root/'provider.json';config.write_text(json.dumps({'schema':'harness-direct-provider/1','route':'custom','model':'custom','context_length':8192,'output_limit':512}))
        try:
            cmd=[str(venv/'bin/harness-run'),'--gateway',f'http://127.0.0.1:{server.server_port}','--provider-config',str(config),'--route','custom','--model','custom','--agent-type','coding','--tool-profile','workspace_read','--workspace-root',str(workspace),'--out',str(root/'receipt.json'),'Read the project']
            run=subprocess.run(cmd,cwd=workspace,env=env,capture_output=True,text=True,timeout=60)
            if run.returncode:raise RuntimeError((run.stdout+run.stderr)[-2500:])
        finally:server.shutdown();server.server_close();thread.join()
        result=json.loads((root/'receipt.json').read_text())
        assert result['tool_calls']==1 and result['run']['phase']=='succeeded',result
        assert all(path=='/v1/chat/completions' for path in calls)
        packets=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        mcp=subprocess.run([str(venv/'bin/harness-workspace-read'),'--root',str(workspace)],input=''.join(json.dumps(x)+'\n' for x in packets),cwd=workspace,env=env,capture_output=True,text=True,timeout=10)
        assert mcp.returncode==0,mcp.stderr
        replies=[json.loads(line) for line in mcp.stdout.splitlines()]
        assert replies[1]['result']['tools']
        receipt={'status':'passed','wheel':a.wheel.name,'fresh_home':True,'external_workspace':True,'provider_requests':calls,'tool_calls':result['tool_calls'],'mcp_discovery':True,'duration_seconds':time.monotonic()-started}
        a.receipt.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':main()
