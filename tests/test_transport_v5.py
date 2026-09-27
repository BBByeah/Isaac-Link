import time
import unittest
from unittest.mock import patch
import test_v4
from server.coordinator_v5 import CoordinatorV5
from isaac_link.transport_v5 import TransportV5
from isaac_link.transport import HEADER

class ControlV5(test_v4.LocalControl):
    def register(self,steam,ipv6,port,token):
        name={100:'ALPHA',101:'BRAVO',102:'CHARL',103:'DELTA'}[steam]
        r=self.call('/register',steam=steam,ipv6='',port=port,token=token.hex(),protocol=5,player_id=name)
        self.credentials={k:r[k] for k in ('sid','auth')}
        self.server.sessions[r['sid']]['ipv6']=ipv6
        return r['code']

class TransportTests(unittest.TestCase):
    def test_count_outer_packet_once_and_separate_steam(self):
        import hmac
        from isaac_link.multipath import WIRE
        with self.b.lock:
            inner=self.a._packet(101,3,channel=0,mode=1,seq=900,payload=b'x'*40)
            raw=WIRE.pack(b'I6W2',100,101,0)+b'D'+inner
            raw+=hmac.digest(self.a.keys[101],raw,'sha256')[:16]
            before=self.b.stats['udp_in']
            self.b.receive_wire(raw,source=('::1',self.a.local.port))
            self.assertEqual(self.b.stats['udp_in']-before,1)
            self.b.receive_wire(raw,source=('::1',self.a.local.port))
            self.assertEqual(self.b.stats['udp_in']-before,2)
            self.assertEqual(len(self.net.received[101]),1)
            steam=WIRE.pack(b'I6W2',100,101,3)+b'D'+inner
            steam+=hmac.digest(self.a.keys[101],steam,'sha256')[:16]
            prev_steam=self.b.stats['steam_in']
            self.b.receive_wire(steam,steam=100)
            self.assertEqual(self.b.stats['udp_in']-before,2)
            self.assertEqual(self.b.stats['steam_in']-prev_steam,1)
    def setUp(self):
        self.patches=[patch.object(test_v4,'Coordinator',CoordinatorV5),patch.object(test_v4,'Multipath',TransportV5),patch.object(test_v4,'LocalControl',ControlV5)]
        for p in self.patches:p.start()
        self.net=test_v4.Network(2);self.a=self.net.nodes[100];self.b=self.net.nodes[101]
        self.a.control.call('/route',a='100',b='101',route='ipv6')
        test_v4.until(lambda:self.a.active(101) and self.b.active(100))
    def tearDown(self):
        self.net.close()
        self.assertTrue(all(not n.copy_thread.is_alive() for n in self.net.nodes.values()))
        for p in reversed(self.patches):p.stop()
    def test_four_players_all_six_edges(self):
        n=test_v4.Network(4)
        try:
            nodes=list(n.nodes.values());host=nodes[0]
            for i,a in enumerate(nodes):
                for b in nodes[i+1:]:host.control.call('/route',a=str(a.local.steam),b=str(b.local.steam),route='relay')
            test_v4.until(lambda:all(len(x.peers)==3 and all(x.active(p) for p in x.peers) for x in nodes))
            for x in nodes:
                for peer in x.peers:x.send(peer,0,1,b'z'*40)
            test_v4.until(lambda:all(len(n.received[x.local.steam])==3 for x in nodes))
            time.sleep(.05);self.assertTrue(all(len(n.received[x.local.steam])==3 for x in nodes))
        finally:n.close()
    def test_first_packet_lost_copy_recovers_and_content_repeats_preserved(self):
        self.a.control.call('/settings',redundancy='copy5')
        test_v4.until(lambda:self.a.redundancy=='copy5')
        original=self.a.emit;dropped=set()
        def loss(peer,route,body):
            if body[:1]==b'D' and len(body)==87:
                seq=HEADER.unpack_from(body,1)[5]
                if seq not in dropped:dropped.add(seq);return True
            return original(peer,route,body)
        self.a.emit=loss;started=time.monotonic()
        self.a.send(101,0,1,b'x'*40)
        test_v4.until(lambda:len(self.net.received[101])==1,1)
        self.assertLess(time.monotonic()-started,.2)
        self.a.send(101,0,1,b'x'*40)
        test_v4.until(lambda:len(self.net.received[101])==2,1)
        self.assertEqual(self.a.stats['redundancy_sent'],2)
        self.a.emit=original;self.a.send(101,0,1,b'y'*40)
        test_v4.until(lambda:len(self.net.received[101])==3)
        time.sleep(.05);self.assertEqual(len(self.net.received[101]),3)
    def test_rejoin_rejects_old_packets_and_monitor_off(self):
        old_key=self.a.keys[101]
        old=self.a._packet(101,3,channel=0,mode=1,seq=500,payload=b'old')
        self.a.control.call('/new-room')
        test_v4.until(lambda:not self.a.peers and not self.b.peers)
        self.a.control.call('/add',code=self.b.code)
        self.a.control.call('/route',a='100',b='101',route='ipv6')
        test_v4.until(lambda:self.a.active(101) and self.b.active(100))
        self.assertNotEqual(old_key,self.a.keys[101])
        with self.b.lock:
            source=self.b.peers[100];self.b._receive(old,(source.ip,source.port))
        self.assertEqual(self.net.received[101],[])
        self.a.send(101,0,1,b'new');test_v4.until(lambda:len(self.net.received[101])==1)
        self.a.control.call('/settings',monitor=False)
        test_v4.until(lambda:not self.a.monitor_enabled and not self.b.monitor_enabled)
        self.assertEqual(set(self.b.report()),{'health'})
    def test_copy_limits_do_not_block_original_and_stale_copy_expires(self):
        with self.a.lock:
            self.a.redundancy='copy5';now=time.monotonic()
            self.a.copy_budget[101]=(now,120)
            self.a.send(101,0,1,b'l'*40)
            self.assertEqual(len(self.a.copies),0)
            self.assertEqual(self.a.stats['redundancy_limited'],1)
            self.a.copy_budget.clear()
            raw=self.a._packet(101,3,channel=0,mode=1,seq=900,payload=b'x'*40)
            self.a.copies=[(now+1,i,101,'ipv6',raw) for i in range(256)]
            self.a.send(101,0,1,b'm'*40)
            self.assertEqual(len(self.a.copies),256)
            self.assertEqual(self.a.stats['redundancy_limited'],2)
            self.a.copies=[(now-.1,0,101,'ipv6',raw)]
            self.a.maintenance(now)
            self.assertEqual(self.a.stats['redundancy_expired'],1)
            self.assertEqual(len(self.a.copies),0)
        test_v4.until(lambda:len(self.net.received[101])==2)

if __name__=='__main__':unittest.main()
