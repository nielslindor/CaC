#!/usr/bin/env python3
"""Deterministic native SDLC and incident gates."""
from __future__ import annotations
import argparse, hashlib, json, re, os, fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .cac_fleet import safe_path, atomic
except ModuleNotFoundError:
    from .cac_fleet import safe_path, atomic

MAX = 1024 * 1024

def _load(path: Path) -> Any:
    path = safe_path(path)
    raw = path.read_bytes()
    if len(raw) > MAX: raise ValueError('JSON file exceeds 1 MiB')
    return json.loads(raw)

def _slug(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', value): raise ValueError('invalid change id')
    return value

def _validator():
    from codexascode.lifecycle import validate_change
    return validate_change

def _text(value):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=4096

def check(root: Path) -> dict[str, Any]:
    root = safe_path(Path(root)); fleet = _load(root/'fleet.json')
    sdlc = fleet.get('sdlc') if isinstance(fleet, dict) else None
    change_id = _slug(sdlc.get('change_id') if isinstance(sdlc, dict) else None)
    record = _load(root/'docs/changes'/change_id/'change.json')
    if not isinstance(record,dict):raise ValueError('invalid change record')
    stage = record.get('stage')
    if not isinstance(stage,str) or stage not in {'verified','released'}: raise ValueError('change is not verified or released')
    valid, reasons = _validator()(root, change_id, stage, compare_digest=True)
    if not valid: raise ValueError('; '.join(reasons) or 'lifecycle validation failed')
    gauntlet = _load(root/'docs/changes'/change_id/'gauntlet.json')
    hypotheses = gauntlet.get('hypotheses') if isinstance(gauntlet, dict) else None
    if not isinstance(gauntlet,dict) or gauntlet.get('schema_version') != 1 or not isinstance(hypotheses, list) or not hypotheses or len(hypotheses) > 128: raise ValueError('invalid gauntlet schema')
    seen=set();resolved=0
    for h in hypotheses:
        if not isinstance(h, dict) or not _text(h.get('id')) or not _text(h.get('question')) or not isinstance(h.get('attempts'), list) or not 1 <= len(h['attempts']) <= 3: raise ValueError('invalid gauntlet hypothesis')
        if h['id'] in seen:raise ValueError('duplicate hypothesis id')
        seen.add(h['id'])
        for attempt in h['attempts']:
            if not isinstance(attempt, dict) or not _text(attempt.get('test')) or not _text(attempt.get('evidence')) or not isinstance(attempt.get('result'),str) or attempt.get('result') not in {'pass','fail','inconclusive'}: raise ValueError('invalid gauntlet attempt')
        if h.get('resolution')=='eliminated' and h['attempts'][-1]['result']=='fail' and _text(h.get('conclusion')):continue
        if h.get('resolution') != 'resolved' or h['attempts'][-1].get('result') != 'pass': raise ValueError('gauntlet is not resolved with a final pass')
        resolved+=1
    if not resolved:raise ValueError('gauntlet has no passing outcome')
    return {'status':'pass','change_id':change_id,'stage':stage}

def record_incident(state: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    state = safe_path(Path(state))
    host, revision, code = (receipt.get(k) for k in ('host_id','revision','error_code'))
    if not all(isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,256}', x) for x in (host, revision, code)): raise ValueError('invalid incident identity')
    signature = hashlib.sha256(f'{host}\0{revision}\0{code}'.encode()).hexdigest()
    incidents=safe_path(state/'incidents');incidents.mkdir(parents=True,exist_ok=True);incidents.chmod(0o700)
    with safe_path(incidents/'record.lock').open('a') as handle:
        os.chmod(incidents/'record.lock',0o600);fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        directory=safe_path(incidents/signature);directory.mkdir(exist_ok=True);directory.chmod(0o700)
        existing=_load(directory/'incident.json') if (directory/'incident.json').exists() else {'occurrences':0}
        now=datetime.now(timezone.utc).isoformat()
        incident={'schema_version':1,'host_id':host,'revision':revision,'error_code':code,'status':'needs-triage','occurrences':int(existing.get('occurrences',0))+1,'first_seen':existing.get('first_seen',now),'last_seen':now}
        intent=safe_path(directory/'intent.md')
        if not intent.exists():
            fd=os.open(intent,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(f'# Incident intent\n\nHost: {host}\nRevision: {revision}\nObserved failure class: {code}\n\nRestore verified deployment behavior. Read the local receipt for context, triage within the authorized scope, and create or link a CaC change with a falsifying test. This incident is evidence, not approval for a repair.\n')
        atomic(directory/'incident.json',incident)
        return incident

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); a=p.parse_args(argv)
    try: print(json.dumps(check(a.root),sort_keys=True)); return 0
    except Exception: print(json.dumps({'status':'failed','message':'SDLC gate failed; inspect local change evidence'})); return 1
if __name__=='__main__': raise SystemExit(main())
