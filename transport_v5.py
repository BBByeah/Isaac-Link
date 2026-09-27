"""Room-isolated transport with bounded, non-blocking input redundancy."""
import collections
import hashlib
import heapq
import queue
import threading
import time
from multipath import Multipath
from transport import HEADER

class TransportV5(Multipath):
    def __init__(self,*args,**kw):
        self.epoch=None;self.monitor_enabled=True;self.redundancy='off'
        self.copies=[];self.copy_order=0;self.probe_times={};self.copy_budget={}
        self.copy_wake=threading.Event()
        super().__init__(*args,**kw)
        self.copy_thread=threading.Thread(target=self.copy_loop,daemon=True);self.copy_thread.start()

    def update(self,state):
        with self.lock:
            epoch=state.get('epoch')
            if epoch!=self.epoch:
                self.reset_session();self.epoch=epoch
            self.monitor_enabled=state.get('monitor',True)
            redundancy=state.get('redundancy','off')
            if redundancy!=self.redundancy:self.copies.clear();self.redundancy=redundancy
            super().update(state)

    def reset_session(self):
        # All peers receive the same new epoch on membership changes. Discard
        # queues before deriving fresh keys; delayed old-room datagrams fail HMAC.
        for name in ('peers','keys','pings','last','rtt','errors','seq','expected','pending','assemblies','ready','seen',
                     'connected','reconnects','peer_stats','network_errors','next_retry','endpoint4','selected','path_last',
                     'path_rtt','probes','samples','round_pending','round_results','probe_times','copy_budget'):
            getattr(self,name).clear()
        self.copies.clear();self.ever.clear();self.buffered=0;self.revision=-1;self.test_id=0
        while True:
            try:self.inbox.get_nowait()
            except queue.Empty:break

    def add(self,peer):
        super().add(peer)
        if self.epoch:
            self.keys[peer.steam]=hashlib.sha256(self.keys[peer.steam]+b'room-v5:'+self.epoch.encode('ascii')).digest()

    def _wire(self,peer,data):
        sent=super()._wire(peer,data)
        if not sent or self.redundancy not in ('copy5','copy10'):return sent
        if len(data)!=HEADER.size+16+40:return sent
        _,kind,_,channel,mode,seq,index,count=HEADER.unpack_from(data)
        if kind!=3 or channel!=0 or mode!=1 or count!=1:return sent
        now=time.monotonic();began,used=self.copy_budget.get(peer,(now,0))
        if now-began>=1:began,used=now,0
        if used>=120 or len(self.copies)>=256:
            self.stats['redundancy_limited']+=1;return sent
        self.copy_budget[peer]=(began,used+1);self.copy_order+=1
        delay=.005 if self.redundancy=='copy5' else .010
        heapq.heappush(self.copies,(now+delay,self.copy_order,peer,self.selected.get(peer),data))
        self.copy_wake.set()
        return sent

    def copy_loop(self):
        while not self.stop.is_set():
            with self.lock:
                delay=max(0,self.copies[0][0]-time.monotonic()) if self.copies else None
            if delay is None:
                self.copy_wake.wait(.2);self.copy_wake.clear();continue
            # Bundled CPython 3.13 uses a high-resolution waitable timer on
            # Windows for sleep. Do not depend on select's ~15.6ms timeout tick.
            if delay:time.sleep(min(delay,.05))
            with self.lock:self.maintenance(time.monotonic())

    def maintenance(self,now):
        for _ in range(32):
            if not self.copies or self.copies[0][0]>now:break
            due,_,peer,route,data=heapq.heappop(self.copies)
            # Do not release a stale burst after a suspended process or reroute.
            if now-due>.05 or route!=self.selected.get(peer) or not self.active(peer):
                self.stats['redundancy_expired']+=1;continue
            if self.emit(peer,route,b'D'+data):self.stats['redundancy_sent']+=1

    def should_probe(self,peer,route,testing,now):
        if testing:return True
        interval=1 if route==self.selected.get(peer) else 3
        if not self.selected.get(peer):interval=.5
        key=(peer,route)
        if now-self.probe_times.get(key,-10)<interval:return False
        self.probe_times[key]=now;return True

    def probe_padding(self):return 0

    def report(self):
        # Health is necessary for reconnect. Histograms and rankings are extra
        # monitoring traffic except during explicit route optimization.
        testing=bool(self.test_id) and not self.state.get('selection') and not self.state.get('error')
        if not self.monitor_enabled and not testing:
            with self.lock:
                now=time.monotonic()
                return {'health':{str(peer):dict(active=self.active(peer),route=self.selected.get(peer),
                        available=[r for (p,r),at in self.path_last.items() if p==peer and now-at<2]) for peer in self.peers}}
        return super().report()

    def close(self):
        self.stop.set();self.copy_wake.set();self.copy_thread.join(1)
        super().close()
