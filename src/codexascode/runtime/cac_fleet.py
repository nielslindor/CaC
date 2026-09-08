#!/usr/bin/env python3
"""Pull-based native Codex deployments. No model calls in reconciliation."""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import secrets

class FleetError(ValueError): pass

def digest(data): return hashlib.sha256(data).hexdigest()
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def codex_version(): return subprocess.check_output(['codex','--version'],text=True,timeout=15).strip()
def safe_path(path):
    p=Path(path).absolute()
    if any(ord(c)<32 for c in str(p)):raise FleetError("control character in managed path")
    if ".." in p.parts:raise FleetError("parent traversal in managed path")
    for a in [p,*p.parents]:
        if a.is_symlink(): raise FleetError('symlink in managed path')
    return p

def atomic(path, value):
    path=safe_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.cac-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f: json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def git(*args,cwd=None):
    p=subprocess.run(['git',*map(str,args)],cwd=cwd,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'},capture_output=True,timeout=90)
    if p.returncode:raise FleetError('Git operation failed; verify transport, revision and repository access')
    return p.stdout.decode().strip()

@contextlib.contextmanager
def lock(state):
    state=safe_path(state);state.mkdir(parents=True,exist_ok=True);state.chmod(0o700)
    p=safe_path(state/'reconcile.lock')
    with p.open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise FleetError('another reconciliation owns this host')
        yield

def validate_enrollment(e,allow_local_remote=False):
    if e.get('schema_version')!=1:raise FleetError('unsupported enrollment')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,80}',e.get('host_id','')):raise FleetError('invalid host id')
    remote=e.get('remote','')
    if not (re.fullmatch(r'https://github.com/[\w.-]+/[\w.-]+(?:\.git)?',remote) or (allow_local_remote and Path(remote).is_absolute())):raise FleetError('remote must be an explicit GitHub repository without credentials')
    ref=e.get('branch','')
    if not ref or ref.startswith('-') or git('check-ref-format','--branch',ref)!=ref:raise FleetError('invalid branch')
    if not Path(e.get('home','')).is_absolute():raise FleetError('host home must be absolute')
    safe_path(e['home'])
    roots=e.get('project_roots',[])
    if not isinstance(roots,list) or len(roots)>128:raise FleetError('invalid enrolled project roots')
    for root in roots:
        if not isinstance(root,str) or not Path(root).is_absolute():raise FleetError('project root must be absolute')
        safe_path(root)
    if e.get('activate_native') is not True:raise FleetError('native activation must be explicitly enrolled')
    return e

def enroll(state,remote,branch,host_id,home=None,test_remote=False,project_roots=None):
    state=safe_path(state);home=safe_path(home or Path.home())
    e=validate_enrollment({'schema_version':1,'remote':remote,'branch':branch,'host_id':host_id,'home':str(home),'activate_native':True,'project_roots':[str(safe_path(p)) for p in (project_roots or [])],'enrolled_at':stamp()},allow_local_remote=test_remote)
    state.mkdir(parents=True,exist_ok=True)
    if (state/'enrollment.json').exists():
        old=json.loads((state/'enrollment.json').read_text())
        if any(old[k]!=e[k] for k in ['remote','branch','host_id','home']):raise FleetError('already enrolled with different identity')
        if project_roots is not None:
            old['project_roots']=e['project_roots'];atomic(state/'enrollment.json',old)
        return old
    atomic(state/'enrollment.json',e);return e

def materialize(state,e):
    cache=safe_path(state/'source.git')
    if not cache.exists():git('init','--bare',cache);git('remote','add','origin',e['remote'],cwd=cache)
    if git('remote','get-url','origin',cwd=cache)!=e['remote']:raise FleetError('cache remote identity changed')
    git('fetch','--no-tags','origin','+refs/heads/'+e['branch']+':refs/remotes/origin/desired',cwd=cache)
    rev=git('rev-parse','refs/remotes/origin/desired^{commit}',cwd=cache)
    target=safe_path(state/'generations'/rev)
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True)
        git('clone','--shared','--no-checkout',cache,target)
        git('checkout','--detach',rev,cwd=target)
    if git('rev-parse','HEAD',cwd=target)!=rev or git('status','--porcelain','--untracked-files=normal',cwd=target):raise FleetError('deployment generation has local edits; refusing overwrite')
    return rev,target

