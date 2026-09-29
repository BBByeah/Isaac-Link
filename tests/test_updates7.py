import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature
from isaac_link.updates import verified_manifest,verify_package,UpdateManager
from isaac_link.updater import extract,install,EXE

class Updates(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.key=Ed25519PrivateKey.generate()
    def tearDown(self):self.temp.cleanup()
    def package(self,version='0.7.1'):
        archive=self.root/'client.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr(EXE,b'new-exe');z.writestr('updater.exe',b'updater')
            z.writestr('.isaac-link-install.json',json.dumps({'version':version}))
        manifest=dict(version=version,protocol=8,platform='windows-x64',size=archive.stat().st_size,urls=['https://example.com/client.zip'],package_signature=base64.b64encode(self.key.sign(archive.read_bytes())).decode())
        payload=json.dumps(manifest).encode();raw=json.dumps(dict(payload=base64.b64encode(payload).decode(),signature=base64.b64encode(self.key.sign(payload)).decode())).encode()
        path=self.root/'update.json';path.write_bytes(raw)
        return archive,manifest,path
    def test_signed_manifest_package_and_tampering(self):
        archive,m,path=self.package();self.assertEqual(verified_manifest(path.read_bytes(),self.key.public_key()),m)
        verify_package(archive,m,self.key.public_key())
        data=bytearray(archive.read_bytes());data[-1]^=1;archive.write_bytes(data)
        with self.assertRaises(InvalidSignature):verify_package(archive,m,self.key.public_key())
        with self.assertRaises(InvalidSignature):verified_manifest(path.read_bytes(),Ed25519PrivateKey.generate().public_key())

    def test_next_version_detected_and_same_version_not_offered(self):
        manager=UpdateManager(self.root)
        for published,expected in [('0.7.1','available'),('0.7.0','latest'),('0.6.5','latest')]:
            archive,m,path=self.package(published)
            with patch('isaac_link.updates.__version__','0.7.0'),patch('isaac_link.updates.public_key',return_value=self.key.public_key()),patch('isaac_link.updates.fetch',return_value=path.read_bytes()):
                manager.check()
            self.assertEqual(manager.status,expected)
    def test_archive_traversal_and_missing_files(self):
        archive=self.root/'evil.zip'
        for name in ('../outside','C:/outside','a\\outside','a:stream','/absolute'):
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,'x')
            with self.assertRaises(ValueError):extract(archive,self.root/'stage')
        self.assertFalse((self.root.parent/'outside').exists())
    def installation(self):
        root=self.root/'app';root.mkdir();(root/EXE).write_bytes(b'old-exe');(root/'.isaac-link-install.json').write_text('{"version":"0.7.0"}')
        (root/'captures').mkdir();(root/'captures/evidence.txt').write_text('keep')
        archive,m,path=self.package()
        return root,dict(root=str(root),archive=str(archive),manifest=str(path),pid=0)
    def test_success_preserves_user_data_and_old_directory(self):
        root,job=self.installation()
        class Process:
            def poll(self):return None
        def launch(command):Path(command[-1]).write_text('ready');return Process()
        with patch('isaac_link.updates.public_key',return_value=self.key.public_key()),patch('isaac_link.updater.wait_parent'):
            backup=install(job,launch=launch,timeout=.1)
        self.assertEqual((root/EXE).read_bytes(),b'new-exe');self.assertEqual((backup/EXE).read_bytes(),b'old-exe')
        self.assertEqual((root/'captures/evidence.txt').read_text(),'keep')
    def test_startup_failure_rolls_back(self):
        root,job=self.installation()
        class Process:
            def poll(self):return 1
        with patch('isaac_link.updates.public_key',return_value=self.key.public_key()),patch('isaac_link.updater.wait_parent'):
            with self.assertRaises(RuntimeError):install(job,launch=lambda args:Process(),timeout=.1)
        self.assertEqual((root/EXE).read_bytes(),b'old-exe');self.assertTrue((root/'captures/evidence.txt').is_file())
    def test_download_cancelled_and_truncated_not_ready(self):
        archive,m,path=self.package();manager=UpdateManager(self.root);manager.manifest=m;manager.raw=path.read_bytes()
        class Response(io.BytesIO):url='https://example.com/client.zip'
        with patch('isaac_link.updates.public_key',return_value=self.key.public_key()),patch('urllib.request.urlopen',return_value=Response(b'bad')):
            with self.assertRaises(ValueError):manager.download()
        self.assertNotEqual(manager.status,'ready')
        manager.cancel.set()
        with patch('isaac_link.updates.public_key',return_value=self.key.public_key()),patch('urllib.request.urlopen',return_value=Response(b'bad')):
            with self.assertRaises(InterruptedError):manager.download()

    def test_same_version_cannot_replace_installation(self):
        root,job=self.installation();self.package('0.7.0')
        with patch('isaac_link.updates.public_key',return_value=self.key.public_key()):
            with self.assertRaisesRegex(ValueError,'版本'):install(job)
        self.assertEqual((root/EXE).read_bytes(),b'old-exe')

if __name__=='__main__':unittest.main()
