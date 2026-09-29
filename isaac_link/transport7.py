"""Server-optional multipath transport; Steam is only one independent carrier."""
import collections
import hashlib
import hmac
import json
import queue
import secrets
import select
import socket
import struct
import threading
import time
import zlib
from types import SimpleNamespace
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from isaac_link.transport import Transport
from isaac_link.transport_v5 import TransportV5
from isaac_link.multipath import Multipath
from isaac_link.protocol7 import encode, descriptor, bootstrap, read_bootstrap, peer_from, endpoint
from isaac_link.session7 import Session
from isaac_link.stun import Discovery, DEFAULT_SERVERS
from isaac_link.selection import ORDER, PERIOD, WINDOW
from isaac_link.routing import edge
from isaac_link.control import Control

class LocalControl:
    config={'host':'127.0.0.1','udp_port':27667}
    credentials={'sid':'00'*16,'auth':'00'*32}
    def register(self,*args):return ''

class Transport7(TransportV5):
    def __init__(self,steam,name,ip='',port=27667,callback=None,carrier_send=None,event=None,capture=None,server=None,stun_servers=DEFAULT_SERVERS,test=False):
        self.started=threading.Event();self.session=None;self.server_config=server;self.server_status='未配置'
        self.server_ready=False;self.remote_candidates={};self.local_endpoint=None;self.probe_schedule={}
        self.input_metrics={}
        self.measure_window=-1;self.boot_inbox=queue.Queue(128);self.resolved_relay=None
        super().__init__(steam,ip,port,callback,LocalControl(),carrier_send or (lambda *a:False),event,test,capture)
        self.discovery=Discovery(self.sock4,stun_servers)
        self.session=Session(self,name);self.code=self.session.code
        self.redundancy='window4';self.steam_status={}
        self.resolver=threading.Thread(target=self.discovery.resolve,daemon=True);self.resolver.start()
        self.server_worker=threading.Thread(target=self.server_loop,daemon=True);self.server_worker.start()
        self.started.set()

    def reset_room(self):
        self.reset_session();self.remote_candidates.clear();self.server_ready=False

    def suspend(self):
        self.selected.clear();self.pending.clear();self.input_window.clear()

    def sync_members(self,members,room):
        for p in list(self.peers):
            if str(p) not in members:
                self.peers.pop(p,None);self.keys.pop(p,None);self.selected.pop(p,None)
                for key in list(self.pending):
                    if key[0]==p:self.pending.pop(key,None)
        own=members[str(self.local.steam)]
        for sid,d in members.items():
            p=int(sid)
            if p==self.local.steam:continue
            peer=peer_from(d)
            if p not in self.peers:
                Transport.add(self,peer)
                self.keys[p]=hashlib.sha512(self.keys[p]+b'room-v7:'+room.encode()).digest()[:32]
            elif self.peers[p]!=peer:raise ValueError('队友已重启，请重新组队')
            if own.get('lan_ip') and d.get('lan_ip'):self.lan_endpoints[p]=(d['lan_ip'],peer.port)
            else:self.lan_endpoints.pop(p,None)

    def bootstrap_send(self,p,value,token):
        self.carrier_send(p,bootstrap(value,token))

    def carrier_receive(self,p,raw):
        if raw[:3]==b'I7J':
            try:self.boot_inbox.put_nowait((p,raw))
            except queue.Full:self.stats['bootstrap_dropped']+=1
        else:super().carrier_receive(p,raw)

    def send_control(self,p,route,message):
        data=zlib.compress(encode(message))
        if len(data)>1120:raise ValueError('协调消息过大')
        nonce=secrets.token_bytes(12)
        aad=f'{self.session.room}:{self.local.steam}>{p}'.encode('ascii')
        # Config snapshots include bootstrap tokens. Do not expose them on UDP/relay.
        sealed=AESGCM(self.keys[p]).encrypt(nonce,data,aad)
        return self.emit(p,route,b'C'+nonce+sealed)

    def receive_extra(self,p,route,body):
        if body[:1]==b'C':
            try:
                if len(body)<29:return True
                aad=f'{self.session.room}:{p}>{self.local.steam}'.encode('ascii')
                compressed=AESGCM(self.keys[p]).decrypt(body[1:13],body[13:],aad)
                decoder=zlib.decompressobj();raw=decoder.decompress(compressed,16385)
                if len(raw)>16384 or not decoder.eof or decoder.unused_data:return True
                message=json.loads(raw)
                if not isinstance(message,dict):return True
                self.path_last[p,route]=time.monotonic()
                self.session.receive(p,message)
            except (ValueError,TypeError,KeyError,zlib.error,InvalidTag):self.stats['invalid_control']+=1
            return True
        return super().receive_extra(p,route,body)

    def emit(self,p,route,body,endpoint4=None):
        if route not in ORDER:return False
        if body[:1] in (b'D',b'B') and self.session:
            fixed=self.session.game_fixed.get(edge(self.local.steam,p),'auto')
            if fixed!='auto' and route!=fixed:return False
        if route=='relay' and not self.server_ready:return False
        result=super().emit(p,route,body,endpoint4)
        # Preserve the same game envelope/sequence across overlapping paths.
        if body[:1] in (b'D',b'B') and self.session:
            old=self.session.overlap.get(p)
            if old and old[0]!=route and time.monotonic()<old[1] and self.session.game_fixed.get(edge(self.local.steam,p),'auto')=='auto':super().emit(p,old[0],body)
        return result

    def relay_packet(self,magic,payload=b''):
        return super().relay_packet({b'I6H2':b'I7H2',b'I6R2':b'I7R2'}.get(magic,magic),payload)

    def receive_wire(self,raw,source=None,steam=None):
        if self.session and self.session.cancelled and len(raw)>21 and raw[:4]==b'I6W2' and raw[21:22] in (b'D',b'B'):return
        if source and raw[:4]==b'I7E2':
            if source[:2]!=self.relay or len(raw)<37:return
            if hmac.compare_digest(raw[-32:],hmac.digest(self.auth,raw[:-32],'sha512')[:32]):
                try:self.local_endpoint=endpoint(json.loads(raw[4:-32]))
                except (ValueError,TypeError):pass
            return
        if source and self.discovery.receive(raw,source):return
        # Only a challenge-validated IPv4 source may carry control or game data.
        if source and len(raw)>21 and raw[:4]==b'I6W2' and raw[20]==1 and raw[21:22] not in (b'?',b'!'):
            p=struct.unpack_from('!Q',raw,4)[0]
            if self.learned4.get(p)!=tuple(source[:2]):return
        candidate=None;was_alive=False
        if len(raw)>21 and raw[:4]==b'I6W2' and raw[20]<5:
            p=struct.unpack_from('!Q',raw,4)[0]
            route=('ipv6','ipv4','relay','steam','lan')[raw[20]]
            candidate=(p,route);was_alive=time.monotonic()-self.path_last.get(candidate,-1e9)<3
        super().receive_wire(raw,source,steam)
        if candidate and not was_alive and time.monotonic()-self.path_last.get(candidate,-1e9)<3:
            # Discovery attempts before the peer installed its keys are not path loss.
            # Begin a fresh quality window when a path is first established/recovered.
            rtt=self.path_rtt.get(candidate)
            self.samples[candidate].clear()
            if rtt is not None:self.samples[candidate].append(rtt)
            for key in list(self.probes):
                if key[:2]==candidate:del self.probes[key]

    def candidates(self):
        values=list(self.discovery.found)
        if self.server_ready and self.local_endpoint and self.local_endpoint not in values:values.append(self.local_endpoint)
        return [list(v) for v in values[:8]]

    def set_candidates(self,p,values):
        if not isinstance(values,list):return
        parsed=[e for v in values[:8] if (e:=endpoint(v))]
        self.remote_candidates[p]=parsed
        if parsed and p not in self.learned4:self.endpoint4[p]=parsed[0]

    def available(self,p):
        now=time.monotonic()
        return [r for r in ORDER if now-self.path_last.get((p,r),-1e9)<3 and (r!='relay' or self.server_ready)]

    def active(self,p):
        if self.session:
            if self.session.cancelled:return False
            fixed=self.session.game_fixed.get(edge(self.local.steam,p),'auto')
            if fixed!='auto' and self.selected.get(p)!=fixed:return False
        return super().active(p)

    def measurements(self):return Multipath.report(self)['links']

    def public_edges(self):
        result={};measurements=self.measurements()
        for p in self.peers:
            cs=self.session.controls.get(p);gs=self.session.selectors.get(p)
            result[str(p)]=dict(route=self.selected.get(p),control=cs.current if cs else None,active=self.active(p),
                game_mode=gs.fixed if gs else 'auto',control_mode=cs.fixed if cs else 'auto',rtt=self.path_rtt.get((p,self.selected.get(p))),
                links=measurements.get(str(p),{}),available=self.available(p),input_gap=self.input_metrics.get(str(p),{}))
        return result

    def server_loop(self):
        if not self.server_config:return
        ctl=Control(self.server_config);registered_room=None
        while not self.stop.is_set():
            try:
                if not self.session:self.stop.wait(.1);continue
                room=self.session.room
                if not ctl.credentials or registered_room!=room:
                    resolved=(socket.gethostbyname(self.server_config['host']),self.server_config.get('udp_port',27667))
                    r=ctl.call('/v7/register',steam=str(self.local.steam),room=room,protocol=8,access_key=self.server_config.get('access_key',''))
                    if r.get('protocol')!=8:raise ValueError('服务器版本不兼容，需要 0.7.0')
                    ctl.credentials={k:r[k] for k in ('sid','auth')}
                    with self.lock:
                        self.sid=bytes.fromhex(r['sid']);self.auth=bytes.fromhex(r['auth']);self.relay=resolved
                        self.server_ready=True;self.server_status='已连接';registered_room=room
                ctl.call('/v7/alive')
                self.stop.wait(5)
            except Exception as e:
                with self.lock:self.server_ready=False;self.server_status=str(e);self.local_endpoint=None
                ctl.credentials={};self.stop.wait(5)

    def _run(self):
        self.started.wait();heartbeat=0;next_session=0
        while not self.stop.is_set():
            try:
                ready,_,_=select.select(self.sockets,[],[],.02)
                with self.lock:
                    now=time.monotonic()
                    for sock in ready:
                        for _ in range(64):
                            try:raw,source=sock.recvfrom(1600)
                            except (BlockingIOError,ConnectionResetError):break
                            self.record('udp_receive',raw,endpoint=list(source),family=sock.family)
                            self.receive_wire(raw,source)
                    for _ in range(64):
                        try:p,raw=self.boot_inbox.get_nowait()
                        except queue.Empty:break
                        value=read_bootstrap(raw,self.local.token,p)
                        if value:self.session.receive_boot(p,value)
                    for _ in range(128):
                        try:p,raw=self.inbox.get_nowait()
                        except queue.Empty:break
                        self.receive_wire(raw,steam=p)
                    self.discovery.tick(now)
                    if self.server_ready and now>=heartbeat:
                        heartbeat=now+1;self.udp_send(self.sock4,self.relay_packet(b'I6H2'),self.relay,'relay')
                    if self.session.cancelled:self.session.tick(now);continue
                    measure=int(now//PERIOD);testing=now%PERIOD<WINDOW
                    if testing and self.measure_window!=measure:
                        self.samples.clear();self.probes.clear();self.measure_window=measure
                    for p in list(self.peers):
                        for route in ORDER:
                            key=(p,route);interval=.1 if testing else 1
                            if now-self.probe_schedule.get(key,-1e9)<interval:continue
                            self.probe_schedule[key]=now
                            seq=secrets.randbits(64);body=b'?'+struct.pack('!Q',seq)
                            if route=='ipv4':
                                targets=self.remote_candidates.get(p,[])[:]
                                learned=self.learned4.get(p)
                                if learned and learned not in targets:targets.insert(0,learned)
                                sent=False
                                for target in targets:sent=self.emit(p,route,body,endpoint4=target) or sent
                            else:sent=self.emit(p,route,body)
                            if sent:self.probes[p,route,seq]=now
                    for key,began in list(self.probes.items()):
                        if now-began>.8:self.samples[key[:2]].append(None);del self.probes[key]
                    if now>=next_session:self.session.tick(now);next_session=now+.1
                    self.maintenance(now)
                    budget=collections.Counter()
                    for key,item in list(self.pending.items()):
                        p=key[0];rto=max(.08,min(1,self.rtt.get(p,60)/500+.02)) if self.active(p) else 1
                        if now-item[1]>=rto and budget[p]<32:
                            self._wire(p,item[0]);item[1]=now;item[3]+=1;budget[p]+=1;self.stats['retransmits']+=1
                    for key,item in list(self.assemblies.items()):
                        if not key[1] and now-item[0]>2:self.buffered-=item[5];del self.assemblies[key]
            except Exception as e:
                if str(e)!=self.last_error:self.event('网络线程：'+str(e));self.last_error=str(e)
                self.stats['errors']+=1;self.stop.wait(.1)

    def close(self):
        self.started.set();super().close();self.server_worker.join(5)
