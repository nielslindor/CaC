import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from codexascode.runtime import cac_fleet as f

def git(*args,cwd=None):return subprocess.check_output(['git',*map(str,args)],cwd=cwd,stderr=subprocess.DEVNULL,text=True).strip()
class Native:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def activate(self,root):return {'native':True}
class SavedPlanTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.src=self.root/'src';self.src.mkdir();git('init','-b','deploy',self.src)
  git('config','user.name','Fixture',cwd=self.src);git('config','user.email','fixture@localhost',cwd=self.src)
  (self.src/'fleet.json').write_text(json.dumps({'schema_version':1,'enabled':True,'required_environment':[]}));(self.src/'AGENTS.md').write_text('fixture')
  self.commit();self.remote=self.root/'remote.git';git('clone','--bare',self.src,self.remote)
  self.state=self.root/'state';self.home=self.root/'home';self.home.mkdir();f.enroll(self.state,str(self.remote),'deploy','fixture',self.home,test_remote=True)
  self.plan=self.state/'reviewed.json';self.options={'validate':lambda root:'fixture','allow_local_remote':True}
  self.version=patch.object(f,'codex_version',return_value='codex-cli 0.153.4');self.version.start();self.addCleanup(self.version.stop)
 def commit(self):git('add','.',cwd=self.src);git('commit','-m','fixture',cwd=self.src)
 def save(self):return f.deployment_plan(self.state,self.plan,**self.options)
 def apply(self):return f.apply_plan(self.state,self.plan,native_factory=Native,refresh=lambda *a:{'status':'fixture'},**self.options)
 def test_valid_plan_repeat_and_tampering(self):
  self.save();self.assertEqual(self.apply()['status'],'native_verified')
  with self.assertRaises(f.FleetError):self.apply()
  self.save();self.assertEqual(self.apply()['changed_resources'],0)
  value=json.loads(self.plan.read_text());value['desired_revision']='0'*40;self.plan.write_text(json.dumps(value))
  with self.assertRaises(f.FleetError):self.apply()
 def test_changed_source_refused_before_writes(self):
  self.save();(self.src/'AGENTS.md').write_text('new revision');self.commit();git('push',self.remote,'deploy',cwd=self.src)
  with self.assertRaises(f.FleetError):self.apply()
  self.assertFalse((self.home/'.codex/AGENTS.md').exists())
 def test_changed_enrollment_and_managed_bytes_refused(self):
  self.save();p=self.state/'enrollment.json';original=p.read_text();value=json.loads(original);value['host_id']='changed';p.write_text(json.dumps(value))
  with self.assertRaises(f.FleetError):self.apply()
  p.write_text(original);self.save();(self.home/'.codex').mkdir();(self.home/'.codex/AGENTS.md').write_text('new user instruction')
  with self.assertRaises(f.FleetError):self.apply()
  self.assertEqual((self.home/'.codex/AGENTS.md').read_text(),'new user instruction')
 def test_saved_apply_cannot_bypass_environment_policy(self):
  (self.src/'fleet.json').write_text(json.dumps({'schema_version':1,'enabled':True,'required_environment':['CAC_REQUIRED_FIXTURE']}));self.commit();git('push',self.remote,'deploy',cwd=self.src);self.save()
  with patch.dict(f.os.environ,{},clear=True):
   with self.assertRaises(f.FleetError):self.apply()
  self.assertFalse((self.home/'.codex/AGENTS.md').exists())
 def test_service_uses_installed_module_on_linux_and_macos(self):
  for platform in ['linux','darwin']:
   with self.subTest(platform=platform),patch.object(f.sys,'platform',platform),patch.object(f.Path,'home',return_value=self.home),patch.object(f.subprocess,'run'):
    out=f.install_service(self.state);self.assertIn('codexascode.runtime.cac_fleet',Path(out['service']).read_text())
    repeated=f.install_service(self.state);self.assertEqual(out['service'],repeated['service'])
