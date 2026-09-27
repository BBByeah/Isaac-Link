"""Paired IPv6-only game transport. All queue state is protected by one lock."""
import base64
import collections
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import struct
import threading
import time

HEADER=struct.Struct('!4sBQiBQHH')
PING,PONG,DATA,ACK=1,2,3,4
CHUNK=1100
MAX_MESSAGE=1024*1024

def address(value, test=False):
    ip=ipaddress.IPv6Address(value.strip().strip('[]'))
    if ip.ipv4_mapped or ip.scope_id or (not ip.is_global and not (test and ip.is_loopback)):
        raise ValueError('请选择当前网卡的公网 IPv6，不能使用 IPv4、映射地址或链路本地地址。')
    return str(ip)

@dataclass(frozen=True)
class Peer:
    steam: int
    ip: str
    port: int
    token: bytes

    def code(self):
        data=json.dumps([str(self.steam),self.ip,self.port,self.token.hex()],separators=(',',':')).encode()
        return ('ISAAC6-' if self.ip else 'ISAACN-')+base64.urlsafe_b64encode(data).decode().rstrip('=')

    @classmethod
    def parse(cls,code,test=False):
        try:
            code=''.join(code.split())
            if not code.startswith(('ISAAC6-','ISAACN-')) or len(code)>512: raise ValueError()
            tail=code[7:]; steam,ip,port,token=json.loads(base64.b64decode(tail+'='*(-len(tail)%4),altchars=b'-_',validate=True))
            token=bytes.fromhex(token)
            if not 0<int(steam)<2**64 or type(port)!=int or not 1<=port<=65535 or len(token)!=16: raise ValueError()
            if code.startswith('ISAACN-'):
                if ip!='':raise ValueError()
                return cls(int(steam),'',port,token)
            return cls(int(steam),address(ip,test),port,token)
        except Exception as e: raise ValueError('连接码无效，请复制对方本次启动生成的完整连接码。') from e