def resources(root):
    """Only native shared artifacts committed by the owner are promoted."""
    result={}
    for rel in ['.agents/skills','.codex/agents','.codex/rules']:
        parent=root/rel
        if not parent.exists():continue
        safe_path(parent)
        for p in sorted(parent.rglob('*')):
            safe_path(p)
            if p.is_file():
                name=p.relative_to(parent).as_posix()
                if any(x.startswith('.env') or x in {'auth.json','credentials.json'} or x.endswith(('.pem','.key')) for x in p.parts):raise FleetError('secret-like artifact name in shared resources')
                data=p.read_bytes()
                if len(data)>1024*1024:raise FleetError('shared artifact too large')
                if rel=='.agents/skills':dest='.agents/skills/cac-'+name
                else:dest=rel+'/'+('cac-'+name)
                result[dest]=p
    return result

class Native:
    def __init__(self):
        from .native_workspace import Client
        self.client=Client()
    def __enter__(self):self.client.__enter__();return self
    def __exit__(self,*args):self.client.__exit__(*args)
    def activate(self,root):
        r=self.client.request('config/read',{'cwd':str(root),'includeLayers':True})
        user=next((x for x in r.get('layers',[]) if x.get('name',{}).get('type')=='user'),None)
        if user is None:raise FleetError('native user configuration version unavailable')
        # Project table replacement uses the versioned full existing projects map,
        # preserving unrelated projects without ambiguous dotted path parsing.
        projects={**r.get('config',{}).get('projects',{}),**user.get('config',{}).get('projects',{})}
        projects[str(root)]={**projects.get(str(root),{}),'trust_level':'trusted'}
        loose=root/'chats'/'loose';safe_path(loose);loose.mkdir(parents=True,exist_ok=True)
        edits=[{'keyPath':'projects','mergeStrategy':'replace','value':projects},{'keyPath':'desktop.projectlessWorkspaceRoot','mergeStrategy':'replace','value':str(loose)}]
        needed=[]
        if user.get('config',{}).get('projects',{}).get(str(root),{}).get('trust_level')!='trusted':needed.append(edits[0])
        if r.get('config',{}).get('desktop',{}).get('projectlessWorkspaceRoot')!=str(loose):needed.append(edits[1])
        if needed:self.client.request('config/batchWrite',{'edits':needed,'expectedVersion':user['version'],'reloadUserConfig':True})
        return self.verify(root)
    def verify(self,root):
        r=self.client.request('config/read',{'cwd':str(root),'includeLayers':True})
        layer=next((x for x in r.get('layers',[]) if x.get('name',{}).get('dotCodexFolder')==str(root/'.codex')),None)
        if layer is None or layer.get('disabledReason'):raise FleetError('native project configuration is not loaded')
        declared=tomllib.loads((root/'.codex/config.toml').read_text())
        if layer.get('config')!=declared:raise FleetError('native project layer differs from declared configuration')
        s=self.client.request('skills/list',{'cwds':[str(root)],'forceReload':True})
        available={x.get('name') for d in s.get('data',[]) for x in d.get('skills',[])}
        expected=[]
        for p in (root/'.agents/skills').glob('*/SKILL.md'):
            match=re.search(r'^name:\s*[\"\']?([^\n\"\']+)',p.read_text(),re.M)
            if match:expected.append(match.group(1).strip())
        if not set(expected)<=available:raise FleetError('native skills discovery incomplete')
        configured=r.get('config',{}).get('desktop',{}).get('projectlessWorkspaceRoot')
        if configured!=str(root/'chats/loose'):raise FleetError('native task root did not converge')
        return {'project_config_loaded':True,'skills_discovered':sorted(expected),'new_task_root':configured,'existing_sessions':'retain their session context; restart or begin a new task for instruction changes','fresh_task_probe':'not_run'}

