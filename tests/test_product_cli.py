import contextlib,io,json,tempfile,unittest
from pathlib import Path
from codexascode.cli import main
from codexascode import engine
from unittest.mock import patch
class ProductCliTests(unittest.TestCase):
 def test_every_provider_has_installed_help(self):
  for name in ['fleet','jobs','work','context','coordination','sdlc']:
   with self.subTest(provider=name),contextlib.redirect_stdout(io.StringIO()):
    with self.assertRaises(SystemExit) as result:main([name,'--help'])
    self.assertEqual(result.exception.code,0)
 def test_fleet_initialization_is_idempotent_and_requires_acceptance(self):
  with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
   root=Path(tmp).resolve()/'workspace'
   self.assertEqual(main(['init','--root',str(root),'--name','example','--fleet']),0)
   first=(root/'cac.json').read_bytes();self.assertEqual(main(['init','--root',str(root),'--name','example','--fleet']),0);self.assertEqual(first,(root/'cac.json').read_bytes())
   self.assertTrue((root/'.agents/skills/cac-operations/SKILL.md').exists());self.assertTrue((root/'docs/SDLC.md').exists())
   self.assertEqual(main(['sdlc','--root',str(root)]),1)
   self.assertTrue(engine.verify(engine.load_manifest(root/'cac.json'),root)['ok'])

 def test_fleet_scaffold_preserves_concurrent_manifest_edit(self):
  from codexascode.fleet_bootstrap import enable_fleet
  with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
   root=Path(tmp).resolve()/'workspace';main(['init','--root',str(root),'--name','example'])
   original_apply=engine.apply
   def racing_apply(manifest,target):
    result=original_apply(manifest,target);(root/'cac.json').write_text('owner edit');return result
   with patch('codexascode.fleet_bootstrap.engine.apply',side_effect=racing_apply):
    with self.assertRaisesRegex(ValueError,'owner edits preserved'):enable_fleet(root)
   self.assertEqual((root/'cac.json').read_text(),'owner edit')

 def test_fleet_doctor_reports_missing_and_stale_state(self):
  from codexascode.health import inspect
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();self.assertFalse(inspect(root)['healthy'])
   (root/'enrollment.json').write_text('{"host_id":"fixture"}')
   (root/'receipt.json').write_text('{"observed_at":"2000-01-01T00:00:00Z","effective":true,"status":"native_verified"}')
   result=inspect(root);self.assertFalse(result['healthy']);self.assertTrue(result['native_verified'])
