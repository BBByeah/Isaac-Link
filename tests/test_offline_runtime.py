import time
import unittest
from unittest.mock import patch
from offline_runtime import OfflineRuntime
from transport import Transport

class Script:
    def __init__(self):self.exports_sync=self;self.installed=False
    def info(self):return {'steam':'1'}
    def status(self):return {}
    def configure(self,s):self.states=s
    def install(self):self.installed=True
    def restore(self):self.installed=False
    def post(self,*args):pass

class OfflineTests(unittest.TestCase):
    def test_ipv6_delivery_and_native_route(self):
        received=[];other=Transport(2,'::1',0,lambda *v:received.append(v),test=True)
        rt=OfflineRuntime(lambda x:None,'WHEAT');rt.script=Script()
        def local(steam,ip,port,callback,**kw):return Transport(steam,ip,port,callback,test=True,**kw)
        try:
            with patch('runtime.Transport',local):rt.start('::1',0)
            rt.transport.add(other.local);other.add(rt.transport.local)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and not rt.transport.active(2):time.sleep(.05)
            rt.test();self.assertTrue(rt.script.installed)
            rt.transport.send(2,0,1,b'input-test')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not received:time.sleep(.01)
            self.assertEqual(received[0][2],b'input-test')
            rt.set_route('1','2','steam');self.assertTrue(rt.transport.native(2))
            with self.assertRaises(ValueError):rt.set_route('1','2','relay')
        finally:rt.close();other.close()

if __name__=='__main__':unittest.main()
