"""Portable loopback browser UI. No remote scripts, build tools or runtime install."""
import argparse
import collections
import ctypes
import http.client
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from runtime_v5 import RuntimeV5
from identity import player_id
from server_code import decode_server_code
from offline_runtime import OfflineRuntime

ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
ASSETS=Path(__file__).parent/'web'
PROFILE=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'IsaacLink'

class Backend:
    def __init__(self,profile_folder=PROFILE):
        self.profile_folder=profile_folder;profile_folder.mkdir(parents=True,exist_ok=True)
        try:self.profile=json.loads((profile_folder/'profile.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.profile={}
        self.runtime=None;self.busy='';self.error='';self.logs=collections.deque(maxlen=150)
        self.addresses=[];self.network={'status':'checking'};self.lock=threading.RLock();self.shutdown=lambda:None
        (ROOT/'logs').mkdir(exist_ok=True)
        self.logfile=ROOT/'logs'/('v05-'+time.strftime('%Y%m%d-%H%M%S')+'.log')

    def discover(self):
        self.network={'status':'checking'}
        try:
            command='''[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference='Stop';
            $adapters=@(Get-NetAdapter | Where-Object Status -eq 'Up');
            $bindings=@($adapters | Get-NetAdapterBinding -ComponentID ms_tcpip6);
            $ips=@(Get-NetIPAddress -AddressFamily IPv6 -AddressState Preferred | Where-Object { -not $_.SkipAsSource -and $_.InterfaceIndex -in $adapters.ifIndex } | Select-Object -ExpandProperty IPAddress);
            @{addresses=$ips;active=$adapters.Count;binding_enabled=@($bindings | Where-Object Enabled).Count;binding_count=$bindings.Count} | ConvertTo-Json -Compress'''
            r=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
            if r.returncode:raise RuntimeError('无法读取网卡设置')
            result=json.loads(r.stdout);values=result.get('addresses',[])
            values=[values] if isinstance(values,str) else values
            self.addresses=[ip for ip in values if '%' not in ip and ipaddress.ip_address(ip).is_global]
            status='available' if self.addresses else 'disabled' if result.get('binding_count',0)>0 and result.get('binding_enabled')==0 else 'no_address'
            self.network={'status':status}
        except Exception as e:
            self.network={'status':'unknown'};self.log('网卡检测：'+str(e))

    def log(self,message):
        runtime=self.runtime;names={}
        if runtime:
            names={x['steam']:x.get('player_id','玩家') for x in runtime.room.get('members',[])}
            if runtime.transport:names[str(runtime.transport.local.steam)]=runtime.control.name
            if str(message).startswith('已识别游戏 SteamID'):message=runtime.control.name+' 的游戏已识别。'
        message=re.sub(r'\b\d{17}\b',lambda m:names.get(m[0],'玩家'),str(message))
        line=time.strftime('%H:%M:%S')+' '+message
        with self.lock:self.logs.append(line)
        with self.logfile.open('a',encoding='utf-8') as f:f.write(line+'\n')

    def state(self):
        if isinstance(self.runtime,OfflineRuntime):self.runtime.refresh_room()
        rt=self.runtime;room=rt.room if rt else {}
        # Peer cryptographic tokens never need to reach the browser.
        public={k:v for k,v in room.items() if k!='members'}
        public['members']=[{k:x.get(k) for k in ('steam','player_id','enabled')} for x in room.get('members',[])]
        with self.lock:
            return dict(profile=self.profile,addresses=self.addresses,network=self.network,busy=self.busy,error=self.error,logs=list(self.logs),
                        self=str(rt.transport.local.steam) if rt and rt.transport else '',code=rt.code if rt else '',
                        failure=rt.failure if rt else '',control_failure=rt.control_failure if rt else '',room=public,
                        capture=rt.capture.status() if rt else {})

    def submit(self,data):
        with self.lock:
            if self.busy:raise ValueError('上一项操作正在完成，请稍等。')
            action=data.get('action')
            titles={'connect':'正在连接游戏…','disconnect':'正在断开…','new-room':'正在新建组…','add':'正在转接队友…',
                    'test':'正在开始选路…','route':'正在应用线路…','settings':'正在同步设置…','kick':'正在移出成员…',
                    'capture':'正在处理抓包…','open-captures':'正在打开文件夹…','exit':'正在退出…','theme':'正在切换主题…',
                    'guide':'正在保存设置…','network-check':'正在检测 IPv6…','network-settings':'正在打开网络设置…'}
            if action not in titles:raise ValueError('未知操作')
            self.busy=titles[action];self.error=''
        def work():
            try:self.action(action,data)
            except Exception as e:self.error=str(e);self.log(self.error)
            finally:self.busy=''
        threading.Thread(target=work,daemon=True).start()

    def action(self,action,d):
        if action=='network-check':self.discover();return
        if action=='network-settings':os.startfile('ncpa.cpl');return
        if action=='guide':
            if type(d.get('hide')) is not bool:raise ValueError('提示设置无效')
            self.profile['hide_startup_guide']=d['hide']
            temp=self.profile_folder/'profile.tmp';temp.write_text(json.dumps(self.profile),encoding='utf-8');temp.replace(self.profile_folder/'profile.json')
            return
        if action=='theme':
            theme=d.get('theme')
            if theme not in ('green','wine','gold','purple'):raise ValueError('未知主题')
            self.profile['theme']=theme
            temp=self.profile_folder/'profile.tmp';temp.write_text(json.dumps(self.profile),encoding='utf-8');temp.replace(self.profile_folder/'profile.json')
            return
        if action=='connect':
            name=player_id(d.get('player_id',''))
            code=str(d.get('server_code','')).strip()
            config=decode_server_code(code) if code else None
            ip=d.get('ip','') or next(iter(self.addresses),'')
            if self.runtime:self.runtime.close()
            self.profile={**self.profile,'player_id':name}
            temp=self.profile_folder/'profile.tmp';temp.write_text(json.dumps(self.profile),encoding='utf-8');temp.replace(self.profile_folder/'profile.json')
            self.runtime=RuntimeV5(self.log,name,config) if config else OfflineRuntime(self.log,name)
            try:self.runtime.start(ip,27667)
            except Exception:self.runtime.close();self.runtime=None;raise
            self.log(name+' 已连接，可以复制连接码。');return
        if action in ('disconnect','exit'):
            if self.runtime:self.runtime.close();self.runtime=None
            if action=='exit':self.shutdown()
            return
        if action=='open-captures':
            folder=ROOT/'captures';folder.mkdir(exist_ok=True);os.startfile(str(folder));return
        rt=self.runtime
        if not rt or not rt.transport:raise ValueError('请先连接游戏。')
        if action=='new-room':rt.new_room();self.log('已新建组；个人连接码保持不变。')
        elif action=='add':rt.add(d.get('code',''))
        elif action=='test':rt.test()
        elif action=='route':rt.set_route(d.get('a'),d.get('b'),d.get('route'))
        elif action=='settings':rt.settings(**{k:d[k] for k in ('monitor','redundancy') if k in d})
        elif action=='kick':rt.kick(d.get('steam'))
        elif action=='capture':
            if rt.capture.active:self.log('抓包已保存：'+str(rt.stop_capture()))
            else:self.log('开始抓包：'+rt.start_capture(ROOT/'captures'))

class PageLifetime:
    """Open streaming requests track tabs without background JS timer leases."""
    def __init__(self):
        self.lock=threading.Lock();self.pages=set();self.empty_since=time.monotonic();self.seen=False
    def opened(self,page):
        with self.lock:self.pages.add(page);self.seen=True
    def closed(self,page):
        with self.lock:
            self.pages.discard(page)
            if not self.pages:self.empty_since=time.monotonic()
    def expired(self):
        with self.lock:return not self.pages and time.monotonic()-self.empty_since>(3 if self.seen else 60)

def make_server(backend,port=0):
    token=secrets.token_urlsafe(32)
    lifetime=PageLifetime()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self,api=False):
            origin='http://127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host')!=origin[7:]:return False
            if self.headers.get('Origin',origin)!=origin:return False
            return not api or secrets.compare_digest(self.headers.get('X-Isaac-Token',''),token)
        def respond(self,status,body,mime='application/json; charset=utf-8'):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if not self.allowed(self.path.startswith('/api/')):self.respond(403,{'error':'本地会话验证失败，请重新打开助手。'});return
            if self.path=='/api/page':
                page=object();lifetime.opened(page)
                try:
                    self.connection.settimeout(5)
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-store');self.end_headers()
                    while not self.server.page_stop.is_set():
                        self.wfile.write(b': alive\n\n');self.wfile.flush()
                        self.server.page_stop.wait(.5)
                except OSError:pass
                finally:lifetime.closed(page)
                return
            if self.path=='/api/state':self.respond(200,backend.state());return
            path={'/':'index.html','/style.css':'style.css','/app.js':'app.js'}.get(self.path)
            if not path:self.respond(404,{'error':'不存在'});return
            self.respond(200,(ASSETS/path).read_bytes(),{'index.html':'text/html; charset=utf-8','style.css':'text/css; charset=utf-8','app.js':'text/javascript; charset=utf-8'}[path])
        def do_POST(self):
            if not self.allowed(True):self.respond(403,{'error':'本地会话验证失败。'});return
            if self.path!='/api/action':self.respond(404,{'error':'不存在'});return
            try:
                self.connection.settimeout(5);n=int(self.headers.get('Content-Length','0'))
                if not 0<n<8192 or self.headers.get_content_type()!='application/json':raise ValueError('请求无效')
                d=json.loads(self.rfile.read(n))
                if not isinstance(d,dict):raise ValueError('请求无效')
                backend.submit(d);self.respond(202,{'ok':True})
            except (ValueError,TypeError) as e:self.respond(400,{'error':str(e)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    server.page_lifetime=lifetime;server.page_stop=threading.Event()
    backend.shutdown=server.shutdown
    return server,token

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
    # The second launch opens the existing browser page instead of attaching
    # another hook to the same game. This handle lives until process exit.
    mutex=None
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\IsaacLinkBrowserV5')
        if ctypes.get_last_error()==183:
            try:
                previous=json.loads((PROFILE/'instance.json').read_text(encoding='utf-8'))
                conn=http.client.HTTPConnection('127.0.0.1',int(previous['port']),timeout=2)
                conn.request('GET','/api/state',headers={'X-Isaac-Token':previous['token']})
                response=conn.getresponse();response.read();conn.close()
                if response.status!=200:raise RuntimeError('旧会话未就绪')
                webbrowser.open(f"http://127.0.0.1:{previous['port']}/#{previous['token']}")
            except Exception:
                ctypes.windll.user32.MessageBoxW(None,'助手已经启动，浏览器服务正在准备。请稍后再次打开。','以撒联机助手',0)
            return
    backend=Backend();server,token=make_server(backend,args.port)
    url=f'http://127.0.0.1:{server.server_port}/#{token}'
    (PROFILE/'instance.json').write_text(json.dumps({'port':server.server_port,'token':token,'pid':os.getpid()}),encoding='utf-8')
    threading.Thread(target=backend.discover,daemon=True).start()
    def watch_pages():
        while not server.page_stop.wait(.5):
            if server.page_lifetime.expired():
                backend.log('助手页面已关闭，正在退出。');server.shutdown();return
    threading.Thread(target=watch_pages,daemon=True).start()
    if not args.no_browser:webbrowser.open(url)
    else:print(url,flush=True)
    try:server.serve_forever()
    finally:
        server.page_stop.set()
        if backend.runtime:backend.runtime.close()
        server.server_close()
        try:(PROFILE/'instance.json').unlink(missing_ok=True)
        except OSError:pass

if __name__=='__main__':main()
