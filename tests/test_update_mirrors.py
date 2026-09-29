import base64
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError
import test_updates7
from isaac_link.updates import UpdateManager,GITEE_SOURCE,SOURCES


class MirrorUpdates(unittest.TestCase):
    setUp=test_updates7.Updates.setUp
    tearDown=test_updates7.Updates.tearDown
    package=test_updates7.Updates.package

    def signed(self,manifest):
        payload=json.dumps(manifest).encode()
        return json.dumps(dict(payload=base64.b64encode(payload).decode(),signature=base64.b64encode(self.key.sign(payload)).decode())).encode()

    def test_github_offline_checks_gitee_signed_manifest(self):
        _,manifest,path=self.package('0.7.4')
        wrapped=json.dumps(dict(encoding='base64',content=base64.b64encode(path.read_bytes()).decode())).encode()
        def fetch(url):
            if url==SOURCES[0]:raise URLError('GitHub unavailable')
            self.assertEqual(url,GITEE_SOURCE);return wrapped
        manager=UpdateManager(self.root)
        with patch('isaac_link.updates.fetch',side_effect=fetch),patch('isaac_link.updates.public_key',return_value=self.key.public_key()):manager.check()
        self.assertEqual(manager.status,'available');self.assertEqual(manager.manifest_source,GITEE_SOURCE)

    def test_bad_primary_signature_falls_back_and_bad_mirror_rejected(self):
        _,_,path=self.package('0.7.4');manager=UpdateManager(self.root)
        with patch('isaac_link.updates.fetch_manifest',side_effect=[b'{}',path.read_bytes()]),patch('isaac_link.updates.public_key',return_value=self.key.public_key()):manager.check()
        self.assertEqual(manager.manifest_source,GITEE_SOURCE)
        with patch('isaac_link.updates.fetch_manifest',return_value=b'{}'):
            with self.assertRaises(ValueError):manager.check()
        self.assertIsNone(manager.manifest);self.assertIsNone(manager.raw)

    def test_package_falls_back_after_network_or_signature_failure(self):
        archive,manifest,_=self.package('0.7.4');data=archive.read_bytes()
        manifest['urls']=['https://github.com/test/client.zip','https://gitee.com/test/client.zip']
        class Response(io.BytesIO):
            def __init__(self,data,url):super().__init__(data);self.url=url
        for failure in ('network','signature'):
            with self.subTest(failure=failure):
                manager=UpdateManager(self.root);manager.manifest=manifest;manager.raw=self.signed(manifest)
                def open_url(request,**kwargs):
                    if request.full_url==manifest['urls'][0]:
                        if failure=='network':raise URLError('GitHub unavailable')
                        return Response(b'x'*len(data),request.full_url)
                    return Response(data,request.full_url)
                with patch('urllib.request.urlopen',side_effect=open_url),patch('isaac_link.updates.public_key',return_value=self.key.public_key()):manager.download()
                self.assertEqual(manager.status,'ready');self.assertEqual(manager.archive.read_bytes(),data)
                self.assertEqual(manager.download_source,manifest['urls'][1])

    def test_cancellation_does_not_start_mirror_download(self):
        _,manifest,_=self.package('0.7.4');manifest['urls']=['https://github.com/a','https://gitee.com/a']
        manager=UpdateManager(self.root);manager.manifest=manifest;manager.raw=self.signed(manifest);manager.cancel.set()
        with patch('urllib.request.urlopen') as opened,patch('isaac_link.updates.public_key',return_value=self.key.public_key()):
            with self.assertRaises(InterruptedError):manager.download()
        opened.assert_not_called()
