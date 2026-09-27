import time
import unittest
from test_v4 import Network,until
from isaac_link.routing import ROUTES,candidates,edge

class Tests(unittest.TestCase):
    def test_manual_full_mesh_lock_and_unlock(self):
        n=Network(4)
        try:
            host=n.nodes[100].control
            state=host.call('/route',a='100',b='101',route='ipv6')
            self.assertFalse(state['plan_complete'])
            for a,b in [(100,102),(100,103),(101,102),(101,103),(102,103)]:host.call('/route',a=str(a),b=str(b),route='ipv4')
            until(lambda:all(x.state.get('plan_complete') and all(x.active(p) for p in x.peers) for x in n.nodes.values()))
            self.assertTrue(all(x.state['test']==0 for x in n.nodes.values()))
            before=n.nodes[100].state['plan'].copy()
            for local,remote in [(100,101),(101,100)]:
                node=n.nodes[local];original=node.emit
                node.emit=lambda peer,route,body,original=original,remote=remote:False if peer==remote and route=='ipv6' else original(peer,route,body)
            n.nodes[100].send(101,0,2,b'held-during-lock')
            time.sleep(6)
            self.assertFalse(n.nodes[100].active(101))
            self.assertTrue(all(x.state['plan']['100:101']=='ipv6' for x in n.nodes.values()))
            self.assertFalse(n.received[101])
            host.call('/route',a='100',b='101',route='auto')
            until(lambda:all(x.state['plan']['100:101']!='ipv6' for x in n.nodes.values()),10)
            until(lambda:any(d==b'held-during-lock' for p,c,d in n.received[101]))
            self.assertTrue(all(v==n.nodes[100].state['plan'][k] for k,v in before.items() if k!='100:101'))
            with self.assertRaises(ValueError):n.nodes[101].control.call('/route',a='100',b='101',route='steam')
            with self.assertRaises(ValueError):host.call('/route',a='100',b='999',route='steam')
            with self.assertRaises(ValueError):host.call('/route',a='100',b='101',route='invalid')
        finally:n.close()

    def test_fixed_candidate_and_test_cancellation(self):
        members=['1','2','3'];reports={p:{'links':{}} for p in members}
        for a in members:
            for b in members:
                if a!=b:reports[a]['links'][b]={r:dict(received=20,loss=0,p95=100 if r=='relay' else 10) for r in ROUTES}
        plans=candidates(members,reports,fixed={'1:2':'relay'})
        self.assertTrue(plans and all(p['1:2']=='relay' for p in plans))
        n=Network(2)
        try:
            h=n.nodes[100].control;h.call('/test')
            result=h.call('/route',a='100',b='101',route='steam')
            self.assertEqual(result['test'],0);self.assertEqual(result['candidates'],[])
            self.assertEqual(result['fixed'],{'100:101':'steam'});self.assertTrue(result['plan_complete'])
        finally:n.close()

if __name__=='__main__':unittest.main(verbosity=2)
