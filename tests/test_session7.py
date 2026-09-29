"""Actual local UDP + simulated Steam carrier; these are NOT live Steam/NAT tests."""
import threading
import time
import unittest
from isaac_link.transport7 import Transport7
from isaac_link.protocol7 import parse_code

def until(fn,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if fn():return
        time.sleep(.03)
    raise AssertionError('condition timed out')

class Rooms(unittest.TestCase):
    def setUp(self):self.nodes={};self.received={};self.block=set();self.logs=[]
    def tearDown(self):
        for t in self.nodes.values():t.close()
    def node(self,sid):
        self.received[sid]=[]
        def carrier(peer,data):
            if len(data)>1200:raise AssertionError('Steam unreliable packet exceeds 1200 bytes')
            if (sid,peer) in self.block:return False
            if peer in self.nodes:self.nodes[peer].carrier_receive(sid,data);return True
            return False
        t=Transport7(sid,'ABCDE',port=0,callback=lambda *a:self.received[sid].append(a),carrier_send=carrier,
                     event=self.logs.append,stun_servers=(),test=True)
        self.nodes[sid]=t;return t
    def join(self,a,b):
        with a.lock:a.session.invite(b.code)
        until(lambda:str(a.local.steam) in b.session.offers)
        with b.lock:b.session.accept(str(a.local.steam))
        until(lambda:b.session.room==a.session.room)
        try:until(lambda:b.local.steam in a.selected and a.local.steam in b.selected)
        except AssertionError as e:
            raise AssertionError(str([(t.local.steam,t.selected,t.session.switches,t.last_error,t.measurements(),t.session.remote) for t in (a,b)])) from e

    def test_server_free_join_switch_and_strict_fixed(self):
        a=self.node(1);b=self.node(2);self.join(a,b)
        self.assertEqual(a.selected[2],'steam');self.assertEqual(b.selected[1],'steam')
        a.send(2,0,2,b'hello');until(lambda:len(self.received[2])==1)
        with a.lock:a.session.route('1','2','ipv4')
        until(lambda:b.session.game_fixed.get('1:2')=='ipv4')
        self.assertFalse(a.active(2));self.assertFalse(b.active(1))
        a.send(2,0,2,b'wait-for-fixed');time.sleep(.2);self.assertEqual(len(self.received[2]),1)
        with a.lock:a.session.all_auto()
        until(lambda:not b.session.game_fixed)
        until(lambda:len(self.received[2])==2)
        self.assertEqual(self.received[2][-1][-1],b'wait-for-fixed')

    def test_lan_survives_steam_and_host_absence(self):
        a=self.node(1);b=self.node(2);c=self.node(3);self.join(a,b);self.join(a,c)
        until(lambda:3 in b.selected and 2 in c.selected)
        # Loopback is allowed by test transport, not by the production LAN editor.
        with a.lock:
            for member in a.session.members.values():member['lan_ip']='127.0.0.1'
            a.session.revision+=1;a.session.install(a.session.config());a.session.broadcast()
        until(lambda:'lan' in b.available(3) and 'lan' in c.available(2))
        with a.lock:a.session.route('2','3','lan')
        until(lambda:b.selected.get(3)=='lan' and c.selected.get(2)=='lan')
        host=a.session.host;self.block.update((x,y) for x in (1,2,3) for y in (1,2,3))
        # Host transport can be stopped without re-electing or destroying other pairs.
        a.close();time.sleep(3.2)
        b.send(3,0,2,b'host-is-offline');until(lambda:len(self.received[3])==1)
        self.assertEqual(b.session.host,host);self.assertEqual(c.session.host,host)
        self.assertEqual(self.received[3][0][-1],b'host-is-offline')

    def test_old_code_rejected_and_room_control_replay_ignored(self):
        with self.assertRaisesRegex(ValueError,'旧版'):parse_code('ISAAC6-abc')
        a=self.node(1);b=self.node(2);self.join(a,b)
        before=b.session.revision
        b.session.receive(1,dict(protocol=8,room='old-room',sender='1',kind='config',data={},id='x'))
        self.assertEqual(b.session.revision,before)

    def test_four_peers_and_lost_switch_confirmation(self):
        import json,zlib
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        a=self.node(1);b=self.node(2);c=self.node(3);d=self.node(4)
        original=b.carrier_send;dropped=[]
        def lossy(p,raw):
            if len(raw)>22 and raw[21:22]==b'C':
                aad=f'{b.session.room}:{b.local.steam}>{p}'.encode('ascii')
                msg=json.loads(zlib.decompress(AESGCM(b.keys[p]).decrypt(raw[22:34],raw[34:-16],aad)))
                if msg.get('kind')=='switch_done' and not dropped:dropped.append(True);return True
            return original(p,raw)
        b.carrier_send=lossy
        self.join(a,b);self.assertTrue(dropped)
        self.join(a,c);self.join(a,d)
        until(lambda:all(len(t.selected)==3 for t in self.nodes.values()))
        self.assertTrue(all(t.session.host=='1' for t in self.nodes.values()))
        a.send(4,0,2,b'four-players');until(lambda:len(self.received[4])==1)
        self.assertEqual(self.received[4][0][-1],b'four-players')

    def test_control_fixed_no_fallback_and_auto_game_does_not_reset_it(self):
        a=self.node(1);b=self.node(2);self.join(a,b)
        with a.lock:a.session.route('1','2','ipv4','control')
        until(lambda:a.session.controls[2].current is None)
        with a.lock:a.session.all_auto()
        self.assertEqual(a.session.control_fixed['1:2'],'ipv4')
        self.assertIsNone(a.session.controls[2].current)
        # An established game stream does not depend on coordination being healthy.
        a.send(2,0,2,b'coordination-is-offline');until(lambda:len(self.received[2])==1)

    def test_team_control_sync_and_new_member_inherits(self):
        a=self.node(1);b=self.node(2);c=self.node(3);self.join(a,b);self.join(a,c)
        with a.lock:
            for member in a.session.members.values():member['lan_ip']='127.0.0.1'
            a.session.revision+=1;a.session.install(a.session.config());a.session.broadcast()
        until(lambda:all('lan' in t.available(p) for t in self.nodes.values() for p in t.peers))
        with a.lock:a.session.set_control_route('lan')
        until(lambda:all(t.session.control_route=='lan' for t in self.nodes.values()))
        until(lambda:all(x.current=='lan' for t in self.nodes.values() for x in t.session.controls.values()))
        with b.lock:
            with self.assertRaisesRegex(ValueError,'房主'):b.session.set_control_route('steam')
        with a.lock:a.session.all_auto()
        self.assertEqual(a.session.control_route,'lan')
        with a.lock:a.session.set_control_route('steam')
        until(lambda:all(t.session.control_route=='steam' for t in self.nodes.values()))
        d=self.node(4);self.join(a,d)
        self.assertEqual(d.session.control_route,'steam')
        self.assertTrue(all(x.fixed=='steam' for x in d.session.controls.values()))

    def test_ipv4_candidate_challenge_and_reliable_switch(self):
        a=self.node(1);b=self.node(2);self.join(a,b)
        for node in (a,b):
            with node.lock:node.discovery.found[('127.0.0.1',node.local.port)]=time.monotonic()
        until(lambda:2 in a.learned4 and 1 in b.learned4)
        with a.lock:a.session.route('1','2','ipv4')
        until(lambda:a.selected.get(2)=='ipv4' and b.selected.get(1)=='ipv4')
        self.block.update(((1,2),(2,1)))
        a.send(2,0,2,b'validated-ipv4');until(lambda:len(self.received[2])==1)
        self.assertEqual(self.received[2][0][-1],b'validated-ipv4')
        self.assertGreater(a.stats['ipv4_endpoint_validated'],0)

if __name__=='__main__':unittest.main()
