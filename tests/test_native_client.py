import io,json,unittest
from unittest.mock import patch,MagicMock
from codexascode.runtime.native_workspace import Client,NativeError
class NativeClientTests(unittest.TestCase):
 def test_native_error_does_not_echo_provider_secret(self):
  client=Client();client.process=MagicMock();client.process.stdin=io.BytesIO();client.next_id=0
  client.buffer=(json.dumps({'id':1,'error':{'message':'PRIVATE_CREDENTIAL_VALUE'}})+'\n').encode()
  with self.assertRaises(NativeError) as error:client.request('config/read',{})
  self.assertNotIn('PRIVATE_CREDENTIAL_VALUE',str(error.exception))
 def test_initialization_failure_closes_its_process(self):
  client=Client()
  with patch('codexascode.runtime.native_workspace.subprocess.Popen') as launch,patch.object(client,'request',side_effect=NativeError('failed')):
   with self.assertRaises(NativeError):client.__enter__()
   launch.return_value.stdin.close.assert_called_once();launch.return_value.wait.assert_called_once()
 def test_spawn_failure_retains_original_error(self):
  client=Client()
  with patch('codexascode.runtime.native_workspace.subprocess.Popen',side_effect=FileNotFoundError('codex')),patch.object(client,'__exit__') as cleanup:
   with self.assertRaises(FileNotFoundError):client.__enter__()
   cleanup.assert_not_called()
 def test_notification_failure_closes_its_process(self):
  client=Client()
  with patch('codexascode.runtime.native_workspace.subprocess.Popen') as launch,patch.object(client,'request',return_value={}):
   launch.return_value.stdin.write.side_effect=BrokenPipeError()
   with self.assertRaises(BrokenPipeError):client.__enter__()
   launch.return_value.wait.assert_called_once()
