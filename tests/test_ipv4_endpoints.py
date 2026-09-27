import collections
import hmac
import threading
import time
import unittest
from isaac_link.multipath import Multipath,WIRE
from isaac_link.transport import Peer


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.node=Multipath.__new__(Multipath);n=self.node
        n.keys={2:b'k'*32};n.local=Peer(1,'',1234,b'a'*16)
        n.peers={2:Peer(2,'',5678,b'b'*16)}
        n.endpoint4={2:('192.0.2.1',1111)};n.advertised4=dict(n.endpoint4)
        n.learned4={};n.checks4={};n.direct4_at={};n.stats=collections.Counter()
        n.lan_endpoints={}
        n.path_last={};n.path_rtt={};n.samples=collections.defaultdict(list)
        n.capture=None;n.probes={};n.round_pending={};n.selected={};n.rtt={};n.last={}
        n.lock=threading.RLock();n.test_id=0;n.revision=0;n.event=lambda x:None
        n.add=lambda p:None;n.sent=[]
        n._emit=lambda peer,route,body,endpoint4=None:n.sent.append((peer,route,body,endpoint4)) or True

    def wire(self,body,key=None):
        raw=WIRE.pack(b'I6W2',2,1,1)+body
        return raw+hmac.digest(key or self.node.keys[2],raw,'sha256')[:16]

    def test_observed_source_reply_challenge_and_keep_on_poll(self):
        n=self.node;source=('192.0.2.1',2222)
        n.receive_wire(self.wire(b'?12345678'),source)
        self.assertIn((2,'ipv4',b'!12345678',source),n.sent)
        self.assertEqual(n.endpoint4[2][1],1111)  # unverified address is not used for game traffic
        nonce=n.checks4[2][0]
        n.receive_wire(self.wire(b'!'+nonce),source)
        self.assertEqual(n.endpoint4[2],source)
        state=dict(test=0,revision=0,members=[dict(steam='2',ipv6='',port=5678,token=(b'b'*16).hex(),endpoint=['192.0.2.1',1111])])
        n.update(state)
        self.assertEqual(n.endpoint4[2],source)
        n.direct4_at[2]=time.monotonic()-11;n.update(state)
        self.assertEqual(n.endpoint4[2],('192.0.2.1',1111))

    def test_invalid_auth_wrong_source_and_expired_challenge_do_not_promote(self):
        n=self.node;source=('192.0.2.1',2222)
        n.receive_wire(self.wire(b'?12345678',b'wrong'),source)
        self.assertEqual(n.sent,[])
        n.receive_wire(self.wire(b'?12345678'),source);nonce=n.checks4[2][0]
        n.receive_wire(self.wire(b'!'+nonce),('192.0.2.1',3333))
        self.assertEqual(n.endpoint4[2][1],1111)
        n.checks4[2]=(nonce,source,time.monotonic()-4)
        n.receive_wire(self.wire(b'!'+nonce),source)
        self.assertEqual(n.endpoint4[2][1],1111)
