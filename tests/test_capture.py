import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from isaac_link.capture import Capture
from test_v4 import Network,until
from isaac_link.routing import ROUTES

def rows(path):return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines()]

class Tests(unittest.TestCase):
    def test_full_bytes_concurrency_restart(self):
        with tempfile.TemporaryDirectory(prefix='抓包-') as directory:
            c=Capture();path=c.start(directory);payload=bytes(range(256))*4096
            threads=[threading.Thread(target=lambda:[c.record('test',payload,index=i) for i in range(8)]) for _ in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
            c.stop();data=rows(path)
            self.assertEqual(len(data),34);self.assertTrue(data[-1]['complete'])
            self.assertEqual([r['id'] for r in data[1:-1]],list(range(1,33)))
            self.assertTrue(all(base64.b64decode(r['payload_b64'])==payload for r in data[1:-1]))
            next_path=c.start(directory);c.record('empty');c.stop();self.assertNotEqual(path,next_path)

    def test_overflow_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture(limit=1);path=c.start(d);c.record('test',b'abc')
            with self.assertRaises(RuntimeError):c.stop()
            end=rows(path)[-1];self.assertFalse(end['complete']);self.assertEqual(end['dropped'],1)

    def test_disk_failure_and_dead_game_stop(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture();c.start(d);c.file.close();c.record('test',b'abc')
            until(lambda:bool(c.status()['error']))
            with self.assertRaises(RuntimeError):c.stop()
            from isaac_link.runtime_v4 import MultiRuntime
            r=MultiRuntime(lambda x:None);r.start_capture(d)
            class DeadScript:
                def post(self,*args):raise RuntimeError('game has exited')
            r.script=DeadScript();path=r.stop_capture()
            self.assertTrue(rows(path)[-1]['complete'])

    def test_transport_and_retransmission(self):
        with tempfile.TemporaryDirectory() as d:
            n=Network(2);a,b=n.nodes[100],n.nodes[101];c=Capture();a.capture=c;path=c.start(d)
            try:
                until(lambda:all(a.report()['links'].get('101',{}).get(r,{}).get('received',0)>1 for r in ROUTES))
                for route in ROUTES:
                    a.selected[101]=route;b.selected[100]=route
                    a.send(101,7,2,bytes(range(256))*12)
                    until(lambda:len(n.received[101])>=ROUTES.index(route)+1)
                a.selected[101]='ipv4';b.selected[100]='ipv4'
                original=b._wire;drop=[True]
                b._wire=lambda peer,raw:False if drop[0] else original(peer,raw)
                a.send(101,7,2,b'force-ack-loss');time.sleep(.25);drop[0]=False
                until(lambda:not a.pending)
            finally:n.close();c.stop()
            data=rows(path);events={r['event'] for r in data}
            self.assertTrue({'udp_send','udp_receive','steam_enqueue','steam_receive','game_transport_send'}<=events)
            wire=[r for r in data if r.get('decoded',{}).get('packet_type')=='data' and r['event']=='udp_send']
            self.assertTrue(any(r['decoded']['fragments']>1 for r in wire))
            ids=[(r['decoded']['sequence'],r['decoded']['fragment']) for r in wire]
            self.assertLess(len(set(ids)),len(ids),'retransmissions were not captured')
            self.assertTrue(data[-1]['complete'])

if __name__=='__main__':unittest.main(verbosity=2)
