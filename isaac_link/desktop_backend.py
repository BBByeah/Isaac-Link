"""UI-neutral command/snapshot boundary. Blocking operations run off the UI thread."""
import itertools
import json
import threading
import time
from isaac_link.backend import Backend, PROFILE, ROOT
from isaac_link.identity import player_id
from isaac_link.runtime7 import Runtime7
from isaac_link.routing import edge
from isaac_link.server_code import decode_server_code
from isaac_link.updates import UpdateManager
from isaac_link.version import __version__
from isaac_link.stun import DEFAULT_SERVERS,parse_servers

class DesktopBackend(Backend):
    def __init__(self,profile_folder=PROFILE):
        super().__init__(profile_folder)
        self.updates=UpdateManager(profile_folder);self.closing=False

    def save_profile(self):
        path=self.profile_folder/'profile.json';tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.profile,ensure_ascii=False),encoding='utf-8');tmp.replace(path)

    def submit(self,data):
        with self.lock:
            if self.busy or self.closing:return
            self.busy='正在处理…';self.error=''
        def work():
            try:self.action(data['action'],data)
            except Exception as e:self.error=str(e);self.log(str(e))
            finally:self.busy=''
        threading.Thread(target=work,daemon=True).start()

    def action(self,action,d):
        if action=='connect':
            name=player_id(d['player_id']);code=d.get('server_code','').strip();config=decode_server_code(code) if code else None
            servers=parse_servers(self.profile.get('stun_servers','\n'.join(f'{h}:{p}' for h,p in DEFAULT_SERVERS)))
            if self.runtime:self.runtime.close()
            rt=Runtime7(self.log,name,config);self.runtime=rt
            rt.stun_servers=servers
            try:rt.start(d.get('ip','') or next(iter(self.addresses),''))
            except Exception:rt.close();self.runtime=None;raise
            self.profile['player_id']=name;self.save_profile()
            try:
                if code:self.credentials.save(code);self.saved_server_code=code
                else:self.credentials.forget();self.saved_server_code=''
            except OSError:self.log('连接已建立，但服务器码未能保存。')
            self.log('已连接游戏；把连接码交给房主，或添加队友创建房间。');return
        if action=='accept':self.runtime.accept(d['steam']);return
        if action=='route':self.runtime.set_route(d['a'],d['b'],d['route'],d.get('plane','game'));return
        if action=='control-route':self.runtime.set_control_route(d['route']);return
        if action=='dissolve':self.runtime.dissolve();return
        if action=='update-check':self.updates.start(self.updates.check);return
        if action=='update-download':self.updates.start(self.updates.download);return
        if action=='update-cancel':self.updates.cancel.set();return
        if action=='update-ignore':
            self.profile['ignored_version']=self.updates.manifest['version'];self.save_profile();return
        if action=='auto-update':self.profile['check_updates']=bool(d['enabled']);self.save_profile();return
        if action=='stun-settings':
            rows=parse_servers(d['text']);self.profile['stun_servers']='\n'.join(f'{h}:{p}' for h,p in rows);self.save_profile();return
        return super().action(action,d)

    def state(self):
        rt=self.runtime;room={};edges={};network={};code='';is_host=False;server='未配置';failure='';inputs={}
        if rt and rt.transport:
            with rt.transport.lock:
                session=rt.transport.session;room=session.public();code=session.code;is_host=session.me==session.host
                network=rt.transport.public_edges();server=rt.transport.server_status;failure=rt.failure
                now=time.monotonic()
                for a,b in itertools.combinations(session.members,2):
                    key=edge(a,b)
                    if session.me in (a,b):
                        other=b if a==session.me else a;record=network.get(other,{})
                        stale=False
                    else:
                        at,remote=session.telemetry.get(a,(0,{}));record=remote.get(b,{})
                        stale=now-at>4
                    edges[key]={**record,'stale':stale,'a':a,'b':b,'game_mode':session.game_fixed.get(key,'auto'),
                                'control_mode':session.control_fixed.get(key,'auto')}
                inputs=getattr(rt,'inputs',{})
        return dict(version=__version__,profile=dict(self.profile),network_check=self.network,room=room,edges=edges,code=code,is_host=is_host,
                    connected=rt is not None,enabled=bool(rt and rt.enabled),server=server,failure=failure,error=self.error,busy=self.busy,
                    logs=list(self.logs),capture=rt.capture.status() if rt else {},inputs=inputs,
                    steam=getattr(rt,'carrier_status',{}) if rt else {},update=dict(status=self.updates.status,error=self.updates.error,
                        progress=self.updates.progress,manifest=self.updates.manifest))

    def close_async(self,done):
        if self.closing:return
        self.closing=True;self.updates.cancel.set()
        def close():
            try:
                while self.busy:time.sleep(.05)
                if self.runtime:self.runtime.close();self.runtime=None
            finally:done()
        threading.Thread(target=close,daemon=True).start()
