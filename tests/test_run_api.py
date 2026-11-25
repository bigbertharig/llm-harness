import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
from harness_core.run_api import RunAPI, SCHEMA
from harness_core.recorder import RunRecorder


def test_idempotent_submit_input_cancel_and_restart(tmp_path):
    calls=[]
    api=RunAPI(tmp_path,lambda **kw:calls.append(kw),{})
    task={'schema':SCHEMA,'request_id':'task1','prompt':'work'}
    run=api.submit(task)['run_id']
    assert api.submit(task)['run_id']==run
    with pytest.raises(ValueError,match='reused'):
        api.submit(dict(task,prompt='different'))
    packet={'schema':SCHEMA,'request_id':'input1','mode':'steer','content':'new fact'}
    assert api.input(run,packet)['pending_inputs']==['input1']
    assert api.input(run,packet)['pending_inputs']==['input1']
    assert api.cancel(run)['state']=='cancelled'
    api.execute(run)
    assert not calls
    assert RunAPI(tmp_path,lambda **kw:None,{}).status(run)['state']=='cancelled'


def test_resume_never_replays_uncertain_dispatch(tmp_path):
    api=RunAPI(tmp_path,lambda **kw:None,{})
    run=api.submit({'schema':SCHEMA,'request_id':'a','prompt':'write'})['run_id']
    with api.connect() as db:
        db.execute("UPDATE runs SET state='running' WHERE id=?",(run,))
    resumed=RunAPI(tmp_path,lambda **kw:pytest.fail('replayed write'),{})
    assert resumed.status(run)['state']=='reconciliation_required'
    with pytest.raises(ValueError,match='reconciliation'): resumed.resume(run)


def test_execution_stable_ids_events_and_bounded_grants(tmp_path):
    def engine(**kwargs):
        recorder=RunRecorder(kwargs['journal_root'],kwargs['run_id'])
        recorder.emit('run.started')
        assert kwargs['input_source']('model_end')[0]['content']=='correction'
        recorder.emit('model.started', model_step_id='m')
        recorder.emit('model.completed', model_step_id='m', payload={'finish_reason':'stop'})
        recorder.emit('run.succeeded', payload={'reason':'completed'})
        return {'run':recorder.receipt(),'error':None,'answer':'done'}
    api=RunAPI(tmp_path,engine,{})
    with pytest.raises(ValueError,match='grant'):
        api.submit({'schema':SCHEMA,'request_id':'bad','prompt':'x','tool_profile':'workspace_git'})
    run=api.submit({'schema':SCHEMA,'request_id':'good','prompt':'x'})['run_id']
    api.input(run,{'schema':SCHEMA,'request_id':'steer','mode':'steer','content':'correction'})
    api.execute(run)
    assert api.status(run)['state']=='succeeded'
    assert api.status(run)['receipt']['run']['run_id']==run
    assert [e['sequence'] for e in api.events(run)['events']]==[0,1,2,3]
    assert api.events(run,0)['events'][0]['sequence']==1
    with pytest.raises(ValueError,match='cursor'): api.events(run,4)
    assert RunAPI(tmp_path,engine,{}).status(run)['state']=='succeeded'