def bridge_bytes(state,e,rev,root):
    return ('# CaC deployment context\n\nThis host is '+e['host_id']+'. Shared Codex desired state is revision '+rev+'.\nRead '+str(root/'AGENTS.md')+' for shared working instructions and '+str(root/'WORKBOARD.md')+' for project outcomes.\nUse '+str(state/'receipt.json')+' for observed deployment status; do not infer other hosts are current.\nHost-local native memory and chat history are not shared configuration. Label retrieved memories with host and source; never imply another host remembers them. Shared decisions must be explicitly committed or published through the configured coordination protocol.\nUse the indexed official docs before changing Codex behavior; retrieve bounded sections rather than whole pages.\nBefore concurrent project edits, claim the project/work scope with the CaC coordination tool and record host, agent, task, branch and worktree; renew the lease while working and release it on completion.\n').encode()

def plan_files(state,e,root,rev):
    home=Path(e['home']);owned_path=state/'ownership.json'
    owned=json.loads(owned_path.read_text()) if owned_path.exists() else {}
    desired={str(home/dest):p.read_bytes() for dest,p in resources(root).items()}
    bridge=home/'.codex/AGENTS.md'
    # Existing user instructions are preserved outside a bounded owned block.
    start=b'<!-- CaC managed start -->\n';end=b'<!-- CaC managed end -->\n'
    old=bridge.read_bytes() if bridge.exists() else b''
    if start in old:
        if old.count(start)!=1 or old.count(end)!=1:raise FleetError('ambiguous global instruction block')
        pre,rest=old.split(start,1);_,post=rest.split(end,1)
        block=start+bridge_bytes(state,e,rev,root)+end
        # Ownership checks below prevent silently losing edits inside this file.
        desired[str(bridge)]=pre+block+post
    else:
        if str(bridge) in owned:raise FleetError('managed instruction block removed locally')
        desired[str(bridge)]=old+(b'\n' if old and not old.endswith(b'\n') else b'')+start+bridge_bytes(state,e,rev,root)+end
    changes=[]
    for dest,data in desired.items():
        p=safe_path(dest);actual=digest(p.read_bytes()) if p.exists() else None
        expected=owned.get(dest)
        if expected and actual not in (expected,digest(data)):raise FleetError('managed resource drift; preserve local edit and publish it deliberately')
        if not expected and p.exists() and p!=bridge and actual!=digest(data):raise FleetError('unowned native resource collision')
        if actual!=digest(data):changes.append(dest)
    stale=set(owned)-set(desired)
    for dest in stale:
        p=safe_path(dest)
        if p.exists() and digest(p.read_bytes())!=owned[dest]:raise FleetError('retired managed resource has local edits')
    return desired,owned,changes,stale

def write_files(state,desired,owned,stale):
    # All conflicts were preflighted. Preserve previous bytes for explicit rollback.
    backup=safe_path(state/'rollback');backup.mkdir(exist_ok=True);backup.chmod(0o700)
    for dest,data in desired.items():
        p=safe_path(dest);p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists() and p.read_bytes()==data:continue
        if p.exists():
            b=safe_path(backup/digest(dest.encode()));b.write_bytes(p.read_bytes());b.chmod(0o600)
        fd,tmp=tempfile.mkstemp(prefix='.cac-',dir=p.parent)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,p)
    for dest in stale:
        p=safe_path(dest)
        if p.exists():p.unlink()
    atomic(state/'ownership.json',{k:digest(v) for k,v in desired.items()})


