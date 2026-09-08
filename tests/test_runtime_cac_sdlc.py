import json, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from codexascode.runtime import cac_sdlc

class SdlcTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve()
    def tearDown(self): self.tmp.cleanup()
    def fixture(self, stage='verified', result='pass'):
        (self.root/'docs/changes/x').mkdir(parents=True, exist_ok=True); (self.root/'fleet.json').write_text(json.dumps({'sdlc':{'change_id':'x'}}))
        rec={'schema_version':1,'id':'x','title':'X','stage':stage,'files':[],'evidence':{}}
        (self.root/'docs/changes/x/change.json').write_text(json.dumps(rec))
        (self.root/'docs/changes/x/gauntlet.json').write_text(json.dumps({'schema_version':1,'hypotheses':[{'id':'h','question':'q','attempts':[{'test':'t','evidence':'e','result':result}],'resolution':'resolved'}]}))
    def test_planned_and_failed_or_inconclusive_rejected(self):
        self.fixture('planned')
        with self.assertRaises(ValueError): cac_sdlc.check(self.root)
        for result in ('fail','inconclusive'):
            self.fixture('verified',result)
            with patch.object(cac_sdlc,'_validator',return_value=lambda *a,**k:(True,[])):
                with self.assertRaises(ValueError): cac_sdlc.check(self.root)
    def test_too_many_attempts_and_symlink_rejected(self):
        self.fixture(); p=self.root/'docs/changes/x/gauntlet.json'
        data=json.loads(p.read_text()); data['hypotheses'][0]['attempts']=[{'test':'t','evidence':'e','result':'pass'}]*4; p.write_text(json.dumps(data))
        with patch.object(cac_sdlc,'_validator',return_value=lambda *a,**k:(True,[])):
            with self.assertRaises(ValueError): cac_sdlc.check(self.root)
        outside=self.root/'outside'; outside.write_text('{}'); p.unlink(); p.symlink_to(outside)
        with self.assertRaises(ValueError): cac_sdlc.check(self.root)
    def test_malformed_result_is_a_gate_failure(self):
        self.fixture();p=self.root/'docs/changes/x/gauntlet.json';value=json.loads(p.read_text());value['hypotheses'][0]['attempts'][0]['result']=[];p.write_text(json.dumps(value))
        with patch.object(cac_sdlc,'_validator',return_value=lambda *a,**k:(True,[])):
            with self.assertRaises(ValueError):cac_sdlc.check(self.root)
    def test_eliminated_hypothesis_preserved_but_not_a_passing_outcome(self):
        self.fixture();p=self.root/'docs/changes/x/gauntlet.json';value=json.loads(p.read_text())
        rejected={'id':'wrong-cause','question':'Is it the old cause?','attempts':[{'test':'falsifier','evidence':'counterexample','result':'fail'}],'resolution':'eliminated','conclusion':'Counterexample disproves this cause.'}
        value['hypotheses'].append(rejected);p.write_text(json.dumps(value))
        with patch.object(cac_sdlc,'_validator',return_value=lambda *a,**k:(True,[])):
            self.assertEqual(cac_sdlc.check(self.root)['status'],'pass')
            value['hypotheses']=[rejected];p.write_text(json.dumps(value))
            with self.assertRaises(ValueError):cac_sdlc.check(self.root)
    def test_real_verified_record_passes_and_source_edit_invalidates_it(self):
        from codexascode.lifecycle import create_change,source_digest
        self.assertEqual(create_change(self.root,'Fixture outcome','x'),0)
        (self.root/'fleet.json').write_text(json.dumps({'sdlc':{'change_id':'x'}}))
        directory=self.root/'docs/changes/x'
        for name in ['intent','spec','plan','verification','release']:(directory/(name+'.md')).write_text('Observed fixture evidence for '+name)
        (directory/'gauntlet.json').write_text(json.dumps({'schema_version':1,'hypotheses':[{'id':'h','question':'Does fixture behave?','attempts':[{'test':'fixture assertion','evidence':'observed fixture result','result':'pass'}],'resolution':'resolved'}]}))
        p=directory/'change.json';record=json.loads(p.read_text());record['stage']='verified'
        for key in ['acceptance_criteria','verification','independent_review']:record['evidence'][key]=['Explicit fixture evidence']
        record['evidence']['source_tree_digest']=source_digest(self.root);p.write_text(json.dumps(record))
        self.assertEqual(cac_sdlc.check(self.root)['status'],'pass')
        (self.root/'changed.txt').write_text('new source')
        with self.assertRaisesRegex(ValueError,'digest'):cac_sdlc.check(self.root)
    def test_dangling_incident_intent_symlink_refused(self):
        receipt={'host_id':'host-a','revision':'abc','error_code':'deploy-failed'}
        signature=__import__('hashlib').sha256(b'host-a\0abc\0deploy-failed').hexdigest()
        directory=self.root/'incidents'/signature;directory.mkdir(parents=True)
        victim=self.root/'victim';(directory/'intent.md').symlink_to(victim)
        with self.assertRaises(ValueError):cac_sdlc.record_incident(self.root,receipt)
        self.assertFalse(victim.exists())
    def test_incident_dedup_preserves_edited_intent_and_omits_private_error(self):
        receipt={'host_id':'host-a','revision':'abc','error_code':'deploy-failed','error':'PRIVATE TOKEN'}
        first=cac_sdlc.record_incident(self.root,receipt); path=self.root/'incidents'/__import__('hashlib').sha256(b'host-a\0abc\0deploy-failed').hexdigest()
        (path/'intent.md').write_text('human edit\n'); second=cac_sdlc.record_incident(self.root,receipt)
        self.assertEqual(first['occurrences'],1); self.assertEqual(second['occurrences'],2); self.assertEqual((path/'intent.md').read_text(),'human edit\n')
        raw=(path/'incident.json').read_text(); self.assertNotIn('PRIVATE TOKEN',raw); self.assertEqual(second['status'],'needs-triage')

if __name__=='__main__': unittest.main()
