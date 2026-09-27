from pathlib import Path
import queue,time,threading
import frida
from isaac_link.transport import Transport

class Runtime:
    hook_name='hook.js'
    def __init__(self,log):
        self.log=log;self.transport=None;self.session=None;self.script=None
        self.outgoing=queue.Queue(maxsize=1024);self.stop_event=threading.Event();self.failure=''
        self.hook_status={};self.native_states={};self.next_hook=0
    def attach(self):
        if self.script:return self.script.exports_sync.info()
        device=frida.get_local_device()
        found=[p for p in device.enumerate_processes() if p.name.lower()=='isaac-ng.exe']
        if len(found)!=1:raise RuntimeError('请先从 Steam 启动一份忏悔+游戏，停留在主菜单。')
        self.session=device.attach(found[0].pid)
        self.pid=found[0].pid
        self.session.on('detached',self.detached)
        self.script=self.session.create_script(Path(__file__).with_name(self.hook_name).read_text(encoding='utf-8'))
        self.script.on('message',self.message)
        try:
            self.script.load()
            info=self.script.exports_sync.info()
        except Exception as e:
            reason=self.failure.splitlines()[0] if self.failure else str(e)
            self.session.off('detached',self.detached)
            self.session.detach();self.session=None;self.script=None;self.failure=''
            raise RuntimeError(reason) from e
        self.log('已识别游戏 SteamID '+info['steam'])
        return info
    def detached(self,*args):
        if not self.stop_event.is_set():self.failure='游戏已退出或接管已断开，请重新启动工具。';self.log(self.failure)
    def message(self,m,data):
        if m['type']=='error':self.failure=m.get('stack',str(m));self.log(self.failure);return
        p=m.get('payload',{})
        if p.get('type')=='packet':
            try:self.outgoing.put_nowait((p,data or b''))
            except queue.Full:self.failure='游戏发送队列已满';self.log(self.failure)
        elif p.get('type')=='fatal':self.failure=p['message'];self.log(self.failure)
    def post(self,p,data=None):
        if self.script:self.script.post({'type':'control','payload':p},data)
    def receive(self,peer,ch,data):
        self.post({'kind':'receive','peer':str(peer),'channel':ch},data)
    def start(self,ip,port):
        info=self.attach()
        self.transport=Transport(int(info['steam']),ip,port,self.receive,event=self.log)
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
        return self.transport.local.code()
    def run(self):
        next_state=0
        while not self.stop_event.is_set():
            try:
                try:
                    p,data=self.outgoing.get(timeout=.03)
                    try:self.transport.send(int(p['peer']),p['channel'],p['mode'],data)
                    except ConnectionError:
                        if p['mode']>=2:
                            self.log('该队友会话不可用：'+p['peer'])
                        # A disconnect between the hook and worker must not latch
                        # a global failure that stops the other two teammates.
                        self.transport.stats['dropped_realtime']+=1
                    except BufferError as e:
                        with self.transport.lock:self.transport.errors[int(p['peer'])]=str(e)
                        self.log(p['peer']+'：'+str(e)+'；其他队友继续连接。')
                    finally:self.post({'kind':'ack'})
                except queue.Empty:pass
                if time.monotonic()>=next_state:
                    snap=self.transport.snapshot();states=snap['peers']
                    if self.failure:
                        for s in states.values():s['active']=False
                    self.post({'kind':'states','states':states});next_state=time.monotonic()+.2
                if time.monotonic()>=self.next_hook:
                    self.hook_status=self.script.exports_sync.status();self.next_hook=time.monotonic()+.5
                    for peer,s in self.hook_status.get('nativePeers',{}).items():
                        state=(s['active'],s['connecting'],s['relay'],s['error'])
                        if self.native_states.get(peer)!=state:
                            self.native_states[peer]=state
                            self.log(f"{peer} Steam 原生：连接={s['active']} 建连中={s['connecting']} 中继={s['relay']} 错误码={s['error']}")
            except Exception as e:
                if not self.failure:self.failure=str(e);self.log('传输已停止：'+self.failure)
                self.stop_event.wait(.1)
    def enable(self):
        if self.failure:raise RuntimeError(self.failure)
        states=self.transport.snapshot()['peers']
        if not states or not all(s['active'] or s['route']=='steam' for s in states.values()):raise RuntimeError('先交换连接码，等待 IPv6 队友连通。Steam 原生连接在进入官方房间后建立。')
        self.script.exports_sync.configure(states);self.script.exports_sync.install()
        self.log('按队友选路已启用：双方有 IPv6 时直连，其余使用 Steam 原生。现在可以进入官方房间。')
    def close(self):
        self.stop_event.set()
        if self.script:
            try:self.script.exports_sync.restore()
            except Exception:pass
        if self.transport:self.transport.close()
        if hasattr(self,'worker'):self.worker.join(2)
        if self.session:
            try:self.session.detach()
            except Exception:pass