def validate_generation(root):
    # Use the installed, reviewed checker; never execute tests from a new revision.
    from codexascode.gauntlet import run_gauntlet
    for name in git('ls-files',cwd=root).splitlines():
        if any((part.startswith('.env') and part!='.env.example') or part in {'auth.json','credentials.json'} or part.endswith(('.pem','.key')) for part in Path(name).parts):
            raise FleetError('raw environment or credential artifact is tracked')
    from .cac_sdlc import check as check_sdlc
    check_sdlc(root)
    check=run_gauntlet(root,run_tests=False)
    if check['status']!='pass':raise FleetError('desired revision fails content/lifecycle checks')
    return check['source_tree_digest']

def refresh_context(state,root,version,policy):
    from .cac_context import refresh_docs
    receipt=state/'documentation.json'
    old=json.loads(receipt.read_text()) if receipt.exists() else {}
    hours=policy.get('documentation_refresh_hours',24)
    if not isinstance(hours,(int,float)) or hours<1:raise FleetError('invalid docs refresh interval')
    due=old.get('codex_version')!=version or time.time()-old.get('checked_epoch',0)>hours*3600
    if due:
        result=refresh_docs(state/'context',root/'environment/documentation-sources.json',codex_version=version)
        atomic(receipt,{'codex_version':version,'checked_epoch':time.time(),'result':result})
    return {'status':'indexed','codex_version':version,'refreshed':due}

def publish_observation(state,receipt,skills):
    from .cac_coordination import CoordinationStore
    e=json.loads((state/'enrollment.json').read_text())
    store=CoordinationStore(e['remote'],state/'coordination')
    previous_path=state/'published.json';previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
    normalized=[{'name':x['name'],'sha256':x['sha256']} for x in skills]
    summary={'revision':receipt.get('desired_revision') or 'unknown','status':receipt['status'],'codex_version':receipt.get('codex_version','unknown'),'effective':{'native':receipt.get('effective',False),'fresh_task':receipt.get('fresh_task_verified',False)}}
    fingerprint=digest(json.dumps([summary,normalized],sort_keys=True).encode())
    if previous.get('fingerprint')==fingerprint and time.time()-previous.get('epoch',0)<300:return
    store.put_receipt(e['host_id'],observed_at=receipt['observed_at'],**summary)
    store.put_discovery(e['host_id'],{x['name']:x['sha256'] for x in normalized})
    atomic(previous_path,{'fingerprint':fingerprint,'epoch':time.time()})

def fleet_status(state):
    from .cac_coordination import CoordinationStore
    e=json.loads((state/'enrollment.json').read_text());store=CoordinationStore(e['remote'],state/'coordination')
    receipts=store.get_receipts();now=dt.datetime.now(dt.timezone.utc)
    for r in receipts:
        observed=dt.datetime.fromisoformat(r['observed_at'].replace('Z','+00:00'))
        r['freshness']='stale' if (now-observed).total_seconds()>900 else 'recent'
    return {'hosts':receipts,'discoveries':store.list_discoveries(),'work':store.list_leases(),'coverage':'only enrolled reporting hosts; missing machines are not assumed converged'}

