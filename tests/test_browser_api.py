import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from isaac_link.browser_app import Backend,make_server

class BrowserApi(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.backend=Backend(Path(self.temp.name))
        self.server,self.token=make_server(self.backend)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
    def tearDown(self):self.server.shutdown();self.thread.join();self.server.server_close();self.temp.cleanup()
    def request(self,path,method='GET',body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request(method,path,json.dumps(body) if body is not None else None,headers or {})
        r=conn.getresponse();data=r.read();conn.close();return r.status,data
    def test_local_session_and_origin(self):
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/api/state')[0],403)
        h={'X-Isaac-Token':self.token};status,body=self.request('/api/state',headers=h)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['profile'],{})
        self.assertEqual(self.request('/api/state',headers={**h,'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request('/',headers={'Host':'evil.example'})[0],403)
    def test_actions_and_paths(self):
        h={'X-Isaac-Token':self.token,'Content-Type':'application/json'}
        self.assertEqual(self.request('/api/action','POST',{'action':'unknown'},h)[0],400)
        self.assertEqual(self.request('/../server.json')[0],404)
        self.assertEqual(self.request('/api/action','POST',{'action':'disconnect'},h)[0],202)
    def test_profile_survives_restart(self):
        (Path(self.temp.name)/'profile.json').write_text('{"player_id":"WHEAT"}',encoding='utf-8')
        self.assertEqual(Backend(Path(self.temp.name)).state()['profile']['player_id'],'WHEAT')

if __name__=='__main__':unittest.main()
