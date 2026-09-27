import collections
import copy
import socket
import threading
import time
import unittest
from coordinator_server import Coordinator
from multipath import Multipath
from routing import candidates,choose,edge,ROUTES

def until(fn,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if fn():return
        time.sleep(.02)
    raise AssertionError('condition timed out')

class LocalControl:
    def __init__(self,server,port):self.server=server;self.credentials={};self.config=dict(host='127.0.0.1',udp_port=port)
    def call(self,path,**data):return copy.deepcopy(self.server.handle(path,{**self.credentials,**data}))
    def register(self,steam,ipv6,port,token):
        r=self.call('/register',steam=steam,ipv6='',port=port,token=token.hex())
        self.credentials={k:r[k] for k in ('sid','auth')}
        self.server.sessions[r['sid']]['ipv6']=ipv6
        return r['code']

class Network:
    def __init__(self,count=4):
        self.server=Coordinator();self.stop=threading.Event();self.nodes={};self.received=collections.defaultdict(list)
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.05)
        def relay():
            while not self.stop.is_set():
                try:
                    raw,source=self.sock.recvfrom(1501);out=self.server.udp(raw,source)
                    if out:self.sock.sendto(*out)
                except OSError:pass
        self.thread=threading.Thread(target=relay,daemon=True);self.thread.start()
        for i in range(count):
            steam=100+i;control=LocalControl(self.server,self.sock.getsockname()[1])
            def carrier(peer,raw,source=steam):
                if peer in self.nodes:self.nodes[peer].carrier_receive(source,raw);return True
                return False
            self.nodes[steam]=Multipath(steam,'::1' if i<2 else '',0,lambda p,c,d,s=steam:self.received[s].append((p,c,d)),control,carrier,test=True)
        first=self.nodes[100]
        for n in list(self.nodes.values())[1:]:first.control.call('/add',code=n.code)
        self.poller=threading.Thread(target=self.poll,daemon=True);self.poller.start()
    def poll(self):
        while not self.stop.is_set():
            for n in list(self.nodes.values()):
                state=n.control.call('/poll',report=n.report(),test=n.test_id,enabled=n.enabled)
                n.update(state)
            self.stop.wait(.05)
    def close(self):
        self.stop.set();self.poller.join(2)
        for n in self.nodes.values():n.close()
        self.thread.join(2);self.sock.close()

class Tests(unittest.TestCase):
    def test_optimizer_minimax(self):
        members=['1','2','3'];reports={p:{'links':{}} for p in members}
        for a in members:
            for b in members:
                if a==b:continue
                reports[a]['links'][b]={r:dict(received=20,loss=0,p95=(20 if r=='steam' else 100)) for r in ROUTES}
        plans=candidates(members,reports)
        self.assertTrue(all(x=='steam' for x in plans[0].values()))
        for p in members:reports[p]['rounds']={'0':dict(count=20,p95=30,loss=0),'1':dict(count=20,p95=10 if p!='3' else 80,loss=0)}
        self.assertEqual(choose(plans,members,reports),plans[0])

    def test_relay_auth_membership(self):
        n=Network(2)
        try:
            a=n.nodes[100];until(lambda:n.server.sessions[a.control.credentials['sid']]['endpoint'])
            packet=a.relay_packet(b'I6H2');source=('127.0.0.1',12345)
            endpoint=n.server.sessions[a.control.credentials['sid']]['endpoint'][:]
            self.assertIsNone(n.server.udp(packet[:-1]+bytes([packet[-1]^1]),source))
            self.assertEqual(n.server.sessions[a.control.credentials['sid']]['endpoint'],endpoint)
            with self.assertRaises(ValueError):n.server.handle('/test',{'sid':a.control.credentials['sid'],'auth':'bad'})
            with self.assertRaises(ValueError):n.nodes[101].control.call('/test')
        finally:n.close()

    def test_all_carriers_and_reliable_failover(self):
        n=Network(4)
        try:
            a,b=n.nodes[100],n.nodes[101]
            until(lambda:all(a.report()['links'].get('101',{}).get(r,{}).get('received',0)>1 for r in ROUTES))
            for route in ROUTES:
                a.selected[101]=route;b.selected[100]=route
                for i in range(4):a.send(101,9,2,(route+str(i)).encode()*800)
                until(lambda:len(n.received[101])>=4*(ROUTES.index(route)+1))
            original=a.emit
            a.emit=lambda peer,route,body:False if route=='ipv6' else original(peer,route,body)
            a.selected[101]='ipv6';b.selected[100]='ipv6'
            a.send(101,9,2,b'queued-before-switch')
            a.send(101,9,2,b'queued-second')
            time.sleep(.1);a.selected[101]='ipv4';b.selected[100]='ipv4'
            until(lambda:len(n.received[101])==18)
            self.assertEqual([x[2] for x in n.received[101][-2:]],[b'queued-before-switch',b'queued-second'])
            time.sleep(.3);self.assertEqual(len(n.received[101]),18)
            self.assertFalse(a.errors)
        finally:n.close()

    def test_complete_four_player_selection(self):
        n=Network(4)
        try:
            n.nodes[100].control.call('/test')
            until(lambda:all(x.state.get('plan') for x in n.nodes.values()),35)
            plans=[x.state['plan'] for x in n.nodes.values()]
            self.assertTrue(all(p==plans[0] for p in plans));self.assertEqual(len(plans[0]),6)
            self.assertGreater(n.nodes[100].state['selection']['barrier_p95_ms'],0)
            tested_plans=copy.deepcopy(n.nodes[100].state['candidates'])
            for node in n.nodes.values():
                for peer in node.peers:node.send(peer,0,2,b'four-player')
            until(lambda:all(len(n.received[p])==3 for p in n.nodes))
            self.assertTrue(all(not x.state['error'] for x in n.nodes.values()))
            before=plans[0].copy();key=edge(100,101);blocked=before[key]
            for local,remote in [(100,101),(101,100)]:
                node=n.nodes[local];original=node.emit
                node.emit=lambda peer,route,body,original=original,remote=remote:False if peer==remote and route==blocked else original(peer,route,body)
            n.nodes[100].send(101,0,2,b'held-across-automatic-failover')
            until(lambda:all(x.state.get('plan',{}).get(key)!=blocked for x in n.nodes.values()),12)
            until(lambda:any(d==b'held-across-automatic-failover' for p,c,d in n.received[101]))
            after=n.nodes[100].state['plan']
            self.assertTrue(all(v==after[k] for k,v in before.items() if k!=key))
            self.assertTrue(all(x.state['plan']==after for x in n.nodes.values()))
            self.assertEqual(n.nodes[100].state['candidates'],tested_plans)
        finally:n.close()

if __name__=='__main__':unittest.main(verbosity=2)