def install_service(state,interval=60):
    # Launch the explicitly installed distribution; source generations do not replace it.
    state=safe_path(state)
    if interval<10:raise FleetError('minimum interval is ten seconds')
    executable=Path(sys.executable).absolute()
    if sys.platform.startswith('linux'):
        units=safe_path(Path.home()/'.config/systemd/user');units.mkdir(parents=True,exist_ok=True)
        unit=safe_path(units/'cac-fleet.service')
        command=' '.join('"'+str(x).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"' for x in [executable,'-m','codexascode.runtime.cac_fleet','--state',state,'watch','--interval',interval])
        content='[Unit]\nDescription=CaC desired-state reconciler\nAfter=network-online.target\n\n[Service]\nType=simple\nExecStart='+command+'\nRestart=on-failure\nRestartSec=15\nUMask=0077\n\n[Install]\nWantedBy=default.target\n'
        if unit.exists() and not unit.read_text().startswith('[Unit]\nDescription=CaC desired-state reconciler'):raise FleetError('service unit collision')
        fd,tmp=tempfile.mkstemp(prefix='.cac-unit-',dir=units)
        with os.fdopen(fd,'w') as f:f.write(content)
        os.chmod(tmp,0o600);os.replace(tmp,unit)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=20)
        subprocess.run(['systemctl','--user','enable','--now','cac-fleet.service'],check=True,timeout=20)
        subprocess.run(['systemctl','--user','restart','cac-fleet.service'],check=True,timeout=20)
        return {'service':str(unit),'state':str(state),'scope':'user session','interval_seconds':interval}
    if sys.platform=='darwin':
        import plistlib
        dest=safe_path(Path.home()/'Library/LaunchAgents/dev.cac.fleet.plist');dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            old=plistlib.loads(dest.read_bytes());args=old.get('ProgramArguments',[])
            if old.get('Label')!='dev.cac.fleet' or 'codexascode.runtime.cac_fleet' not in args or str(state) not in args:raise FleetError('launch agent collision')
            target='gui/'+str(os.getuid())+'/dev.cac.fleet'
            observed=subprocess.run(['launchctl','print',target],capture_output=True,timeout=20)
            if observed.returncode==0:subprocess.run(['launchctl','bootout',target],check=True,timeout=20)
        data={'Label':'dev.cac.fleet','ProgramArguments':[str(executable),'-m','codexascode.runtime.cac_fleet','--state',str(state),'watch','--interval',str(interval)],'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15}
        fd,tmp=tempfile.mkstemp(prefix='.cac-agent-',dir=dest.parent)
        with os.fdopen(fd,'wb') as f:f.write(plistlib.dumps(data))
        os.chmod(tmp,0o600);os.replace(tmp,dest)
        subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(dest)],check=True,timeout=20)
        return {'service':str(dest),'state':str(state),'scope':'user session','interval_seconds':interval}
    raise FleetError('unsupported service platform')

def _plan_digest(plan):
    data=dict(plan);data.pop('plan_digest',None);return digest(json.dumps(data,sort_keys=True,separators=(',',':')).encode())

def deployment_plan(state,out=None,validate=validate_generation,allow_local_remote=False):
    state=safe_path(state)
    with lock(state):
        e=validate_enrollment(json.loads((state/'enrollment.json').read_text()),allow_local_remote=allow_local_remote)
        rev,root=materialize(state,e);validate(root)
        desired,owned,changes,stale=plan_files(state,e,root,rev)
        snapshot={p:(digest(safe_path(p).read_bytes()) if safe_path(p).exists() else None) for p in set(desired)|set(owned)}
        plan={'schema_version':1,'desired_revision':rev,'enrollment_digest':digest(json.dumps(e,sort_keys=True).encode()),'managed_snapshot':snapshot,'owned_snapshot':owned,'update_paths':changes,'remove_paths':sorted(stale),'native_activation_required':True,'native_changes':['trust this generation','point new projectless tasks at this generation'],'applied':False}
        atomic(state/'plan-seal.json',{'plan_digest':_plan_digest(plan)})
        plan['plan_digest']=_plan_digest(plan)
        if out: atomic(out,plan)
        return plan

def apply_plan(state,path,native_factory=Native,validate=validate_generation,refresh=refresh_context,allow_local_remote=False):
    state=safe_path(state);path=safe_path(path)
    if path.stat().st_size>1024*1024:raise FleetError('deployment plan exceeds limit')
    plan=json.loads(path.read_text())
    if not isinstance(plan,dict) or plan.get('schema_version')!=1 or plan.get('plan_digest')!=_plan_digest(plan):raise FleetError('invalid or tampered deployment plan')
    def preflight(e,rev,root,desired,owned):
        seal=safe_path(state/'plan-seal.json')
        if not seal.exists() or json.loads(seal.read_text()).get('plan_digest')!=plan['plan_digest']:raise FleetError('deployment plan seal is unavailable')
        if digest(json.dumps(e,sort_keys=True).encode())!=plan.get('enrollment_digest'):raise FleetError('enrollment changed since plan')
        if rev!=plan.get('desired_revision'):raise FleetError('source revision changed since plan')
        if owned!=plan.get('owned_snapshot'):raise FleetError('ownership changed since plan')
        actual={p:(digest(safe_path(p).read_bytes()) if safe_path(p).exists() else None) for p in set(desired)|set(owned)}
        if actual!=plan.get('managed_snapshot'):raise FleetError('managed files changed since plan')
    return reconcile(state,native_factory,validate=validate,refresh=refresh,allow_local_remote=allow_local_remote,preflight=preflight)

