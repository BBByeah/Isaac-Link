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
from isaac_link.runtime_v5 import RuntimeV5
from isaac_link.identity import player_id
from isaac_link.server_code import decode_server_code
from isaac_link.credential_store import ServerCredential
from isaac_link.offline_runtime import OfflineRuntime

ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
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
        self.credentials=ServerCredential(profile_folder);self.saved_server_code=''
        try:
            code=self.credentials.load()
            if code:decode_server_code(code)
            self.saved_server_code=code
        except (OSError,ValueError):self.log('无法读取已保存的服务器码，请重新输入。')

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
        public['members']=[{k:x.get(k) for k in ('steam','player_id','enabled','lan_ip')} for x in room.get('members',[])]
        with self.lock:
            return dict(version=__version__,profile=self.profile,addresses=self.addresses,network=self.network,busy=self.busy,error=self.error,logs=list(self.logs),
                        self=str(rt.transport.local.steam) if rt and rt.transport else '',code=rt.code if rt else '',
                        failure=rt.failure if rt else '',control_failure=rt.control_failure if rt else '',room=public,
                        capture=rt.capture.status() if rt else {},saved_server=bool(self.saved_server_code))

    def submit(self,data):
        with self.lock:
            if self.busy:raise ValueError('上一项操作正在完成，请稍等。')
            action=data.get('action')
            titles={'connect':'正在连接游戏…','disconnect':'正在断开…','new-room':'正在新建组…','add':'正在转接队友…',
                    'test':'正在开始选路…','route':'正在应用线路…','settings':'正在同步设置…','kick':'正在移出成员…',
                    'capture':'正在处理抓包…','open-captures':'正在打开文件夹…','exit':'正在退出…','theme':'正在切换主题…',
                    'guide':'正在保存设置…','network-check':'正在检测 IPv6…','network-settings':'正在打开网络设置…','lan':'正在保存局域网地址…'}
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
            if code:
                try:self.credentials.save(code);self.saved_server_code=code
                except OSError:self.log('已连接，但服务器码未能保存；下次启动需重新输入。')
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
        elif action=='lan':rt.set_lan(d.get('steam'),d.get('ip',''))
        elif action=='capture':
            if rt.capture.active:self.log('抓包已保存：'+str(rt.stop_capture()))
            else:self.log('开始抓包：'+rt.start_capture(ROOT/'captures'))
