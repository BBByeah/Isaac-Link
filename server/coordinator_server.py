"""Room coordination over pinned TLS; authenticated UDP rendezvous/relay. No dependencies."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from isaac_link.routing import candidates, choose, ROUTES, edge

class CoordinatorHTTPServer(ThreadingHTTPServer):
    """Keep slow TLS handshakes off the accept loop, with bounded workers."""
    daemon_threads=True
    request_queue_size=64

    def __init__(self,address,handler,context,connection_timeout=5,max_connections=64):
        self.context=context;self.connection_timeout=connection_timeout
        self.slots=threading.BoundedSemaphore(max_connections)
        super().__init__(address,handler)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:
            self.slots.release();raise

    def process_request_thread(self,request,address):
        try:
            request.settimeout(self.connection_timeout)
            request=self.context.wrap_socket(request,server_side=True,do_handshake_on_connect=False)
            request.do_handshake()
            self.finish_request(request,address)
        except (OSError,ssl.SSLError):pass
        except Exception:self.handle_error(request,address)
        finally:
            self.shutdown_request(request);self.slots.release()

class Coordinator:
    def __init__(self):
        self.lock=threading.RLock();self.sessions={};self.codes={};self.rooms={}

    def auth(self, data):
        s=self.sessions.get(data.get('sid',''))
        if not s or not hmac.compare_digest(s['auth'],data.get('auth','')):raise ValueError('会话过期，请重新启动助手。')
        s['seen']=time.monotonic();return s

    def room(self,s):return self.rooms[s['room']]

    def advance(self,r):
        if not r['test'] or r['selection'] or r['error']:return
        elapsed=time.monotonic()-r['test']
        if elapsed>=13 and not r['candidates']:
            r['candidates']=candidates(list(r['members']),r['reports'],fixed=r['fixed'])
            if not r['candidates']:r['error']='至少一对玩家没有双向可用线路，请查看连接图后重新测试。'
        if elapsed>=29 and r['candidates']:
            best=choose(r['candidates'],list(r['members']),r['reports'])
            if best:
                r['plan']=dict(best);r['revision']+=1
                index=r['candidates'].index(best)
                measurements=[r['reports'][p]['rounds'][str(index)] for p in r['members']]
                r['selection']=dict(index=index,barrier_p95_ms=max(x['p95'] for x in measurements),loss=max(x['loss'] for x in measurements))
                r['switch_at']={key:time.monotonic() for key in best}
            else:r['error']='组合测试未收齐或丢包过高，没有启用接管；请重新测试。'

    def handle(self,path,d):
        with self.lock:
            now=time.monotonic()
            if path=='/register':
                # Registration is bounded and expires; no credential or account persistence.
                if len(self.sessions)>=512:raise ValueError('服务器会话数已满，请稍后再试。')
                steam=str(int(d['steam']))
                if not 0<int(steam)<2**64:raise ValueError('SteamID 无效')
                ip=d.get('ipv6','')
                if ip and (not ipaddress.ip_address(ip).is_global or ':' not in ip):raise ValueError('IPv6 地址无效')
                port=int(d['port'])
                if not 1<=port<=65535:raise ValueError('端口无效')
                token=bytes.fromhex(d['token'])
                if len(token)!=16:raise ValueError('会话标识无效')
                sid=secrets.token_hex(16);code='ISAAC4-'+secrets.token_urlsafe(24);room=secrets.token_hex(12)
                s=dict(sid=sid,auth=secrets.token_hex(32),steam=steam,ipv6=ip,port=port,token=token.hex(),code=code,room=room,seen=now,endpoint=None,budget=0,budget_at=now,enabled=False)
                self.sessions[sid]=s;self.codes[code]=sid
                self.rooms[room]=dict(host=steam,members={steam:sid},reports={},test=0,candidates=[],plan={},revision=0,error='',switch_at={},selection={},fixed={})
                return dict(sid=sid,auth=s['auth'],code=code)
            s=self.auth(d);r=self.room(s)
            if path=='/add':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以添加成员。')
                if r['test'] or r['plan']:raise ValueError('选路开始后不能修改队伍，请重启助手组队。')
                sid=self.codes.get(d.get('code',''));other=self.sessions.get(sid)
                if not other or now-other['seen']>30:raise ValueError('连接码不存在或对方不在线。')
                if other['steam'] in r['members']:raise ValueError('该成员已经在队伍内。')
                old=self.room(other)
                if len(old['members'])!=1 or old['test']:raise ValueError('对方已加入其他队伍。')
                if len(r['members'])>=4:raise ValueError('最多四人。')
                self.rooms.pop(other['room']);other['room']=s['room'];r['members'][other['steam']]=sid
            elif path=='/test':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以开始测试。')
                if len(r['members'])<2:raise ValueError('先添加至少一位队友。')
                if any(self.sessions[x]['enabled'] for x in r['members'].values()):raise ValueError('已接管游戏，重新选路前请退出房间并重启助手。')
                r.update(test=now,reports={},candidates=[],plan=dict(r['fixed']),error='',selection={});r['revision']+=1
            elif path=='/route':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以指定线路。')
                a,b=str(d.get('a','')),str(d.get('b',''));route=d.get('route')
                if a==b or a not in r['members'] or b not in r['members']:raise ValueError('请选择队伍中两位不同玩家。')
                if route not in (*ROUTES,'auto'):raise ValueError('线路类型无效。')
                if r['error'].startswith('成员离线'):raise ValueError(r['error'])
                key=edge(a,b)
                # An explicit edit cancels a preflight run so an old result cannot overwrite it.
                r.update(test=0,candidates=[],selection={},error='')
                if route=='auto':r['fixed'].pop(key,None)
                else:r['fixed'][key]=route;r['plan'][key]=route
                r['revision']+=1;r['switch_at'][key]=now
            elif path=='/poll':
                report=d.get('report',{})
                if d.get('test')==r['test']:r['reports'][s['steam']]=report
                s['enabled']=bool(d.get('enabled'))
                if r['plan']:
                    for peer,state in report.get('health',{}).items():
                        if peer not in r['members'] or state.get('active',True):continue
                        key=edge(s['steam'],peer)
                        if key in r['fixed']:continue
                        if state.get('route')!=r['plan'].get(key):continue
                        if now-r['switch_at'].get(key,0)<5:continue
                        opposite=r['reports'].get(peer,{}).get('health',{}).get(s['steam'],{})
                        if opposite.get('route')!=r['plan'].get(key):continue
                        options=set(state.get('available',[])) & set(opposite.get('available',[]))
                        options.discard(r['plan'].get(key));options &= set(ROUTES)
                        if options:
                            # Failover only; never optimize a healthy link mid-game.
                            order=sorted(options,key=lambda x:report.get('links',{}).get(peer,{}).get(x,{}).get('p95') or 1e9)
                            r['plan'][key]=order[0];r['revision']+=1;r['switch_at'][key]=now
            elif path=='/leave':
                self.remove(s['sid']);return {'ok':True}
            else:raise ValueError('未知请求')
            self.advance(r)
            members=[]
            for sid in r['members'].values():
                x=self.sessions[sid]
                members.append({k:x[k] for k in ('steam','ipv6','port','token','endpoint','enabled')})
            complete=len(r['members'])>=2 and len(r['plan'])==len(r['members'])*(len(r['members'])-1)//2 and (not r['test'] or bool(r['selection'])) and not r['error']
            return dict(members=members,host=r['host'],test=r['test'],elapsed=now-r['test'] if r['test'] else 0,candidates=r['candidates'],plan=r['plan'],revision=r['revision'],error=r['error'],reports=r['reports'],selection=r['selection'],fixed=r['fixed'],plan_complete=complete)

    def remove(self,sid):
        s=self.sessions.pop(sid,None)
        if not s:return
        self.codes.pop(s['code'],None);r=self.rooms.get(s['room'])
        if r:
            r['members'].pop(s['steam'],None)
            if not r['members']:self.rooms.pop(s['room'],None)
            else:
                if r['host']==s['steam']:r['host']=next(iter(r['members']))
                r['error']='成员离线；请退出游戏房间后重新组队。'

    def udp(self,raw,source):
        if len(raw)<52 or len(raw)>1500 or raw[:4] not in (b'I6H2',b'I6R2'):return None
        with self.lock:
            s=self.sessions.get(raw[4:20].hex())
            if not s or time.monotonic()-s['seen']>60:return None
            if not hmac.compare_digest(raw[20:52],hmac.digest(bytes.fromhex(s['auth']),raw[:20]+raw[52:],'sha256')):return None
            now=time.monotonic()
            if now-s['budget_at']>=1:s['budget']=0;s['budget_at']=now
            s['budget']+=len(raw)
            if s['budget']>2*1024*1024:return None
            if raw[:4]==b'I6H2':
                s['endpoint']=[source[0],source[1]];return None
            if s['endpoint']!=[source[0],source[1]] or len(raw)<60:return None
            target=str(struct.unpack('!Q',raw[52:60])[0]);r=self.room(s)
            sid=r['members'].get(target)
            if not sid or target==s['steam']:return None
            target=self.sessions[sid]
            if target['endpoint']:return raw[60:],tuple(target['endpoint'])

    def expire(self):
        with self.lock:
            for sid,s in list(self.sessions.items()):
                if time.monotonic()-s['seen']>120:self.remove(sid)

def serve(cert,key,host='0.0.0.0',port=27668,udp_port=27667,state_factory=Coordinator):
    state=state_factory()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                self.connection.settimeout(5)
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=65536:raise ValueError('请求过大')
                result=state.handle(self.path,json.loads(self.rfile.read(n)))
                data=json.dumps(result,separators=(',',':')).encode();code=200
            except Exception as e:data=json.dumps({'error':str(e)},ensure_ascii=False).encode();code=400
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(cert,key)
    server=CoordinatorHTTPServer((host,port),Handler,ctx)
    udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind((host,udp_port));udp.settimeout(1)
    def loop():
        while True:
            try:
                raw,source=udp.recvfrom(1501);out=state.udp(raw,source)
                if out:udp.sendto(*out)
            except (OSError,ValueError,KeyError):pass
            state.expire()
    threading.Thread(target=loop,daemon=True).start();server.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cert',required=True);p.add_argument('--key',required=True);p.add_argument('--port',type=int,default=27668);p.add_argument('--udp-port',type=int,default=27667);a=p.parse_args();serve(a.cert,a.key,port=a.port,udp_port=a.udp_port)
