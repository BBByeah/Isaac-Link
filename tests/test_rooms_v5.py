import unittest
from coordinator_v5 import CoordinatorV5

class Rooms(unittest.TestCase):
    def setUp(self):self.server=CoordinatorV5();self.users={}
    def register(self,steam,name):
        r=self.server.handle('/register',dict(steam=steam,ipv6='',port=27667,token='01'*16,protocol=5,player_id=name))
        self.users[steam]=r;return r['code']
    def call(self,user,path,**kw):return self.server.handle(path,{**self.users[user],**kw})
    def test_transfer_host_and_rejoin_preserves_personal_code(self):
        a=self.register(1,'ALPHA');b=self.register(2,'BRAVO');c=self.register(3,'CHARL')
        old=self.call(1,'/add',code=b);self.call(1,'/route',a='1',b='2',route='ipv6')
        moved=self.call(3,'/add',code=a)
        self.assertEqual({m['player_id'] for m in moved['members']},{'ALPHA','CHARL'})
        remaining=self.call(2,'/poll');self.assertEqual(remaining['host'],'2');self.assertEqual(remaining['plan'],{})
        self.assertNotEqual(remaining['epoch'],old['epoch'])
        self.call(1,'/new-room');returned=self.call(1,'/add',code=b)
        self.assertEqual(len(returned['members']),2);self.assertEqual(self.server.sessions[self.users[1]['sid']]['code'],a)
    def test_ids_and_host_only_monitor(self):
        self.register(1,'abcde')
        for name in ('AB12E','ABCD','ABCDEF','中文ABC','ABCDE'):
            with self.assertRaises(ValueError):self.register(2,name)
        b=self.register(2,'FGHIJ');self.call(1,'/add',code=b)
        member=self.call(2,'/poll',telemetry={'edges':{'1':{'gap_p95':34}}})
        self.assertEqual(member['telemetry'],{});self.assertEqual(member['reports'],{})
        self.assertIn('2',self.call(1,'/poll')['telemetry'])
        with self.assertRaises(ValueError):self.call(2,'/settings',monitor=False)
        self.call(1,'/settings',monitor=False)
        self.call(2,'/poll',telemetry={'anything':123})
        self.assertEqual(self.call(1,'/poll')['telemetry'],{})
    def test_kick_and_expiry_do_not_poison_remaining_room(self):
        self.register(1,'ALPHA');b=self.register(2,'BRAVO');self.call(1,'/add',code=b)
        self.call(1,'/kick',steam='2');self.assertEqual(self.call(2,'/poll')['host'],'2')
        self.call(1,'/add',code=b);self.server.remove(self.users[2]['sid'])
        self.assertEqual(self.call(1,'/poll')['error'],'')

if __name__=='__main__':unittest.main()
