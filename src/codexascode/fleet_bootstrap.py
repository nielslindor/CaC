"""Opt-in native fleet scaffold; never activates a host during workspace creation."""
import json
from pathlib import Path
from importlib.resources import files
from . import engine,lifecycle
from .runtime.cac_fleet import safe_path,atomic

def enable_fleet(root):
    root=Path(root).absolute()
    manifest_path=safe_path(root/'cac.json');original=manifest_path.read_bytes()
    manifest=engine.load_manifest(manifest_path)
    assets=files('codexascode').joinpath('templates/fleet')
    desired={}
    def collect(directory,prefix=''):
        for item in directory.iterdir():
            path=prefix+item.name
            if item.is_dir():collect(item,path+'/')
            else:desired[path]=item.read_text()
    collect(assets)
    existing={f['path']:f for f in manifest['spec']['files']}
    # Existing definitions belong to the owner; never overwrite them to reinstall defaults.
    for path,content in desired.items():
        if path not in existing:manifest['spec']['files'].append({'path':path,'content':content})
    preview=engine.plan(manifest,root)
    if preview.get('conflicts'):raise ValueError('fleet scaffold conflicts with existing content')
    if manifest_path.read_bytes()!=original:raise ValueError('manifest changed during fleet planning')
    engine.apply(manifest,root)
    if manifest_path.read_bytes()!=original:raise ValueError('manifest changed during fleet application; owner edits preserved')
    atomic(manifest_path,manifest)
    if lifecycle.create_change(root,'Verify the native fleet bootstrap','fleet-bootstrap')!=0:raise ValueError('cannot create fleet bootstrap lifecycle')
    return {'status':'scaffolded','change_id':'fleet-bootstrap','activation':'not enrolled; complete verification before joining a host'}
