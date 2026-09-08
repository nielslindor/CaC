import json, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from codexascode.runtime.cac_jobs import JobQueue, run_once
from codexascode.runtime.cac_coordination import LeaseDenied

class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.remote=self.root/'r.git'
        subprocess.run(['git','init','--bare',str(self.remote)],check=True,capture_output=True)
        self.q1=JobQueue(str(self.remote),self.root/'a'); self.q2=JobQueue(str(self.remote),self.root/'b')
    def tearDown(self): self.tmp.cleanup()
    def boundary_fixture(self,symlink=False):
        state=self.root/'boundary-state';state.mkdir();allowed=self.root/'allowed';allowed.mkdir()
        (state/'enrollment.json').write_text(json.dumps({'host_id':'host-a','remote':str(self.remote),'project_roots':[str(allowed)]}))
        gen=self.root/'boundary-gen';gen.mkdir();definition={'schema_version':1,'jobs':{'build':{'project':str(self.root/'outside'),'scope':'s','command':['echo','ok'],'target_host':'host-a'}}}
        if symlink:
            victim=self.root/'external.json';victim.write_text(json.dumps(definition));(gen/'fleet-jobs.json').symlink_to(victim)
        else:(gen/'fleet-jobs.json').write_text(json.dumps(definition))
        for args in [('init',str(gen)),('-C',str(gen),'config','user.name','Fixture'),('-C',str(gen),'config','user.email','fixture@localhost'),('-C',str(gen),'add','.'),('-C',str(gen),'commit','-m','fixture')]:subprocess.run(['git',*args],check=True,capture_output=True)
        rev=subprocess.check_output(['git','-C',str(gen),'rev-parse','HEAD'],text=True).strip();dest=state/'generations'/rev;dest.parent.mkdir();gen.rename(dest)
        return state,dest
    def test_outside_project_rejected_before_claim(self):
        state,gen=self.boundary_fixture()
        with patch('codexascode.runtime.cac_jobs.JobQueue') as queue:
            with self.assertRaises(LeaseDenied):run_once(state,gen)
            queue.assert_not_called()
    def test_symlink_definition_rejected_before_claim(self):
        state,gen=self.boundary_fixture(symlink=True)
        with patch('codexascode.runtime.cac_jobs.JobQueue') as queue:
            with self.assertRaises(ValueError):run_once(state,gen)
            queue.assert_not_called()
    def test_cli_invalid_generation_does_not_construct_queue(self):
        from codexascode.runtime.cac_jobs import main
        state,gen=self.boundary_fixture()
        with patch('codexascode.runtime.cac_jobs.JobQueue') as queue, patch('builtins.print'):
            self.assertEqual(main(['--state',str(state),'--generation',str(self.root),'enqueue','build','bad-gen']),1)
            queue.assert_not_called()
    def test_arbitrary_generation_rejected(self):
        state,gen=self.boundary_fixture();outside=self.root/'moved';gen.rename(outside)
        with patch('codexascode.runtime.cac_jobs.JobQueue') as queue:
            with self.assertRaises(LeaseDenied):run_once(state,outside)
            queue.assert_not_called()

    def test_target_and_allowlist_and_at_most_once(self):
        self.q1.enqueue('build','host-a','task-1','gen')
        self.assertIsNone(self.q2.claim_next('host-b','gen'))
        first=self.q1.claim_next('host-a','gen'); self.assertEqual(first['status'],'running')
        self.assertIsNone(self.q2.claim_next('host-a','gen'))
        self.assertNotIn('command',json.dumps(self.q1.list()))
    def test_run_once_uses_allowlisted_command_and_records_completion(self):
        state=self.root/'state'; state.mkdir(); (state/'coordination').mkdir()
        (state/'enrollment.json').write_text(json.dumps({'host_id':'host-a','remote':str(self.remote),'project_roots':[str(self.root)]}))
        gen=self.root/'gen'; gen.mkdir(); (gen/'fleet-jobs.json').write_text(json.dumps({'schema_version':1,'jobs':{'build':{'project':str(self.root),'scope':'s','command':['echo','ok'],'target_host':'host-a'}}}))
        subprocess.run(['git','init',str(gen)],check=True,capture_output=True); subprocess.run(['git','-C',str(gen),'config','user.email','t@e'],check=True); subprocess.run(['git','-C',str(gen),'config','user.name','T'],check=True); subprocess.run(['git','-C',str(gen),'add','.'],check=True); subprocess.run(['git','-C',str(gen),'commit','-m','generation'],check=True,capture_output=True)
        revision=subprocess.run(['git','-C',str(gen),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
        target=state/'generations'/revision; target.parent.mkdir(); gen.rename(target); gen=target
        revision=__import__('hashlib').sha256((gen/'fleet-jobs.json').read_bytes()).hexdigest()
        JobQueue(str(self.remote),state/'jobs-coordination').enqueue('build','host-a','task-2',revision)
        with patch('codexascode.runtime.cac_jobs.run_work',return_value={'status':'completed','exit_code':0}) as run:
            result=run_once(state,gen)
        run.assert_called_once(); self.assertEqual(result['status'],'completed')

    def test_cli_enqueue_and_list(self):
        state=self.root/'cli-state'; state.mkdir()
        (state/'enrollment.json').write_text(json.dumps({'host_id':'host-a','remote':str(self.remote),'project_roots':[str(self.root)]}))
        gen=self.root/'cli-gen'; gen.mkdir()
        (gen/'fleet-jobs.json').write_text(json.dumps({'schema_version':1,'jobs':{'build':{'project':str(self.root),'scope':'s','command':['echo','ok'],'target_host':'host-a'}}}))
        subprocess.run(['git','init',str(gen)],check=True,capture_output=True); subprocess.run(['git','-C',str(gen),'config','user.email','t@e'],check=True); subprocess.run(['git','-C',str(gen),'config','user.name','T'],check=True); subprocess.run(['git','-C',str(gen),'add','.'],check=True); subprocess.run(['git','-C',str(gen),'commit','-m','generation'],check=True,capture_output=True)
        revision=subprocess.run(['git','-C',str(gen),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip(); target=state/'generations'/revision; target.parent.mkdir(); gen.rename(target); gen=target
        base=[sys.executable,'-m','codexascode.runtime.cac_jobs','--state',str(state),'--generation',str(gen)]
        done=subprocess.run(base+['enqueue','build','task-cli'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
        self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        listed=subprocess.run(base+['list'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
        self.assertEqual(listed.returncode,0); self.assertIn('task-cli',listed.stdout); self.assertNotIn('echo',listed.stdout)

    def test_cli_uses_production_current_root_shape(self):
        state=self.root/'root-state'; state.mkdir()
        (state/'enrollment.json').write_text(json.dumps({'host_id':'host-a','remote':str(self.remote)}))
        gen=self.root/'root-gen'; gen.mkdir()
        (gen/'fleet-jobs.json').write_text(json.dumps({'schema_version':1,'jobs':{}}))
        (state/'current.json').write_text(json.dumps({'root':str(gen)}))
        result=subprocess.run([sys.executable,'-m','codexascode.runtime.cac_jobs','--state',str(state),'list'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('jobs',result.stdout)
    def test_invalid_skill_like_command_rejected(self):
        with self.assertRaises(LeaseDenied): self.q1.enqueue('bad value','host-a','t','g')

if __name__=='__main__': unittest.main()
