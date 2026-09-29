"""Optional 0.7 relay. Room membership and route decisions remain on clients."""
import hmac
import secrets
import struct
import time
from isaac_link.protocol7 import encode
from server.coordinator_v5 import CoordinatorV5

class Coordinator7(CoordinatorV5):
    def __init__(self,access_key):
        super().__init__();self.access_key=access_key;self.v7={}

    def handle(self,path,d):
        if not path.startswith('/v7/'):
            if path=='/register' and not hmac.compare_digest(str(d.get('access_key','')),self.access_key):raise ValueError('服务器连接码无效')
            return super().handle(path,d)
        with self.lock:
            now=time.monotonic()
            if path=='/v7/register':
                if not hmac.compare_digest(str(d.get('access_key','')),self.access_key):raise ValueError('服务器连接码无效')
                if d.get('protocol')!=8:raise ValueError('协议不兼容')
                steam=str(int(d['steam']));room=d['room']
                if not 0<int(steam)<2**64 or not isinstance(room,str) or len(room)!=24:raise ValueError('会话无效')
                if len(self.v7)>=512:raise ValueError('服务器会话已满')
                for sid,s in list(self.v7.items()):
                    if s['steam']==steam and s['room']==room:del self.v7[sid]
                sid=secrets.token_hex(16);auth=secrets.token_hex(32)
                self.v7[sid]=dict(steam=steam,room=room,auth=auth,seen=now,endpoint=None,budget=0,budget_at=now)
                return dict(sid=sid,auth=auth,protocol=8)
            s=self.v7.get(d.get('sid'))
            if not s or not hmac.compare_digest(s['auth'],str(d.get('auth',''))):raise ValueError('会话已过期')
            s['seen']=now
            if path=='/v7/alive':return {'ok':True}
            raise ValueError('未知接口')

    def udp(self,raw,source):
        if raw[:4] not in (b'I7H2',b'I7R2'):return super().udp(raw,source)
        if not 52<=len(raw)<=1500:return
        with self.lock:
            s=self.v7.get(raw[4:20].hex());now=time.monotonic()
            if not s or now-s['seen']>60:return
            auth=bytes.fromhex(s['auth'])
            if not hmac.compare_digest(raw[20:52],hmac.digest(auth,raw[:20]+raw[52:],'sha256')):return
            if now-s['budget_at']>=1:s['budget_at']=now;s['budget']=0
            s['budget']+=len(raw)
            if s['budget']>2*1024*1024:return
            if raw[:4]==b'I7H2':
                s['endpoint']=source[:2];reply=b'I7E2'+encode(source[:2])
                return reply+hmac.digest(auth,reply,'sha512')[:32],source[:2]
            if s['endpoint']!=source[:2] or len(raw)<60:return
            target=str(struct.unpack_from('!Q',raw,52)[0])
            for other in self.v7.values():
                if other['steam']==target and other['room']==s['room'] and other['endpoint'] and now-other['seen']<60:return raw[60:],other['endpoint']

    def expire(self):
        super().expire()
        with self.lock:
            now=time.monotonic()
            for sid,s in list(self.v7.items()):
                if now-s['seen']>120:del self.v7[sid]
