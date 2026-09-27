"""Browser client runtime: room epochs, reconnectable lifecycle and slow telemetry."""
import queue
import threading
import time
from isaac_link.control import Control
from isaac_link.runtime_v4 import MultiRuntime
from isaac_link.transport_v5 import TransportV5
from isaac_link.identity import player_id

class ControlV5(Control):
    def __init__(self,name,config=None):super().__init__(config);self.name=player_id(name)
    def register(self,steam,ipv6,port,token):
        r=self.call('/register',steam=str(steam),ipv6=ipv6,port=port,token=token.hex(),protocol=5,player_id=self.name)
        self.credentials={k:r[k] for k in ('sid','auth')};return r['code']

class RuntimeV5(MultiRuntime):
    hook_name='hook_v5.js'
    capture_version='0.5.0'
    def __init__(self,log,name,config=None):
        super().__init__(log,config);self.control=ControlV5(name,config)
        self.generation=None;self.session_lock=threading.RLock();self.telemetry={};self.code=''

    def detached(self,*args):
        if not self.stop_event.is_set():
            self.failure='游戏连接已断开。启动游戏后点击重新连接即可。';self.log(self.failure)
        self.stop_event.set()

    def start(self,ip,port):
        info=self.attach()
        try:self.transport=TransportV5(int(info['steam']),ip,port,self.receive,self.control,self.carrier_send,self.log,capture=self.capture)
        except Exception:self.close();raise
        self.code=self.transport.code
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
        self.poller=threading.Thread(target=self.poll,daemon=True);self.poller.start()
        return self.code

    def post(self,p,data=None):
        super().post({**p,'generation':self.generation or ''},data)

    def run(self):
        next_state=0
        while not self.stop_event.is_set():
            try:
                try:
                    p,data=self.outgoing.get(timeout=.02)
                    with self.session_lock:
                        if p.get('generation')==self.generation:
                            try:self.transport.send(int(p['peer']),p['channel'],p['mode'],data)
                            except ConnectionError:self.transport.stats['dropped_realtime']+=1
                            except BufferError as e:self.log(str(e))
                            self.post({'kind':'ack'})
                except queue.Empty:pass
                if time.monotonic()>=next_state:
                    with self.session_lock:
                        states=self.transport.snapshot()['peers']
                        if self.failure:
                            for s in states.values():s['active']=False
                        self.post({'kind':'states','states':states});next_state=time.monotonic()+.2
            except Exception as e:
                if not self.failure:self.failure=str(e);self.log('游戏连接：'+self.failure)
                self.stop_event.wait(.2)

    def poll(self):
        configured=();next_telemetry=0;monitor=None;last_error=''
        while not self.stop_event.is_set():
            try:
                if self.failure:self.stop_event.wait(.2);continue
                now=time.monotonic();data={}
                if self.room.get('monitor',True) and now>=next_telemetry:
                    self.telemetry={'inputs':self.script.exports_sync.inputs()}
                    data['telemetry']=self.telemetry;next_telemetry=now+3
                room=self.control.call('/poll',epoch=self.generation,report=self.transport.report(),test=self.transport.test_id,enabled=self.enabled and not self.failure,**data)
                with self.session_lock:
                    with self.transport.lock:
                        if room['epoch']!=self.generation:
                            self.generation=room['epoch'];self.enabled=False;self.telemetry={}
                            self.script.exports_sync.resetroom(self.generation)
                            while True:
                                try:self.outgoing.get_nowait()
                                except queue.Empty:break
                        self.room=room;self.transport.update(room)
                    ids=tuple(sorted(str(x) for x in self.transport.peers))
                    if ids!=configured:self.script.exports_sync.carrierconfigure(list(ids));configured=ids
                    if monitor!=room['monitor']:
                        monitor=room['monitor'];self.script.exports_sync.monitoring(monitor);next_telemetry=0
                    if room.get('plan_complete') and not room['error'] and not self.enabled:self.enable()
                if self.capture.active:self.capture.record('network_snapshot',plan=room.get('plan',{}),network=self.transport.snapshot())
                if room['error']!=last_error:
                    last_error=room['error']
                    if last_error:self.log(last_error)
                self.control_failure=''
            except Exception as e:
                error=str(e)
                if '会话过期' in error:self.failure='协调会话已失效，点击重新连接即可恢复。'
                if error!=self.control_failure:self.log('协调连接：'+error)
                self.control_failure=error
            self.stop_event.wait(.35 if self.room.get('test') and not self.room.get('selection') else 1)

    def new_room(self):return self.control.call('/new-room')
    def settings(self,**data):return self.control.call('/settings',**data)
    def kick(self,steam):return self.control.call('/kick',steam=steam)
