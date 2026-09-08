import contextlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from codexascode.runtime.cac_fleet import enroll,reconcile as real_reconcile,FleetError,plan_files,safe_path
def reconcile(state,native):return real_reconcile(state,native,validate=lambda root:'fixture',refresh=lambda *a:{'status':'fixture'},allow_local_remote=True)

def run(*args,cwd=None):
 return subprocess.check_output(['git',*map(str,args)],cwd=cwd,stderr=subprocess.DEVNULL).decode().strip()
class FakeNative:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def activate(self,root):return {'project_config_loaded':True,'skills_discovered':['sample'],'fresh_task_probe':'not_run'}
class BadNative(FakeNative):
 def activate(self,root):raise FleetError('native project configuration is not loaded')
class FleetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name).resolve()
  self.src=self.base/'src';self.src.mkdir();run('init','-b','deploy',self.src)
  run('config','user.name','Fixture',cwd=self.src);run('config','user.email','fixture@localhost',cwd=self.src)
  for d in ['.codex','.agents/skills/sample']:(self.src/d).mkdir(parents=True,exist_ok=True)
  (self.src/'.gitignore').write_text('/chats/loose/\n')
  (self.src/'AGENTS.md').write_text('Shared fixture instructions')
  (self.src/'.codex/config.toml').write_text('[agents]\nenabled = true\n')
  (self.src/'.agents/skills/sample/SKILL.md').write_text('---\nname: sample\ndescription: fixture\n---\nVersion one')
  (self.src/'fleet.json').write_text(json.dumps({'schema_version':1,'enabled':True,'required_environment':[]}))
  self.commit();self.remote=self.base/'remote.git';run('clone','--bare',self.src,self.remote)
  self.states=[]
  for h in ['one','two']:
   home=self.base/h;home.mkdir();state=self.base/('state-'+h)
   enroll(state,str(self.remote),'deploy',h,home,test_remote=True);self.states.append(state)
  self.validation=patch('codexascode.runtime.cac_fleet.validate_generation',return_value='fixture')
  self.version=patch('codexascode.runtime.cac_fleet.codex_version',return_value='codex-cli 0.153.4');self.version.start();self.addCleanup(self.version.stop)
 def commit(self):run('add','.',cwd=self.src);run('commit','-m','fixture',cwd=self.src)
 def test_push_reaches_two_hosts_preserves_old_generation(self):
  a=reconcile(self.states[0],FakeNative);b=reconcile(self.states[1],FakeNative)
  self.assertEqual(a['desired_revision'],b['desired_revision'])
  old=self.states[0]/'generations'/a['desired_revision'];(old/'chats/loose').mkdir(parents=True);(old/'chats/loose/active-task.txt').write_text('valuable uncommitted work')
  self.assertEqual(reconcile(self.states[0],FakeNative)['changed_resources'],0)
  (self.src/'.agents/skills/sample/SKILL.md').write_text('---\nname: sample\ndescription: fixture\n---\nVersion two')
  self.commit();run('push',self.remote,'deploy',cwd=self.src)
  c=reconcile(self.states[0],FakeNative);d=reconcile(self.states[1],FakeNative)
  self.assertEqual(c['desired_revision'],d['desired_revision']);self.assertNotEqual(a['desired_revision'],c['desired_revision'])
  self.assertEqual((old/'chats/loose/active-task.txt').read_text(),'valuable uncommitted work')
  self.assertIn('Version two',(self.base/'two/.agents/skills/cac-sample/SKILL.md').read_text())
 def test_executable_skill_helpers_preserved(self):
  p=self.src/'.agents/skills/sample/helper.sh';p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
  self.commit();run('push',self.remote,'deploy',cwd=self.src)
  reconcile(self.states[0],FakeNative)
  self.assertEqual((self.base/'one/.agents/skills/cac-sample/helper.sh').stat().st_mode & 0o777,0o700)
 def test_native_plugin_discovery_without_content_publication(self):
  from codexascode.runtime.cac_fleet import discover
  state=self.states[0];reconcile(state,FakeNative)
  plugin=self.base/'one/.codex/plugins/cache/example/skills/new/SKILL.md';plugin.parent.mkdir(parents=True);plugin.write_text('private skill instructions')
  class Catalogue:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def request(self,*a):return {'data':[{'skills':[{'name':'example:new','scope':'user','path':str(plugin)}]}]}
  items=discover(state,Catalogue)
  self.assertIn('native/user/example:new',[x['name'] for x in items]);self.assertNotIn('private skill instructions',json.dumps(items))
 def test_sdlc_failure_precedes_native_writes_and_creates_incident(self):
  from codexascode.runtime.cac_sdlc import check
  with self.assertRaises(FleetError):real_reconcile(self.states[0],FakeNative,validate=check,refresh=lambda *a:{},allow_local_remote=True)
  self.assertFalse((self.base/'one/.codex/AGENTS.md').exists())
  receipts=list((self.states[0]/'incidents').glob('*/incident.json'))
  self.assertEqual(len(receipts),1);self.assertEqual(json.loads(receipts[0].read_text())['status'],'needs-triage')
 def test_native_failure_not_convergence(self):
  with self.assertRaises(FleetError):reconcile(self.states[0],BadNative)
  r=json.loads((self.states[0]/'receipt.json').read_text());self.assertFalse(r['effective']);self.assertEqual(r['status'],'blocked')
 def test_resource_drift_preserved(self):
  reconcile(self.states[0],FakeNative);p=self.base/'one/.agents/skills/cac-sample/SKILL.md';p.write_text('local discovery')
  with self.assertRaises(FleetError):reconcile(self.states[0],FakeNative)
  self.assertEqual(p.read_text(),'local discovery')
 def test_collision_and_symlink_refused(self):
  d=self.base/'one/.agents/skills/cac-sample';d.mkdir(parents=True);(d/'SKILL.md').write_text('existing user skill')
  with self.assertRaises(FleetError):reconcile(self.states[0],FakeNative)
  link=self.base/'link';link.symlink_to(self.base/'one',target_is_directory=True)
  with self.assertRaises(FleetError):safe_path(link/'new')
 def test_secret_values_not_serialized(self):
  with patch.dict(os.environ,{'CAC_TEST_SECRET':'super-private-value'}):r=reconcile(self.states[0],FakeNative)
  self.assertNotIn('super-private-value',json.dumps(r))
 def test_production_refuses_persisted_local_remote(self):
  from codexascode.runtime.cac_fleet import validate_enrollment
  e=json.loads((self.states[0]/'enrollment.json').read_text());e['test_remote']=True
  with self.assertRaises(FleetError):validate_enrollment(e)
 def test_service_symlink_refused(self):
  from codexascode.runtime.cac_fleet import install_service
  state=self.states[0];victim=self.base/'victim';victim.write_text('keep')
  units=self.base/'one/.config/systemd/user';units.mkdir(parents=True)
  (units/'cac-fleet.service').symlink_to(victim)
  with patch('codexascode.runtime.cac_fleet.Path.home',return_value=self.base/'one'), patch('codexascode.runtime.cac_fleet.subprocess.run') as command:
   with self.assertRaises(FleetError):install_service(state)
   command.assert_not_called()
  self.assertEqual(victim.read_text(),'keep')
