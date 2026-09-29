"""Bounded RFC 8489 Binding transactions on the application's UDP socket."""
import ipaddress
import secrets
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor

COOKIE=0x2112A442
DEFAULT_SERVERS=(('stun.cloudflare.com',3478),('stun.l.google.com',19302))

def check_servers(servers):
    """Background diagnostic, separate from the game socket; never expose mapped IPs."""
    def check(server):
        host,port=server
        try:
            targets=socket.getaddrinfo(host,port,socket.AF_INET,socket.SOCK_DGRAM)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.settimeout(2);target=targets[0][4];tid=secrets.token_bytes(12);started=time.monotonic()
                for attempt in range(2):
                    sock.sendto(request(tid),target);deadline=time.monotonic()+2
                    while time.monotonic()<deadline:
                        sock.settimeout(max(.01,deadline-time.monotonic()))
                        try:raw,source=sock.recvfrom(2048)
                        except socket.timeout:break
                        if source==target and parse(raw,tid):return host,port,f'可用 · {(time.monotonic()-started)*1000:.0f} ms'
            return host,port,'未收到响应（当前网络）'
        except OSError:return host,port,'解析或网络连接失败'
    with ThreadPoolExecutor(max_workers=min(8,len(servers))) as pool:return list(pool.map(check,servers))

def parse_servers(text):
    rows=[]
    for line in text.splitlines():
        if not line.strip():continue
        host,separator,port=line.strip().rpartition(':')
        if not separator or not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):raise ValueError('STUN 节点格式应为 域名:端口，每行一个')
        if not port.isdecimal() or not 0<int(port)<65536:raise ValueError('STUN 端口无效')
        if (host,int(port)) not in rows:rows.append((host,int(port)))
    if not 1<=len(rows)<=8:raise ValueError('请设置 1～8 个 STUN 节点')
    return rows

def request(transaction):
    return struct.pack('!HHI12s',1,0,COOKIE,transaction)

def parse(raw, transaction):
    if len(raw)<20:return None
    kind,size,cookie,tid=struct.unpack_from('!HHI12s',raw)
    if kind!=0x101 or cookie!=COOKIE or tid!=transaction or size%4 or len(raw)!=20+size:return None
    offset=20;fallback=None
    while offset+4<=len(raw):
        attr,n=struct.unpack_from('!HH',raw,offset);offset+=4
        value=raw[offset:offset+n]
        if len(value)!=n:return None
        offset+=(n+3)&~3
        if attr in (0x0020,0x0001) and n==8 and value[1]==1:
            port,ip=struct.unpack_from('!HI',value,2)
            if attr==0x0020:port^=COOKIE>>16;ip^=COOKIE
            address=ipaddress.IPv4Address(ip)
            if not port or not address.is_global:return None
            endpoint=(str(address),port)
            if attr==0x0020:return endpoint
            fallback=endpoint
    return fallback

class Discovery:
    def __init__(self, sock, servers=DEFAULT_SERVERS):
        self.sock=sock;self.servers=servers;self.targets=[];self.pending={};self.found={};self.next=0

    def resolve(self):
        targets=[]
        for host,port in self.servers:
            try:
                for row in socket.getaddrinfo(host,port,socket.AF_INET,socket.SOCK_DGRAM):
                    if row[4] not in targets:targets.append(row[4])
            except OSError:pass
        self.targets=targets[:8]

    def tick(self, now):
        self.pending={k:v for k,v in self.pending.items() if now-v[1]<3}
        self.found={k:v for k,v in self.found.items() if now-v<90}
        if now<self.next:return
        self.next=now+20
        for target in self.targets:
            tid=secrets.token_bytes(12)
            try:self.sock.sendto(request(tid),target);self.pending[tid]=(target,now)
            except OSError:pass

    def receive(self,raw,source):
        if len(raw)<20 or raw[4:8]!=struct.pack('!I',COOKIE):return False
        tid=raw[8:20];item=self.pending.get(tid)
        if item and tuple(source[:2])==item[0]:
            endpoint=parse(raw,tid)
            if endpoint:self.found[endpoint]=time.monotonic();self.pending.pop(tid,None)
        return True
