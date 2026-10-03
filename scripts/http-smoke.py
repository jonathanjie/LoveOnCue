#!/usr/bin/env python3
"""Exercise real loopback HTTP against an isolated, owned fictional demo process."""
import json,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='weddingops-http-') as directory:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    # Do not inherit real integration credentials into a rehearsal.
    env={k:v for k,v in os.environ.items() if not k.startswith('WEDDINGOPS_')}
    env.update(PYTHONPATH=str(root/'src'),WEDDINGOPS_MODE='demo',
               WEDDINGOPS_DATABASE_URL='sqlite:///'+directory+'/demo.db',WEDDINGOPS_PUBLIC_URL=url,
               WEDDINGOPS_SEND_NOTIFICATIONS='false',WEDDINGOPS_AGENT_MODE='deterministic')
    with open(Path(directory)/'server.log','w+') as log:
        child=subprocess.Popen([sys.executable,'-m','wedding_ops.cli','demo','--port',str(port)],
                               cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=url,timeout=5,headers={'Origin':url,'X-WeddingOps-Client':'1'}) as client:
                for _ in range(100):
                    try:
                        if client.get('/health').status_code==200:break
                    except httpx.HTTPError:pass
                    if child.poll() is not None:raise RuntimeError('Owned rehearsal process exited')
                    time.sleep(.1)
                else:raise RuntimeError('Owned rehearsal process did not start')
                assert client.get('/ready').status_code==200
                assert client.get('/api/config').json()['demo'] is True
                assert client.get('/api/snapshot').status_code==401
                def login(member):
                    result=client.post('/api/auth/demo',json={'member_id':member});result.raise_for_status()
                    client.headers['X-CSRF-Token']=result.json()['csrf']
                    assert 'HttpOnly' in result.headers['set-cookie']
                login('registration-a')
                assert client.get('/api/guests?q=Sarah').json()['items'][0]['table']=='18'
                login('banquet')
                result=client.post('/api/chat',json={'text':'Dinner needs another 12 minutes'});result.raise_for_status()
                result=client.post('/api/confirm',json={'draft_id':result.json()['draft']['id']});result.raise_for_status()
                proposal_id=result.json()['id']
                assert client.get('/api/snapshot').json()['wedding']['timeline_version']==1
                command={'command':{'type':'decide_approval','approval_id':proposal_id,'decision':'approve'},'request_id':'http-smoke-approved-change'}
                assert client.post('/api/commands',json=command).status_code==403
                login('coordinator')
                result=client.post('/api/commands',json=command);result.raise_for_status()
                assert result.json()['timeline_version']==2
                result=client.post('/api/commands',json=command);result.raise_for_status()
                assert result.json()['replayed'] is True
                assert client.get('/api/snapshot').json()['counts']['guests']==180
                assert client.get('/api/snapshot',headers={'Host':'untrusted.example'}).status_code==400
                report={'transport':'real loopback HTTP, Python client, isolated Uvicorn process',
                    'checks':['readiness','unauthenticated denial','cookie session','role seating lookup',
                              'delay draft confirmation','non-coordinator approval denial','coordinator approval',
                              'idempotent replay','trusted-host rejection'],
                    'external_messages_sent':0,'browser_tls_telegram_verified':False,'passed':True}
                out=root/'artifacts';out.mkdir(exist_ok=True)
                (out/'http-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        finally:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
