"""One reliable message stream per peer, carried over four independently probed paths."""
import collections
import hmac
import queue
import secrets
import select
import socket
import struct
import threading
import time
from isaac_link.transport import Transport, Peer
from isaac_link.routing import ROUTES, edge, percentile

WIRE=struct.Struct('!4sQQB')

class Multipath(Transport):
    def __init__(self,steam,ipv6,port,callback,control,carrier_send,event=None,test=False,capture=None):
        super().__init__(steam,'',0,callback,test,event,start_thread=False)
        self.sock.close();self.control=control;self.carrier_send=carrier_send;self.capture=capture
        self.sockets=[];self.sock4=None;self.sock6=None
        try:
            self.sock4=self.make_socket(socket.AF_INET,('0.0.0.0',port));self.sockets.append(self.sock4)
            port=self.sock4.getsockname()[1]
            if ipv6:
                self.sock6=self.make_socket(socket.AF_INET6,(ipv6,port));self.sockets.append(self.sock6)
            self.local=Peer(int(steam),ipv6,port,secrets.token_bytes(16))
            self.code=control.register(steam,ipv6,port,self.local.token)
        except Exception:
            for s in self.sockets:s.close()
            raise
        self.endpoint4={};self.selected={};self.path_last={};self.path_rtt={}
        self.probes={};self.samples=collections.defaultdict(lambda:collections.deque(maxlen=600))
        self.round_pending={};self.round_results=collections.defaultdict(list)
        self.state={};self.test_id=0;self.state_at=0;self.revision=-1;self.inbox=queue.Queue(2048)
        self.relay=(socket.gethostbyname(control.config['host']),control.config.get('udp_port',27667))
        self.sid=bytes.fromhex(control.credentials['sid']);self.auth=bytes.fromhex(control.credentials['auth'])
        self.last_error='';self.enabled=False;self.receive_route=None
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    @staticmethod
    def make_socket(family,addr):
        s=socket.socket(family,socket.SOCK_DGRAM)
        try:
            if family==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            if hasattr(socket,'SIO_UDP_CONNRESET'):s.ioctl(socket.SIO_UDP_CONNRESET,False)
            s.bind(addr);s.setblocking(False);return s
        except Exception:s.close();raise

    def native(self,peer):return False

    def record(self,event,data=b'',**fields):
        if self.capture:self.capture.record(event,data,**fields)

    def send(self,peer,channel,mode,payload):
        self.record('game_transport_send',payload,peer=str(peer),channel=channel,mode=mode)
        return super().send(peer,channel,mode,payload)

    def _deliver(self,peer,ch,data):
        self.record('game_transport_deliver',data,peer=str(peer),channel=ch)
        return super()._deliver(peer,ch,data)

    def udp_send(self,sock,raw,target,route,peer=None):
        try:
            n=sock.sendto(raw,target)
            self.record('udp_send',raw,route=route,peer=str(peer) if peer is not None else None,endpoint=list(target),success=True,sent_bytes=n)
            return n
        except OSError as e:
            self.record('udp_send',raw,route=route,peer=str(peer) if peer is not None else None,endpoint=list(target),success=False,error=str(e))
            raise

    def active(self,peer):
        return peer not in self.errors and time.monotonic()-self.path_last.get((peer,self.selected.get(peer)),0)<3

    def update(self,state):
        with self.lock:
            if self.test_id!=state['test']:
                self.samples.clear();self.probes.clear();self.round_results.clear();self.round_pending.clear()
                self.test_id=state['test'];self.event('正在测试四种线路，约 30 秒。' if self.test_id else '成员名单已同步。')
            for item in state['members']:
                peer=int(item['steam'])
                if peer==self.local.steam:continue
                self.add(Peer(peer,item['ipv6'],item['port'],bytes.fromhex(item['token'])))
                if item['endpoint']:self.endpoint4[peer]=tuple(item['endpoint'])
            self.state=state;self.state_at=time.monotonic()
            if state['revision']!=self.revision:
                previous=self.selected
                self.selected={}
                for key,route in state['plan'].items():
                    a,b=map(int,key.split(':'))
                    if self.local.steam not in (a,b):continue
                    peer=b if a==self.local.steam else a
                    if previous.get(peer)!=route:self.event(f'{peer} 采用 {route}，可靠数据序号保持连续。')
                    self.selected[peer]=route
                self.revision=state['revision']

    def relay_packet(self,magic,payload=b''):
        header=magic+self.sid
        return header+hmac.digest(self.auth,header+payload,'sha256')+payload

    def emit(self,peer,route,body):
        if peer not in self.keys:return False
        raw=WIRE.pack(b'I6W2',self.local.steam,peer,ROUTES.index(route))+body
        raw+=hmac.digest(self.keys[peer],raw,'sha256')[:16]
        try:
            if route=='steam':
                ok=self.carrier_send(peer,raw);self.record('steam_enqueue',raw,peer=str(peer),success=bool(ok));return ok
            if route=='relay':self.udp_send(self.sock4,self.relay_packet(b'I6R2',struct.pack('!Q',peer)+raw),self.relay,route,peer)
            elif route=='ipv4':
                if peer not in self.endpoint4:return False
                self.udp_send(self.sock4,raw,self.endpoint4[peer],route,peer)
            else:
                p=self.peers[peer]
                if not self.sock6 or not p.ip:return False
                self.udp_send(self.sock6,raw,(p.ip,p.port),route,peer)
            self.stats['udp_out']+=1;return True
        except (OSError,RuntimeError):
            self.stats['wire_errors']+=1;return False

    def _wire(self,peer,data):
        route=self.selected.get(peer)
        return self.emit(peer,route,b'D'+data) if route else False

    def carrier_receive(self,peer,data):
        self.record('steam_receive',data,peer=str(peer),route='steam')
        try:self.inbox.put_nowait((peer,data))
        except queue.Full:
            self.stats['carrier_dropped']+=1;self.record('steam_receive_drop',data,peer=str(peer),reason='inbox_full')

    def receive_wire(self,raw,source=None,steam=None):
        if not WIRE.size+17<=len(raw)<=1450:return
        magic,peer,target,rid=WIRE.unpack_from(raw)
        if magic!=b'I6W2' or target!=self.local.steam or peer not in self.keys or rid>=4:return
        route=ROUTES[rid]
        if steam is not None:
            if peer!=steam or route!='steam':return
        elif route=='steam':return
        elif route=='relay' and source[:2]!=self.relay:return
        elif route=='ipv6' and ':' not in source[0]:return
        elif route=='ipv4' and ':' in source[0]:return
        if not hmac.compare_digest(raw[-16:],hmac.digest(self.keys[peer],raw[:-16],'sha256')[:16]):
            self.stats['rejected']+=1;return
        body=raw[WIRE.size:-16];now=time.monotonic();kind=body[:1]
        self.stats['steam_in' if steam is not None else 'udp_in']+=1
        if kind in (b'?',b'Q'):
            if len(body)<9:return
            self.emit(peer,route,(b'!' if kind==b'?' else b'A')+body[1:9]);return
        if kind==b'!' and len(body)==9:
            seq=struct.unpack('!Q',body[1:])[0];start=self.probes.pop((peer,route,seq),None)
            if start is not None:
                rtt=(now-start)*1000;self.path_last[peer,route]=now;self.path_rtt[peer,route]=rtt
                self.samples[peer,route].append(rtt)
                if route==self.selected.get(peer):self.rtt[peer]=rtt;self.last[peer]=now
            return
        if kind==b'A' and len(body)==9:
            seq=struct.unpack('!Q',body[1:])[0];record=self.round_pending.get(seq)
            if record and record[3].get(peer)==route:
                record[2].discard(peer)
                if not record[2]:self.round_results[record[0]].append((now-record[1])*1000);del self.round_pending[seq]
            return
        if kind==b'D':
            # The end-to-end envelope was authenticated. Reuse the reliable
            # decoder with its expected logical source, independent of carrier.
            p=self.peers[peer];super()._receive(body[1:],(p.ip,p.port),count_wire=False)

    def report(self):
        with self.lock:
            links={};health={};now=time.monotonic()
            for peer in self.peers:
                links[str(peer)]={}
                for route in ROUTES:
                    values=list(self.samples[peer,route]);good=[x for x in values if x is not None]
                    links[str(peer)][route]=dict(received=len(good),sent=len(values),p95=percentile(good),loss=1-len(good)/len(values) if values else 1,rtt=self.path_rtt.get((peer,route)))
                health[str(peer)]=dict(active=self.active(peer),route=self.selected.get(peer),available=[r for r in ROUTES if now-self.path_last.get((peer,r),0)<2])
            rounds={str(k):dict(count=len(v),p95=percentile(v),loss=sum(x>=1000 for x in v)/len(v)) for k,v in self.round_results.items() if v}
            return dict(links=links,rounds=rounds,health=health)

    def snapshot(self):
        with self.lock:
            snap=super().snapshot()
            for p,s in snap['peers'].items():s['route']=self.selected.get(int(p),'testing')
            snap['control_error']=self.last_error
            return snap

    def _run(self):
        heartbeat=probeat=roundat=0
        while not self.stop.is_set():
            try:
                ready,_,_=select.select(self.sockets,[],[],.005)
                with self.lock:
                    for sock in ready:
                        for _ in range(64):
                            try:raw,source=sock.recvfrom(1501)
                            except (BlockingIOError,ConnectionResetError):break
                            self.record('udp_receive',raw,endpoint=list(source),family=sock.family)
                            self.receive_wire(raw,source)
                    for _ in range(128):
                        try:peer,data=self.inbox.get_nowait()
                        except queue.Empty:break
                        self.receive_wire(data,steam=peer)
                    now=time.monotonic()
                    self.maintenance(now)
                    if now>=heartbeat:
                        heartbeat=now+1
                        try:self.udp_send(self.sock4,self.relay_packet(b'I6H2'),self.relay,'relay')
                        except OSError:self.stats['wire_errors']+=1
                    elapsed=self.state.get('elapsed',0)+now-self.state_at
                    testing=bool(self.test_id) and elapsed<29 and not self.state.get('error')
                    if now>=probeat:
                        probeat=now+(.1 if testing else .5)
                        for peer in self.peers:
                            for route in ROUTES:
                                if not self.should_probe(peer,route,testing,now):continue
                                seq=secrets.randbits(64)
                                if self.emit(peer,route,b'?'+struct.pack('!Q',seq)+bytes(192 if testing else self.probe_padding())):
                                    self.probes[peer,route,seq]=now
                    for k,start in list(self.probes.items()):
                        if now-start>.8:self.samples[k[0],k[1]].append(None);del self.probes[k]
                    if testing and 14<=elapsed<26 and now>=roundat:
                        roundat=now+.05;i=int((elapsed-14)//4);phase=elapsed-14-i*4
                        plans=self.state.get('candidates',[])
                        if i<len(plans) and .4<phase<3.3:
                            routes={p:plans[i][edge(self.local.steam,p)] for p in self.peers}
                            seq=secrets.randbits(64);self.round_pending[seq]=[i,now,set(routes),routes]
                            for peer,route in routes.items():self.emit(peer,route,b'Q'+struct.pack('!Q',seq)+bytes(192))
                    for seq,r in list(self.round_pending.items()):
                        if now-r[1]>.8:self.round_results[r[0]].append(1000);del self.round_pending[seq]
                    budget=collections.Counter()
                    for k,pending in list(self.pending.items()):
                        peer=k[0];rto=max(.08,min(1,self.rtt.get(peer,60)/500+.02)) if self.active(peer) else 1
                        if now-pending[1]>=rto and budget[peer]<32:
                            self._wire(peer,pending[0]);pending[1]=now;pending[3]+=1;budget[peer]+=1;self.stats['retransmits']+=1
                    for k,a in list(self.assemblies.items()):
                        if not k[1] and now-a[0]>2:self.buffered-=a[5];del self.assemblies[k]
                    for peer in self.peers:
                        active=self.active(peer)
                        if active!=self.connected.get(peer,False):
                            self.connected[peer]=active
                            if active:
                                if peer in self.ever:self.reconnects[peer]+=1
                                self.ever.add(peer)
                            self.event(f'{peer} '+('线路已连通' if active else '线路中断，正在探测备用线路'))
            except Exception as e:
                if not self.stop.is_set():
                    self.stats['errors']+=1
                    if str(e)!=self.last_error:self.last_error=str(e);self.event('网络线程：'+str(e))
                    self.stop.wait(.1)

    def maintenance(self,now):pass
    def should_probe(self,peer,route,testing,now):return True
    def probe_padding(self):return 192

    def close(self):
        self.stop.set();self.thread.join(2)
        for s in self.sockets:s.close()
