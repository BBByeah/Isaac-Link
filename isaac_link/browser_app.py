"""Portable loopback browser UI. No remote scripts, build tools or runtime install."""
import argparse
from isaac_link.version import __version__
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
from isaac_link.runtime_v5 import RuntimeV5
from isaac_link.identity import player_id
from isaac_link.server_code import decode_server_code
from isaac_link.credential_store import ServerCredential
from isaac_link.offline_runtime import OfflineRuntime

ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
ASSETS=Path(__file__).parent/'web'
PROFILE=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'IsaacLink'

from isaac_link.backend import Backend

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
            if self.path=='/api/server-code':self.respond(200,{'code':backend.saved_server_code});return
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
    parser=argparse.ArgumentParser();parser.add_argument("--version",action="version",version=__version__);parser.add_argument('--no-browser',action='store_true');parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
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