def reconcile(state,native_factory=Native,validate=validate_generation,refresh=refresh_context,allow_local_remote=False,preflight=None):
    state=safe_path(state)
    with lock(state):
        e=validate_enrollment(json.loads((state/'enrollment.json').read_text()),allow_local_remote=allow_local_remote)
        receipt={'schema_version':1,'host_id':e['host_id'],'observed_at':stamp(),'status':'reconciling','desired_revision':None,'applied_revision':None,'effective':False}
        try:
            rev,root=materialize(state,e);receipt['desired_revision']=rev
            receipt['source_digest']=validate(root)
            policy=json.loads((root/'fleet.json').read_text())
            version=codex_version()
            receipt['documentation']=refresh(state,root,version,policy)
            if policy.get('codex_version_prefix') and not version.startswith(policy['codex_version_prefix']):raise FleetError('Codex version changed; refresh docs and validate compatibility before rollout')
            if policy.get('coordination_ref','refs/heads/cac-coordination')!='refs/heads/cac-coordination':raise FleetError('unsupported coordination ref')
            if policy.get('schema_version')!=1 or policy.get('enabled') is not True:raise FleetError('fleet policy disabled or unsupported')
            # Presence-only requirements. Never read or serialize credential values.
            missing=[name for name in policy.get('required_environment',[]) if not re.fullmatch(r'[A-Z_][A-Z0-9_]*',name) or name not in os.environ]
            if missing:raise FleetError('required host-local environment reference is unavailable')
            desired,owned,changes,stale=plan_files(state,e,root,rev)
            if preflight is not None:preflight(e,rev,root,desired,owned)
            write_files(state,desired,owned,stale)
            for dest,source in resources(root).items():
                safe_path(Path(e['home'])/dest).chmod(0o700 if source.stat().st_mode & 0o111 else 0o600)
            receipt['applied_revision']=rev
            with native_factory() as native:
                proof=native.activate(root)
            receipt.update(status='native_verified',effective=True,fresh_task_verified=False,native=proof,changed_resources=len(changes)+len(stale),codex_version=version)
            atomic(state/'current.json',{'revision':rev,'root':str(root),'host_id':e['host_id']})
        except (FleetError,ValueError,OSError,subprocess.SubprocessError) as exc:
            receipt.update(status='blocked',error=type(exc).__name__,failure_detail=(str(exc)[:240] if type(exc) is FleetError else 'dependency operation failed; inspect that provider separately'))
            atomic(state/'receipt.json',receipt)
            from .cac_sdlc import record_incident
            record_incident(state,{'host_id':e['host_id'],'revision':receipt.get('desired_revision') or 'unknown','error_code':type(exc).__name__})
            raise FleetError('reconciliation blocked; see local receipt') from exc
        atomic(state/'receipt.json',receipt)
        return receipt

