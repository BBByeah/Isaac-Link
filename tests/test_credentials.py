import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from isaac_link.browser_app import Backend
from isaac_link.credential_store import ServerCredential
from isaac_link.server_code import encode_server_code


class CredentialsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.code = encode_server_code(dict(host='example.test', port=27668,
            udp_port=27667, sha256='a'*64, access_key='b'*64))

    def test_encrypted_roundtrip_and_forget(self):
        store = ServerCredential(self.folder)
        store.save(self.code)
        self.assertNotIn(self.code.encode(), store.path.read_bytes())
        self.assertNotIn(b'example.test', store.path.read_bytes())
        self.assertEqual(ServerCredential(self.folder).load(), self.code)
        store.forget()
        self.assertEqual(store.load(), '')

    def runtime(self):
        return Mock(room={}, transport=None, code='', failure='', control_failure='')

    def test_connect_remembers_reuses_and_forgets(self):
        backend = Backend(self.folder)
        with patch('isaac_link.backend.RuntimeV5', return_value=self.runtime()):
            backend.action('connect', dict(player_id='WHEAT', server_code=self.code))
        backend = Backend(self.folder)
        self.assertTrue(backend.state()['saved_server'])
        self.assertNotIn(self.code, json.dumps(backend.state()))
        self.assertNotIn(self.code, (self.folder/'profile.json').read_text())
        with patch('isaac_link.backend.RuntimeV5', return_value=self.runtime()) as factory:
            backend.action('connect', dict(player_id='WHEAT', server_code=backend.saved_server_code))
            self.assertEqual(factory.call_args.args[2]['host'], 'example.test')
        backend.credentials.forget()
        self.assertFalse(Backend(self.folder).state()['saved_server'])

    def test_failed_connection_preserves_previous(self):
        ServerCredential(self.folder).save(self.code)
        backend = Backend(self.folder)
        new_code = encode_server_code(dict(host='replacement.test', port=27668,
            udp_port=27667, sha256='c'*64, access_key='d'*64))
        rt = self.runtime();rt.start.side_effect = RuntimeError('connection failed')
        with patch('isaac_link.backend.RuntimeV5', return_value=rt):
            with self.assertRaises(RuntimeError):
                backend.action('connect', dict(player_id='WHEAT', server_code=new_code))
        self.assertEqual(ServerCredential(self.folder).load(), self.code)

    def test_corrupt_storage_does_not_prevent_start(self):
        (self.folder/'server-code.dpapi').write_bytes(b'corrupt')
        self.assertFalse(Backend(self.folder).state()['saved_server'])

    def test_save_failure_keeps_connection(self):
        backend = Backend(self.folder);rt = self.runtime()
        with patch('isaac_link.backend.RuntimeV5', return_value=rt), patch.object(backend.credentials,'save',side_effect=OSError('failed')):
            backend.action('connect', dict(player_id='WHEAT', server_code=self.code))
        self.assertIs(backend.runtime, rt)
        self.assertFalse(backend.saved_server_code)


if __name__ == '__main__':unittest.main()
