from isaac_link.version import __version__
import threading
import time
from isaac_link.runtime import Runtime
from isaac_link.control import Control
from isaac_link.multipath import Multipath
from isaac_link.capture import Capture

class MultiRuntime(Runtime):
    hook_name='hook_v4.js'
    capture_version=__version__

    def __init__(self,log,config=None):
        super().__init__(log);self.control=Control(config);self.room={};self.enabled=False;self.control_failure='';self.carrier_status={}
        self.capture=Capture()

    def message(self,m,data):
        p=m.get('payload',{})
        if p.get('type')=='packet':self.capture.record('game_hook_send',data or b'',peer=p['peer'],channel=p['channel'],mode=p['mode'],hook_wall_ms=p.get('wall_ms'))
        if p.get('type')=='carrier_sent':
            self.capture.record('steam_api_send',data or b'',peer=p['peer'],success=p['success'],carrier_mode=p.get('mode'),hook_wall_ms=p['wall_ms'],route='steam');return
        if p.get('type')=='game_read':
            self.capture.record('game_hook_read',data or b'',peer=p['peer'],channel=p['channel'],hook_wall_ms=p['wall_ms']);return
        if p.get('type')=='carrier':
            if self.transport:self.transport.carrier_receive(int(p['peer']),data or b'')
        else:super().message(m,data)

    def post(self,p,data=None):
        if p.get('kind')=='receive':self.capture.record('game_hook_deliver',data or b'',peer=p['peer'],channel=p['channel'])
        if p.get('kind')=='states':p={**p,'states':{k:{**v,'route':'managed'} for k,v in p['states'].items()}}
        super().post(p,data)

    def carrier_send(self,peer,data):
        if not self.script or self.failure:return False
        self.post(dict(kind='carrier',peer=str(peer)),data);return True

    def start(self,ip,port):
        info=self.attach()
        if self.capture.active:self.post({'kind':'capture','enabled':True})
        self.transport=Multipath(int(info['steam']),ip,port,self.receive,self.control,self.carrier_send,self.log,capture=self.capture)
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
        self.poller=threading.Thread(target=self.poll,daemon=True);self.poller.start()
        return self.transport.code

    def start_capture(self,folder):
        path=self.capture.start(folder,{'version':self.capture_version,'steam':str(self.transport.local.steam) if self.transport else None})
        if self.script:
            try:self.post({'kind':'capture','enabled':True})
            except Exception:self.log('游戏接口已断开；抓包文件仍可保存已有及后续传输记录。')
        self.capture.record('context',plan=self.room.get('plan',{}),network=self.transport.snapshot() if self.transport else {})
        return path

    def stop_capture(self):
        if self.script:
            try:self.post({'kind':'capture','enabled':False})
            except Exception:pass
        return self.capture.stop()

    def add(self,code):self.control.call('/add',code=code.strip())
    def test(self):self.control.call('/test')
    def set_route(self,a,b,route):self.control.call('/route',a=a,b=b,route=route)

    def poll(self):
        configured=();reported_error=''
        while not self.stop_event.is_set():
            try:
                room=self.control.call('/poll',report=self.transport.report(),test=self.transport.test_id,enabled=self.enabled and not self.failure)
                self.transport.update(room);self.room=room
                if self.capture.active:self.capture.record('network_snapshot',plan=room.get('plan',{}),fixed=room.get('fixed',{}),network=self.transport.snapshot())
                ids=tuple(sorted(str(x) for x in self.transport.peers))
                if ids!=configured:self.script.exports_sync.carrierconfigure(list(ids));configured=ids
                self.carrier_status=self.script.exports_sync.carrierstatus()
                if room['error'] and room['error']!=reported_error:self.log(room['error']);reported_error=room['error']
                if room.get('plan_complete',bool(room['plan'])) and not room['error'] and not self.enabled:self.enable()
                if self.control_failure:self.log('协调服务器连接已恢复。')
                self.control_failure=''
            except Exception as e:
                error=str(e)
                if error!=self.control_failure:self.log('协调状态：'+error)
                self.control_failure=error
            self.stop_event.wait(.35)

    def enable(self):
        if self.failure:raise RuntimeError(self.failure)
        states=self.transport.snapshot()['peers']
        if not states or not all(s['active'] for s in states.values()):return
        states={k:{**s,'route':'managed'} for k,s in states.items()}
        self.script.exports_sync.configure(states);self.script.exports_sync.install();self.enabled=True
        self.log('本机已应用选路。等图中全员显示“已接管”后，再进入官方联机房间。')

    def close(self):
        self.stop_event.set()
        if hasattr(self,'poller'):self.poller.join(5)
        if self.control.credentials:
            try:self.control.call('/leave')
            except Exception:pass
        super().close()
        try:self.capture.stop()
        except RuntimeError as e:self.log(str(e))
