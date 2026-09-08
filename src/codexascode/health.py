"""Local deployment diagnostics without reading credentials or contacting Git."""
import datetime as dt
import json
from pathlib import Path
from .runtime.cac_fleet import safe_path,digest

def inspect(state):
 state=safe_path(state)
 def read(name):
  path=safe_path(state/name)
  if not path.exists():return {}
  if path.stat().st_size>1024*1024:raise ValueError('local diagnostic record exceeds limit')
  value=json.loads(path.read_text())
  if not isinstance(value,dict):raise ValueError('invalid diagnostic record')
  return value
 enrollment=read('enrollment.json');receipt=read('receipt.json');owned=read('ownership.json');drift=[]
 for name,expected in owned.items():
  path=safe_path(name)
  if not path.is_file() or digest(path.read_bytes())!=expected:drift.append(name)
 age=None
 if receipt.get('observed_at'):
  observed=dt.datetime.fromisoformat(receipt['observed_at'].replace('Z','+00:00'))
  age=max(0,int((dt.datetime.now(dt.timezone.utc)-observed).total_seconds()))
 enrolled=bool(enrollment);fresh=age is not None and age<=900
 return {'enrolled':enrolled,'host_id':enrollment.get('host_id'),'revision':receipt.get('desired_revision'),'status':receipt.get('status','not-observed'),'receipt_age_seconds':age,'native_verified':receipt.get('effective') is True,'fresh_task_verified':receipt.get('fresh_task_verified') is True,'drift':drift,'healthy':enrolled and fresh and receipt.get('effective') is True and not drift,'coverage':'local observed state; this does not prove other hosts are current'}
