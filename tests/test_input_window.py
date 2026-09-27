import struct
import time
import unittest
from unittest.mock import patch
import test_v4
from server.coordinator_v5 import CoordinatorV5
from isaac_link.transport_v5 import TransportV5

def frame(n):
    p=bytearray(40);struct.pack_into('<I',p,0,n+100)
    p[4:8]=b'\x01\x01\x00\x01';struct.pack_into('<I',p,24,n)
    return bytes(p)

class Control6(test_v4.LocalControl):
    def register(self,steam,ipv6,port,token):
        r=self.call('/register',steam=steam,ipv6='',port=port,token=token.hex(),protocol=7,player_id={100:'ALPHA',101:'BRAVO'}[steam])
        self.credentials={k:r[k] for k in ('sid','auth')}
        self.server.sessions[r['sid']]['ipv6']=ipv6
        return r['code']

class Windows(unittest.TestCase):
    def setUp(self):
        self.patches=[patch.object(test_v4,'Coordinator',CoordinatorV5),patch.object(test_v4,'Multipath',TransportV5),patch.object(test_v4,'LocalControl',Control6)]
        for p in self.patches:p.start()
        self.net=test_v4.Network(2);self.a=self.net.nodes[100];self.b=self.net.nodes[101]
        self.a.control.call('/route',a='100',b='101',route='ipv6')
        test_v4.until(lambda:self.a.active(101) and self.b.active(100))
        self.assertEqual(self.a.redundancy,'window4')

    def tearDown(self):
        self.net.close()
        for p in reversed(self.patches):p.stop()

    def test_three_losses_recovered_by_fourth_no_wait_and_reordering(self):
        saved=[];original=self.a.emit
        def hold(peer,route,body):
            if body[:1]==b'B':saved.append(body);return True
            return original(peer,route,body)
        with self.a.lock:
            self.a.emit=hold
            for i in range(1,5):self.a.send(101,0,1,frame(i))
            self.assertEqual(len(saved),4)
            self.assertEqual([b[1] for b in saved],[1,2,3,4])
            self.assertEqual(len(saved[-1])+37,231)
            self.a.input_window.rescue.clear()
            original(101,'ipv6',saved[-1])
        test_v4.until(lambda:len(self.net.received[101])==4)
        self.assertEqual([r[2] for r in self.net.received[101]],[frame(i) for i in range(1,5)])
        original(101,'ipv6',saved[1]);original(101,'ipv6',saved[-1])
        time.sleep(.06);self.assertEqual(len(self.net.received[101]),4)

    def test_idle_last_input_rescue(self):
        original=self.a.emit;count=0
        def lose(peer,route,body):
            nonlocal count
            if body[:1]==b'B':
                count+=1
                if count==1:return True
            return original(peer,route,body)
        self.a.emit=lose;start=time.monotonic();self.a.send(101,0,1,frame(1))
        test_v4.until(lambda:len(self.net.received[101])==1,.5)
        self.assertLess(time.monotonic()-start,.25)
        time.sleep(.3);self.assertEqual(count,4);self.assertEqual(len(self.net.received[101]),1)

    def test_continuous_inputs_do_not_add_separate_copies(self):
        saved=[];original=self.a.emit;began=time.monotonic()
        def hold(peer,route,body):
            if body[:1]==b'B':saved.append(body);return True
            return original(peer,route,body)
        with self.a.lock:
            self.a.emit=hold
            for i in range(30):
                now=began+i/30
                with patch('isaac_link.input_window.time.monotonic',return_value=now):
                    self.a.send(101,0,1,frame(i))
                    self.a.maintenance(now+.032)
            self.assertEqual(len(saved),30)
            self.assertEqual(self.a.stats['window_rescue'],0)
            self.a.input_window.rescue.clear()

    def test_game_retransmission_preserved_and_window_distinct(self):
        for i in (1,2,2,3,4):self.a.send(101,0,1,frame(i))
        test_v4.until(lambda:len(self.net.received[101])==5)
        self.assertEqual(len(self.a.input_window.history[101]),4)
        self.assertEqual([r[2] for r in self.net.received[101]].count(frame(2)),2)

    def test_malformed_bundle_is_atomic_and_valid_traffic_keeps_alive(self):
        from isaac_link.input_window import ENTRY
        with self.b.lock:
            self.b.path_last[100,'ipv6']=time.monotonic()-10
            invalid=b'B\x02'+ENTRY.pack(100,frame(1))+ENTRY.pack(101,b'X'*40)
            self.b.receive_extra(100,'ipv6',invalid)
            self.assertFalse(self.b.active(100));self.assertEqual(self.net.received[101],[])
            self.b.receive_extra(100,'ipv6',b'B\x01'+ENTRY.pack(102,frame(2)))
            self.assertTrue(self.b.active(100));self.assertEqual(len(self.net.received[101]),1)

    def test_bundle_all_four_carriers_and_session_reset(self):
        self.a.control.call('/lan',steam='100',ip='26.1.2.3')
        self.a.control.call('/lan',steam='101',ip='26.4.5.6')
        for i,route in enumerate(('ipv6','ipv4','relay','steam','lan')):
            self.a.control.call('/route',a='100',b='101',route=route)
            test_v4.until(lambda:self.a.selected.get(101)==route and self.a.active(101))
            self.a.send(101,0,1,frame(i+1))
            test_v4.until(lambda:len(self.net.received[101])==i+1)
        self.a.control.call('/new-room')
        test_v4.until(lambda:not self.a.peers)
        self.assertFalse(self.a.input_window.history);self.assertFalse(self.a.input_window.rescue)

    def test_legacy_client_cannot_join_window_room(self):
        s=self.net.server
        old=s.handle('/register',dict(steam=999,ipv6='',port=12345,token='01'*16,protocol=5,player_id='OLDER'))
        with self.assertRaisesRegex(ValueError,'0.6.5'):
            self.a.control.call('/add',code=old['code'])

if __name__=='__main__':unittest.main()
