#!/usr/bin/env python3
"""Run a bounded command in its own Git worktree while holding a fleet lease."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
try:
    from .cac_coordination import CoordinationStore
    from .cac_fleet import atomic,git,safe_path,FleetError
except ModuleNotFoundError:
    from .cac_coordination import CoordinationStore
    from .cac_fleet import atomic,git,safe_path,FleetError

def stop_group(process,sig):
    with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,sig)

def run_work(state,project,scope,task,agent,command):
    state=safe_path(state);project=safe_path(project)
    if not command:raise FleetError('a command is required')
    enrollment=json.loads((state/'enrollment.json').read_text());host=enrollment['host_id']
    if not task or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in task):raise FleetError('invalid task id')
    remote=git('remote','get-url','origin',cwd=project)
    revision=git('rev-parse','HEAD',cwd=project)
    key=hashlib.sha256(remote.encode()).hexdigest()[:20]+':'+scope
    branch='cac/'+host+'/'+task;git('check-ref-format','--branch',branch)
    worktree=safe_path(state/'worktrees'/task)
    if worktree.exists():raise FleetError('task worktree already exists; resume explicitly rather than overwrite')
    store=CoordinationStore(enrollment['remote'],state/'coordination')
    claim=store.claim(key,host_id=host,task_id=task,agent_id=agent,project=hashlib.sha256(remote.encode()).hexdigest(),worktree=str(worktree),branch=branch,source_revision=revision,duration_seconds=180)
    token=claim['lease_token'];process=None;record=state/'work'/ (task+'.json')
    identity={'resource':key,'host_id':host,'task_id':task,'agent_id':agent,'branch':branch,'worktree':str(worktree),'source_revision':revision}
    # Keep the token in memory only. The durable record is safe to publish or inspect.
    try:
        atomic(record,{**identity,'status':'running'})
        git('worktree','add','-b',branch,worktree,revision,cwd=project)
        process=subprocess.Popen(command,cwd=worktree,start_new_session=True)
        renewed=time.monotonic()
        while process.poll() is None:
            if time.monotonic()-renewed>=45:
                try:
                    renewal=store.renew(key,token,duration_seconds=180)
                    if renewal.get('resource')!=key:raise FleetError('lease renewal identity mismatch')
                except Exception:
                    stop_group(process,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:stop_group(process,signal.SIGKILL);process.wait()
                    raise FleetError('work stopped after lease renewal failed')
                renewed=time.monotonic()
            time.sleep(0.2)
        result={**identity,'status':'completed' if process.returncode==0 else 'failed','exit_code':process.returncode}
        atomic(record,result);return result
    except Exception:
        # Leave the worktree available for inspection/resume and always replace any
        # running record with a token-free failure record.
        failure={**identity,'status':'failed','error':'work command or lease operation failed'}
        if process is not None and process.returncode is not None: failure['exit_code']=process.returncode
        try: atomic(record,failure)
        except Exception: pass
        raise
    finally:
        if process and process.poll() is None:
            stop_group(process,signal.SIGTERM)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:stop_group(process,signal.SIGKILL);process.wait()
        try:store.release(key,token)
        except Exception:pass # lease expiry remains visible if transport is unavailable

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,default=Path.home()/'.local/state/cac-fleet');p.add_argument('--project',type=Path,required=True);p.add_argument('--scope',required=True);p.add_argument('--task',required=True);p.add_argument('--agent',required=True);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args(argv)
    cmd=a.command[1:] if a.command[:1]==['--'] else a.command
    try:
        result=run_work(a.state,a.project,a.scope,a.task,a.agent,cmd)
        print(json.dumps(result,indent=2))
        if result.get('status')!='completed': raise SystemExit(1)
    except Exception:print(json.dumps({'status':'failed','message':'inspect the local task record and fleet lease status'}));raise SystemExit(1)
if __name__=='__main__':main()
