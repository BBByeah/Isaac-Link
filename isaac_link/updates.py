"""Opt-in, signed release downloads. No installation while a game is attached."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from isaac_link.version import __version__

SOURCES=('https://github.com/BBByeah/Isaac-Link/releases/latest/download/update.json',)
MAX_PACKAGE=512*1024*1024

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('版本号无效')
    return tuple(map(int,value.split('.')))

def public_key():
    path=Path(__file__).with_name('release_public_key.txt')
    if not path.exists():raise ValueError('此开发构建尚未配置发布公钥')
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(path.read_text().strip()))

def verified_manifest(raw,key=None):
    if len(raw)>131072:raise ValueError('版本清单过大')
    wrapper=json.loads(raw);payload=base64.b64decode(wrapper['payload'],validate=True)
    (key or public_key()).verify(base64.b64decode(wrapper['signature'],validate=True),payload)
    data=json.loads(payload);version(data['version'])
    if data['platform']!='windows-x64' or data['protocol']!=8:raise ValueError('此更新的平台或协议不兼容')
    if type(data['size'])!=int or not 0<data['size']<=MAX_PACKAGE:raise ValueError('更新包大小无效')
    if not isinstance(data['urls'],list) or not 1<=len(data['urls'])<=4:raise ValueError('更新下载地址无效')
    for url in data['urls']:https_url(url)
    if len(base64.b64decode(data['package_signature'],validate=True))!=64:raise ValueError('更新签名无效')
    return data

def https_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('更新来源必须是 HTTPS')
    return url

def fetch(url,limit=131072):
    request=urllib.request.Request(https_url(url),headers={'User-Agent':'Isaac-Link/'+__version__})
    with urllib.request.urlopen(request,timeout=15) as response:
        https_url(response.url);data=response.read(limit+1)
    if len(data)>limit:raise ValueError('下载内容过大')
    return data

def verify_package(path,manifest,key=None):
    path=Path(path)
    if path.stat().st_size!=manifest['size']:raise ValueError('更新包不完整')
    (key or public_key()).verify(base64.b64decode(manifest['package_signature'],validate=True),path.read_bytes())

class UpdateManager:
    def __init__(self,folder,sources=SOURCES):
        self.folder=Path(folder)/'updates';self.sources=tuple(sources);self.cancel=threading.Event()
        self.status='idle';self.error='';self.manifest=None;self.raw=None;self.progress=0;self.archive=None
        self.lock=threading.Lock();self.worker=None

    def start(self,fn):
        with self.lock:
            if self.worker and self.worker.is_alive():return
            self.cancel.clear();self.error=''
            def run():
                try:fn()
                except InterruptedError:self.status='cancelled'
                except Exception as e:self.error=str(e) or '签名验证失败';self.status='error'
            self.worker=threading.Thread(target=run,daemon=True);self.worker.start()

    def check(self):
        self.status='checking'
        failures=[]
        for source in self.sources:
            try:
                raw=fetch(source);manifest=verified_manifest(raw)
                self.raw=raw;self.manifest=manifest
                self.status='available' if version(manifest['version'])>version(__version__) else 'latest'
                return
            except Exception as e:failures.append(str(e))
        raise ValueError('暂时无法检查更新；可继续使用当前版本。 '+ '; '.join(failures))

    def download(self):
        if not self.manifest:raise ValueError('请先检查更新')
        self.status='downloading';self.folder.mkdir(parents=True,exist_ok=True)
        manifest=verified_manifest(self.raw);target=self.folder/('client-'+manifest['version']+'.zip')
        partial=target.with_suffix('.partial');failures=[]
        for url in manifest['urls']:
            try:
                self.progress=0
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Isaac-Link'}),timeout=20) as response,partial.open('wb') as out:
                    https_url(response.url);size=0
                    while True:
                        if self.cancel.is_set():raise InterruptedError()
                        block=response.read(262144)
                        if not block:break
                        size+=len(block)
                        if size>manifest['size']:raise ValueError('更新包超过声明大小')
                        out.write(block);self.progress=int(size*100/manifest['size'])
                verify_package(partial,manifest)
                partial.replace(target);self.archive=target;self.status='ready'
                (self.folder/'update.json').write_bytes(self.raw)
                return
            except InterruptedError:raise
            except Exception as e:failures.append(str(e))
        raise ValueError('更新下载失败：'+'; '.join(failures))

    def launch_installer(self,root):
        if self.status!='ready' or not self.archive:raise ValueError('更新尚未下载完成')
        if not getattr(sys,'frozen',False):raise ValueError('源码运行不支持覆盖安装，请使用发布版')
        root=Path(root).resolve()
        if not (root/'.isaac-link-install.json').is_file():raise ValueError('安装目录标记缺失，请手动安装发布版')
        try:
            with tempfile.TemporaryFile(dir=root):pass
            with tempfile.TemporaryFile(dir=root.parent):pass
        except OSError as e:raise ValueError('安装目录不可写，请将程序移至可写目录') from e
        stage=Path(tempfile.mkdtemp(prefix='IsaacLink-update-'))
        updater=stage/'updater.exe';shutil.copy2(root/'updater.exe',updater)
        job=dict(root=str(root),archive=str(self.archive.resolve()),manifest=str((self.folder/'update.json').resolve()),pid=os.getpid())
        job_path=stage/'job.json';job_path.write_text(json.dumps(job),encoding='utf-8')
        subprocess.Popen([str(updater),'--job',str(job_path)],cwd=stage,creationflags=subprocess.CREATE_NO_WINDOW)