class NativeTests(unittest.TestCase):
 def test_native_readback_and_existing_projects_preserved(self):
  from codexascode.runtime.cac_fleet import Native
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();(root/'.codex').mkdir();(root/'.codex/config.toml').write_text('[agents]\nenabled = true\n')
   class Client:
    user={'projects':{'/existing':{'trust_level':'trusted','custom':'preserve'}}}
    desktop={}
    def request(self,method,args):
     if method=='config/read':return {'config':{'projects':{'/inherited':{'trust_level':'trusted'}},'desktop':self.desktop},'layers':[{'name':{'type':'user'},'version':'v1','config':self.user},{'name':{'dotCodexFolder':str(root/'.codex')},'config':{'agents':{'enabled':True}}}]}
     if method=='config/batchWrite':
      assert args['expectedVersion']=='v1'
      for e in args['edits']:
       if e['keyPath']=='projects':self.user['projects']=e['value']
       else:self.desktop={'projectlessWorkspaceRoot':e['value']}
      return {}
     if method=='skills/list':return {'data':[]}
   n=Native.__new__(Native);n.client=Client();proof=n.activate(root)
   self.assertTrue(proof['project_config_loaded']);self.assertEqual(n.client.user['projects']['/existing']['custom'],'preserve');self.assertIn('/inherited',n.client.user['projects'])
if __name__=='__main__':unittest.main()