def discover(state,client_factory=None):
    from .native_workspace import Client
    e=json.loads((state/'enrollment.json').read_text());home=Path(e['home']);items={}
    def add(name,path,scope):
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}',name):return
        try:p=safe_path(path)
        except FleetError:return
        if p.name!='SKILL.md' or not p.is_relative_to(home) or not p.is_file() or p.stat().st_size>1024*1024:return
        items[name]={'name':name,'sha256':digest(p.read_bytes()),'host_id':e['host_id'],'scope':scope,'promotion':'not_shared_until_committed'}
    for base in [home/'.agents/skills',home/'.codex/skills']:
        if base.exists():
            for p in sorted(base.glob('*/SKILL.md')):add('local/'+p.parent.name,p,'host-local-discovery')
    current=json.loads((state/'current.json').read_text())
    with (client_factory or Client)() as client:
        result=client.request('skills/list',{'cwds':[current['root']],'forceReload':True})
    for entry in result.get('data',[]):
        for skill in entry.get('skills',[]):
            if isinstance(skill.get('path'),str):add('native/'+skill.get('scope','unknown')+'/'+skill.get('name',''),skill['path'],'native-skill-catalogue')
    if len(items)>512:raise FleetError('skill catalogue exceeds publication bound')
    values=list(items.values());atomic(state/'skill-discovery.json',{'observed_at':stamp(),'skills':values});return values

def service(state,interval):
    from concurrent.futures import ThreadPoolExecutor
    from .cac_jobs import run_once
    executor=ThreadPoolExecutor(max_workers=1);job=None
    while True:
        try:
            receipt=reconcile(state);skills=discover(state);publish_observation(state,receipt,skills)
            if job is not None and job.done():
                try:atomic(state/'job-poll.json',{'status':'checked','result':job.result()})
                except Exception:atomic(state/'job-poll.json',{'status':'failed','detail':'inspect queue and local work record'})
                job=None
            if job is None:
                current=json.loads((state/'current.json').read_text());root=Path(current['root'])
                if (root/'fleet-jobs.json').exists():job=executor.submit(run_once,state,root)
        except Exception:
            try:
                receipt=json.loads((state/'receipt.json').read_text());known=json.loads((state/'skill-discovery.json').read_text()).get('skills',[]) if (state/'skill-discovery.json').exists() else [];publish_observation(state,receipt,known)
            except Exception:atomic(state/'transport-error.json',{'at':stamp(),'status':'could not publish host observation'}) # receipt carries failure; next interval retries without model calls
        time.sleep(interval)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,default=Path.home()/'.local/state/cac-fleet')
    s=p.add_subparsers(dest='command',required=True)
    j=s.add_parser('join');j.add_argument('--remote',required=True);j.add_argument('--branch',required=True);j.add_argument('--host',required=True);j.add_argument('--project-root',action='append',type=Path)
    pl=s.add_parser('plan');pl.add_argument('--out',type=Path)
    ap=s.add_parser('apply');ap.add_argument('--plan',type=Path,required=True)
    s.add_parser('reconcile');s.add_parser('status');s.add_parser('discover');s.add_parser('fleet-status');s.add_parser('install-service')
    w=s.add_parser('watch');w.add_argument('--interval',type=int,default=60)
    args=p.parse_args(argv)
    try:
        if args.command=='join':out=enroll(args.state,args.remote,args.branch,args.host,project_roots=args.project_root)
        elif args.command=='plan':out=deployment_plan(args.state,args.out)
        elif args.command=='apply':
            out=apply_plan(args.state,args.plan);publish_observation(args.state,out,discover(args.state))
        elif args.command=='reconcile':
            out=reconcile(args.state);publish_observation(args.state,out,discover(args.state))
        elif args.command=='install-service':out=install_service(args.state)
        elif args.command=='fleet-status':out=fleet_status(args.state)
        elif args.command=='discover':out=discover(args.state)
        elif args.command=='status':out=json.loads((args.state/'receipt.json').read_text())
        else:
            if args.interval<10:raise FleetError('minimum interval is ten seconds')
            service(args.state,args.interval);return
        print(json.dumps(out,indent=2))
    except (FleetError,OSError,ValueError):
        print(json.dumps({'status':'error','message':'operation failed; inspect the local receipt and enrollment'}));sys.exit(1)
if __name__=='__main__':main()