class Transport:
    def __init__(self,steam,ip,port=27667,callback=None,test=False,event=None,start_thread=True):
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.callback=callback or (lambda *args:None)
        self.event=event or (lambda message:None)
        self.connected={}; self.ever=set(); self.reconnects=collections.Counter()
        self.peer_stats=collections.defaultdict(collections.Counter)
        self.network_errors={}; self.next_retry={}; self.repair_at=0
        self.peers={}; self.keys={}; self.pings={}; self.last={}; self.rtt={}; self.errors={}
        self.seq=collections.defaultdict(int); self.expected=collections.defaultdict(lambda:1)
        self.pending={}; self.assemblies={}; self.ready=collections.defaultdict(dict)
        self.seen=collections.OrderedDict(); self.buffered=0
        self.stats=collections.Counter(); self.test=test
        self.sock=socket.socket(socket.AF_INET6 if ip else socket.AF_INET,socket.SOCK_DGRAM)
        try:
            if ip:self.sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'): self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            if hasattr(socket,'SIO_UDP_CONNRESET'): self.sock.ioctl(socket.SIO_UDP_CONNRESET,False)
            self.sock.bind((address(ip,test),int(port)) if ip else ('127.0.0.1',0))
            self.sock.settimeout(.015)
        except Exception: self.sock.close(); raise
        self.local=Peer(int(steam),address(ip,test) if ip else '',self.sock.getsockname()[1],secrets.token_bytes(16))
        self.thread=threading.Thread(target=self._run,daemon=True)
        if start_thread:self.thread.start()

    def add(self,peer):
        if peer.steam==self.local.steam: raise ValueError('不能添加自己的连接码。')
        if peer.ip:address(peer.ip,self.test)
        with self.lock:
            if peer.steam not in self.peers and len(self.peers)>=3: raise ValueError('最多四人：本机之外最多添加三位队友。')
            if peer.steam in self.peers and self.peers[peer.steam]!=peer: raise ValueError('对方已更换会话，请双方停止连接后重新交换连接码。')
            self.peers[peer.steam]=peer
            ordered=sorted((self.local,peer),key=lambda p:p.steam)
            self.keys[peer.steam]=hashlib.sha256(b'ISAAC6-v1'+b''.join(p.token for p in ordered)).digest()

    def active(self,peer):
        return peer in self.peers and peer not in self.errors and time.monotonic()-self.last.get(peer,0)<4

    def native(self,peer):
        return not self.local.ip or not self.peers[peer].ip

    def _packet(self,peer,kind,channel=0,mode=0,seq=0,index=0,count=1,payload=b''):
        raw=HEADER.pack(b'I6D1',kind,self.local.steam,channel,mode,seq,index,count)+payload
        return raw+hmac.digest(self.keys[peer],raw,'sha256')[:16]

    def _wire(self,peer,data):
        if self.native(peer):return False
        p=self.peers[peer]
        try:
            self.sock.sendto(data,(p.ip,p.port))
            self.stats['udp_out']+=1
            return True
        except OSError as e:
            if self.stop.is_set():return False
            error=str(e)
            if self.network_errors.get(peer)!=error:self.event(f'{peer} 网络发送失败，继续自动重试：{error}')
            self.network_errors[peer]=error;self.stats['socket_errors']+=1
            self.last.pop(peer,None)
            if getattr(e,'winerror',None) in (10038,10049,10050):self.repair_at=self.repair_at or time.monotonic()+2
            return False

    def send(self,peer,channel,mode,payload):
        with self.lock:
            if peer not in self.peers or peer in self.errors: raise ConnectionError('对端未配置或会话错误。')
            if not self.active(peer) and mode<2: raise ConnectionError('断线期间丢弃实时包，等待自动重连。')
            if mode not in (0,1,2,3) or len(payload)>MAX_MESSAGE: raise ValueError('游戏包超出限制。')
            reliable=mode>=2
            count=max(1,(len(payload)+CHUNK-1)//CHUNK)
            if sum(k[0]==peer for k in self.pending)+count>8192: raise BufferError('该队友的可靠发送队列已满。')
            k=(peer,reliable); self.seq[k]+=1; seq=self.seq[k]; now=time.monotonic()
            for index in range(count):
                raw=self._packet(peer,DATA,channel,mode,seq,index,count,payload[index*CHUNK:(index+1)*CHUNK])
                if reliable: self.pending[(peer,seq,index)]=[raw,now,now,1]
                self._wire(peer,raw)
            self.stats['game_out']+=1; self.stats['bytes_out']+=len(payload)
            self.peer_stats[peer]['game_out']+=1;self.peer_stats[peer]['bytes_out']+=len(payload)

    def _receive(self,raw,source,*,count_wire=True):
        if len(raw)<HEADER.size+16 or len(raw)>HEADER.size+CHUNK+16: return
        magic,kind,peer,channel,mode,seq,index,count=HEADER.unpack_from(raw)
        p=self.peers.get(peer)
        if magic!=b'I6D1' or not p or source[0]!=p.ip or source[1]!=p.port: return
        if not hmac.compare_digest(raw[-16:],hmac.digest(self.keys[peer],raw[:-16],'sha256')[:16]):
            self.stats['rejected']+=1; return
        if count_wire:self.stats['udp_in']+=1
        now=time.monotonic(); payload=raw[HEADER.size:-16]
        if kind==PING:
            self._wire(peer,self._packet(peer,PONG,seq=seq)); return
        if kind==PONG:
            began=self.pings.pop((peer,seq),None)
            if began is not None:
                self.last[peer]=now; self.rtt[peer]=(now-began)*1000
                self.network_errors.pop(peer,None)
            return
        if kind==ACK:
            self.pending.pop((peer,seq,index),None); return
        if kind!=DATA or mode not in (0,1,2,3) or not 0<=index<count<=(MAX_MESSAGE+CHUNK-1)//CHUNK: return
        reliable=mode>=2; key=(peer,reliable,seq)
        # A completed reliable message remains represented by expected/ready;
        # stale retransmissions can be ACKed without recreating assemblies.
        if reliable and (seq<self.expected[peer] or seq in self.ready[peer]):
            self._wire(peer,self._packet(peer,ACK,seq=seq,index=index)); return
        if not reliable and key in self.seen: return
        if reliable and seq>self.expected[peer]+1024: return
        a=self.assemblies.get(key)
        if a is None:
            if len(self.assemblies)>=512: return
            a=[now,count,channel,mode,{},0]; self.assemblies[key]=a
        if a[1:4]!=[count,channel,mode]: return
        if index not in a[4]:
            if self.buffered+len(payload)>16*1024*1024 or a[5]+len(payload)>MAX_MESSAGE: return
            a[4][index]=payload; a[5]+=len(payload); self.buffered+=len(payload)
        if reliable: self._wire(peer,self._packet(peer,ACK,seq=seq,index=index))
        if len(a[4])!=count: return
        data=b''.join(a[4][i] for i in range(count)); del self.assemblies[key]
        if reliable:
            self.ready[peer][seq]=(channel,data)
            while self.expected[peer] in self.ready[peer]:
                ch,data=self.ready[peer].pop(self.expected[peer]); self.expected[peer]+=1
                self.buffered-=len(data); self._deliver(peer,ch,data)
        else:
            self.buffered-=len(data); self.seen[key]=now
            while len(self.seen)>4096: self.seen.popitem(last=False)
            self._deliver(peer,channel,data)

    def _deliver(self,peer,ch,data):
        self.stats['game_in']+=1; self.stats['bytes_in']+=len(data)
        self.peer_stats[peer]['game_in']+=1;self.peer_stats[peer]['bytes_in']+=len(data)
        self.callback(peer,ch,data)

    def snapshot(self):
        with self.lock:
            return {'time':time.strftime('%Y-%m-%d %H:%M:%S'),'family':'mixed','stats':dict(self.stats),'peers':{
                str(p):{'active':self.active(p),'rtt_ms':round(self.rtt.get(p,0),2),
                        'route':'steam' if self.native(p) else 'ipv6',
                        'queued':sum(1 for k in self.pending if k[0]==p),'error':self.errors.get(p,''),
                        'network_error':self.network_errors.get(p,''),'reconnects':self.reconnects[p],
                        'state':'connected' if self.active(p) else ('reconnecting' if p in self.ever else 'connecting'),
                        'stats':dict(self.peer_stats[p])}
                for p in self.peers}}

    def _run(self):
        next_ping=0
        while not self.stop.is_set():
            try:
                try: raw,source=self.sock.recvfrom(1500)
                except socket.timeout: raw=None
                except OSError as e:
                    if self.stop.is_set(): break
                    if getattr(e,'winerror',None)==10054: continue
                    raise
                with self.lock:
                    if raw: self._receive(raw,source)
                    now=time.monotonic()
                    if now>=next_ping:
                        next_ping=now+.5
                        for peer in self.peers:
                            if self.native(peer):continue
                            seq=secrets.randbits(64); self.pings[(peer,seq)]=now
                            self._wire(peer,self._packet(peer,PING,seq=seq))
                    for key,ts in list(self.pings.items()):
                        if now-ts>4: del self.pings[key]
                    retry_budget=collections.Counter()
                    for key,pending in list(self.pending.items()):
                        peer=key[0]
                        rto=max(.08,min(1,self.rtt.get(peer,60)/500+.02)) if self.active(peer) else 2
                        if now-pending[1]>=rto and retry_budget[peer]<32:
                            self._wire(peer,pending[0]); pending[1]=now; pending[3]+=1; self.stats['retransmits']+=1
                            retry_budget[peer]+=1
                    for key,a in list(self.assemblies.items()):
                        if not key[1] and now-a[0]>2:
                            self.buffered-=a[5]; del self.assemblies[key]
                    for peer in self.peers:
                        if self.native(peer):continue
                        active=self.active(peer)
                        if active!=self.connected.get(peer,False):
                            self.connected[peer]=active
                            if active:
                                if peer in self.ever:self.reconnects[peer]+=1
                                self.ever.add(peer)
                                self.event(f'{peer} IPv6 已连接；自动恢复次数 {self.reconnects[peer]}')
                            else:self.event(f'{peer} 连接中断，正在自动重连；可靠包保留等待补发。')
                    if self.repair_at and now>=self.repair_at:
                        self.repair_at=now+2
                        self.sock.close()
                        sock=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
                        try:
                            sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                            if hasattr(socket,'SIO_UDP_CONNRESET'):sock.ioctl(socket.SIO_UDP_CONNRESET,False)
                            sock.bind((self.local.ip,self.local.port));sock.settimeout(.015)
                            self.sock=sock;self.repair_at=0;self.event('IPv6 套接字已重建，继续握手。')
                        except OSError:sock.close()
            except Exception as e:
                with self.lock:
                    self.stats['errors']+=1
                    if isinstance(e,OSError):
                        # Re-enter maintenance even if recv fails on the old socket.
                        for peer in self.peers:self.last.pop(peer,None)
                        try:self.sock.close()
                        except OSError:pass
                        try:
                            self.sock=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
                            self.sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                            if hasattr(socket,'SIO_UDP_CONNRESET'):self.sock.ioctl(socket.SIO_UDP_CONNRESET,False)
                            self.sock.bind((self.local.ip,self.local.port));self.sock.settimeout(.015)
                        except OSError:pass
                    else:
                        for peer in self.peers:self.errors[peer]=str(e)
                if not self.stop.wait(.1): continue

    def close(self):
        self.stop.set(); self.sock.close(); self.thread.join(timeout=2)
