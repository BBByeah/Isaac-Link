"""Game-process adapter. UI and optional servers do not own transport lifetime."""
import queue
import threading
import time
from isaac_link.runtime import Runtime
from isaac_link.runtime_v4 import MultiRuntime
from isaac_link.transport7 import Transport7
from isaac_link.capture import Capture
from isaac_link.stun import DEFAULT_SERVERS

class Runtime7(MultiRuntime):
    hook_name='hook7.js'

    def __init__(self,log,name,config=None):
        super().__init__(log,config);self.name=name;self.control.name=name;self.server_config=config;self.code='';self.generation='';self.room={}
        self.stun_servers=DEFAULT_SERVERS

    def start(self,ip,port=27667):
        info=self.attach()
        self.transport=Transport7(int(info['steam']),self.name,ip,port,self.receive,self.carrier_send,self.log,self.capture,self.server_config,stun_servers=self.stun_servers)
        self.code=self.transport.code
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
        return self.code

    def post(self,p,data=None):
        super().post({**p,'generation':self.generation},data)

    def run(self):
        configured=None;next_state=0;next_monitor=0
        while not self.stop_event.is_set():
            try:
                if self.failure:self.stop_event.wait(.2);continue
                try:
                    p,data=self.outgoing.get(timeout=.02)
                    if p.get('generation')==self.generation:
                        try:self.transport.send(int(p['peer']),p['channel'],p['mode'],data)
                        except ConnectionError:self.transport.stats['dropped_realtime']+=1
                        except BufferError as e:self.log(str(e))
                    self.post({'kind':'ack'})
                except queue.Empty:pass
                now=time.monotonic()
                if now>=next_state:
                    next_state=now+.25
                    with self.transport.lock:
                        session=self.transport.session
                        self.room=session.public()
                        generation=session.room
                        ids=tuple(sorted((set(session.members)|set(session.invites)|set(session.offers))-{session.me}))
                        states=self.transport.snapshot()['peers']
                    if generation!=self.generation:
                        self.script.exports_sync.resetroom(generation);self.generation=generation
                    if ids!=configured:self.script.exports_sync.carrierconfigure(list(ids));configured=ids
                    managed={k:{**v,'route':'managed'} for k,v in states.items()}
                    self.script.exports_sync.configure(managed)
                    if not self.enabled and any(s['active'] for s in states.values()):
                        self.script.exports_sync.install();self.enabled=True;self.log('已启用自动接管')
                    self.post({'kind':'states','states':managed})
                    if now>=next_monitor:
                        next_monitor=now+1
                        self.script.exports_sync.monitoring(session.monitor)
                        self.carrier_status=self.script.exports_sync.carrierstatus()
                        self.hook_status=self.script.exports_sync.status()
                        self.inputs=self.script.exports_sync.inputs() if session.monitor else {}
                        with self.transport.lock:self.transport.input_metrics=self.inputs
                        self.capture.record('network_snapshot',room=self.room,network=self.transport.public_edges())
            except Exception as e:
                self.failure='游戏接口已断开，请重新连接游戏：'+str(e);self.log(self.failure)

    def add(self,code):
        with self.transport.lock:self.transport.session.invite(code)
    def test(self):
        with self.transport.lock:self.transport.session.all_auto()
    def set_route(self,a,b,route,plane='game'):
        with self.transport.lock:self.transport.session.route(str(a),str(b),route,plane)
    def settings(self,**data):
        with self.transport.lock:self.transport.session.settings(**data)
    def set_control_route(self,route):
        with self.transport.lock:self.transport.session.set_control_route(route)
    def accept(self,sid):
        with self.transport.lock:self.transport.session.accept(str(sid))
    def set_lan(self,sid,ip):
        with self.transport.lock:self.transport.session.lan(str(sid),ip)
    def kick(self,sid):
        with self.transport.lock:self.transport.session.kick(str(sid))
    def new_room(self):
        raise ValueError('请断开助手并重新连接游戏以创建新房间')
    def dissolve(self):
        with self.transport.lock:
            s=self.transport.session;s.require_host()
            for p in self.transport.peers:s.send(p,'removed',{},True)
            s.cancelled=True
            s.error='房间已解散；请断开并重新连接以创建新房间。'
            self.transport.suspend()

    def close(self):
        self.stop_event.set()
        Runtime.close(self)
        self.capture.stop()
