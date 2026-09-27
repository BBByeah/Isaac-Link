import unittest
from server.coordinator_v5 import CoordinatorV5
from isaac_link.capture import describe
from isaac_link.multipath import WIRE
from isaac_link.routing import candidates


class LanRooms(unittest.TestCase):
    def setUp(self):
        self.server=CoordinatorV5();self.users={}
        for steam,name in ((1,'ALPHA'),(2,'BRAVO'),(3,'CHARL')):
            self.users[steam]=self.server.handle('/register',dict(steam=steam,ipv6='',port=27667,token='01'*16,protocol=7,player_id=name))
        self.call(1,'/add',code=self.users[2]['code'])
    def call(self,who,path,**kw):return self.server.handle(path,{**self.users[who],**kw})
    def test_host_assignment_sync_route_clear_and_room_lifecycle(self):
        self.call(1,'/lan',steam='1',ip='26.1.2.3')
        self.call(1,'/lan',steam='2',ip='26.4.5.6')
        result=self.call(2,'/poll')
        self.assertEqual([m['lan_ip'] for m in result['members']],['26.1.2.3','26.4.5.6'])
        result=self.call(1,'/route',a='1',b='2',route='lan')
        self.assertEqual(result['plan']['1:2'],'lan')
        with self.assertRaises(ValueError):self.call(1,'/lan',steam='2',ip='')
        self.call(1,'/route',a='1',b='2',route='relay')
        self.call(1,'/lan',steam='2',ip='')
        with self.assertRaises(ValueError):self.call(1,'/route',a='1',b='2',route='lan')
        result=self.call(1,'/kick',steam='2')
        self.assertEqual(result['members'][0]['lan_ip'],'26.1.2.3')
        self.assertEqual(self.call(2,'/poll')['members'][0]['lan_ip'],'')
    def test_permissions_addresses_and_duplicates(self):
        with self.assertRaises(ValueError):self.call(2,'/lan',steam='2',ip='26.2.3.4')
        with self.assertRaises(ValueError):self.call(1,'/lan',steam='3',ip='26.2.3.4')
        for ip in ('invalid','127.0.0.1','0.0.0.0','224.0.0.1','255.255.255.255','::1'):
            with self.assertRaises(ValueError):self.call(1,'/lan',steam='1',ip=ip)
        self.call(1,'/lan',steam='1',ip='26.2.3.4')
        with self.assertRaises(ValueError):self.call(1,'/lan',steam='2',ip='26.2.3.4')
    def test_legacy_client_rejected_and_capture_names(self):
        old=self.server.handle('/register',dict(steam=4,ipv6='',port=27667,token='01'*16,protocol=6,player_id='DELTA'))
        with self.assertRaisesRegex(ValueError,'0.6.5'):self.call(1,'/add',code=old['code'])
        raw=WIRE.pack(b'I6W2',1,2,4)+b'?12345678'+bytes(16)
        self.assertEqual(describe(raw)['route'],'lan')
    def test_optimizer_can_choose_lan(self):
        reports={a:{'links':{b:{'lan':dict(received=20,loss=0,p95=5)}}} for a,b in (('1','2'),('2','1'))}
        self.assertEqual(candidates(['1','2'],reports),[{'1:2':'lan'}])
