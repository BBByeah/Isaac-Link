"""Client-owned rooms and pair-local routing, independent of any server lease."""
import collections
import itertools
import math
import secrets
import time
from isaac_link.protocol7 import PROTOCOL, descriptor, connection_code, parse_code, peer_from, encode
from isaac_link.routing import edge
from isaac_link.selection import Selector, ControlSelector, ORDER, quality, PERIOD

class Session:
    def __init__(self, transport, name):
        self.t=transport;self.me=str(transport.local.steam);self.name=name
        self.room=secrets.token_hex(12);self.host=self.me;self.revision=1
        self.members={self.me:descriptor(transport.local,name)}
        self.game_fixed={};self.control_fixed={};self.control_route='steam';self.monitor=True;self.redundancy='window4'
        self.invites={};self.offers={};self.awaiting={};self.outbox={};self.seen=collections.OrderedDict()
        self.selectors={};self.controls={};self.remote={};self.remote_at={};self.telemetry={}
        self.remote_revision={}
        self.switches={};self.switch_version=collections.defaultdict(int);self.overlap={}
        self.last_state=0;self.last_offer=0;self.last_health=0;self.error='';self.cancelled=False
        self.code=connection_code(self.members[self.me])

    def require_host(self):
        if self.me!=self.host:raise ValueError('只有房主可以修改房间配置')

    def config(self):
        return dict(room=self.room,host=self.host,revision=self.revision,members=self.members,
                    game_fixed=self.game_fixed,control_route=self.control_route,monitor=self.monitor,redundancy=self.redundancy)

    def invite(self,code):
        self.require_host();d=parse_code(code);sid=d['steam']
        if sid==self.me:raise ValueError('不能邀请自己')
        if len(self.members)+len(self.invites)>=4:raise ValueError('最多四人，请取消旧邀请或移出成员')
        if sid in self.members:return
        self.invites[sid]={'peer':d,'nonce':secrets.token_hex(12),'at':time.monotonic()}

    def boot(self,sid,kind,data,recipient):
        self.t.bootstrap_send(int(sid),dict(protocol=PROTOCOL,sender=self.me,kind=kind,**data),peer_from(recipient).token)

    def receive_boot(self,sender,value):
        sid=str(sender);kind=value.get('kind');now=time.monotonic()
        if kind=='invite':
            d=value['peer']
            if str(peer_from(d).steam)!=sid or len(self.members)>1:return
            if len(self.offers)>=8 and sid not in self.offers:return
            previous=self.offers.get(sid,{})
            self.offers[sid]=dict(peer=d,nonce=value['nonce'],room=value['room'],at=now,
                accepted=bool(previous.get('accepted') and previous.get('nonce')==value['nonce']))
        elif kind=='accept':
            invite=self.invites.get(sid)
            if not invite or value.get('nonce')!=invite['nonce']:return
            self.members[sid]=invite['peer'];self.revision+=1
            self.awaiting[sid]=dict(peer=invite['peer'],nonce=invite['nonce'],at=now)
            del self.invites[sid];self.install(self.config());self.broadcast()
        elif kind=='welcome':
            offer=self.offers.get(sid)
            if not offer or not offer.get('accepted') or value.get('nonce')!=offer['nonce']:return
            cfg=value['config']
            if cfg['host']!=sid or cfg['room']!=offer['room']:return
            if cfg['members'].get(self.me)!=self.members[self.me]:return
            self.install(cfg,joining=True)
            self.boot(sid,'welcomed',{'nonce':offer['nonce']},offer['peer'])
            # Retain accepted offer briefly so a lost welcome acknowledgement can be retried.
            offer['at']=now
        elif kind=='welcomed':
            item=self.awaiting.get(sid)
            if item and item['nonce']==value.get('nonce'):del self.awaiting[sid]

    def accept(self,sid):
        offer=self.offers.get(str(sid))
        if not offer or time.monotonic()-offer['at']>120:raise ValueError('邀请已过期')
        if len(self.members)>1:raise ValueError('请先离开当前房间')
        offer['accepted']=True
        self.boot(str(sid),'accept',{'nonce':offer['nonce']},offer['peer'])

    def install(self,cfg,joining=False):
        if not isinstance(cfg,dict) or not 1<=len(cfg['members'])<=4:raise ValueError('房间成员无效')
        if cfg['host'] not in cfg['members'] or self.me not in cfg['members']:raise ValueError('房间身份无效')
        for sid,d in cfg['members'].items():
            if str(peer_from(d).steam)!=sid:raise ValueError('成员身份不一致')
        if not joining and (cfg['room']!=self.room or cfg['host']!=self.host or cfg['revision']<self.revision):return
        if joining and cfg['room']==self.room and cfg['revision']<=self.revision:return
        if cfg.get('control_route','steam') not in ORDER:raise ValueError('全队协调线路无效')
        for field in ('game_fixed',):
            for pair,route in cfg.get(field,{}).items():
                if route not in ORDER or pair not in {edge(a,b) for a,b in itertools.combinations(cfg['members'],2)}:raise ValueError('线路配置无效')
        if cfg.get('redundancy') not in ('off','window4'):raise ValueError('输入冗余配置无效')
        changed_room=cfg['room']!=self.room
        if changed_room:
            self.t.reset_room();self.outbox.clear();self.seen.clear();self.selectors.clear();self.controls.clear()
            self.remote.clear();self.remote_at.clear();self.switches.clear();self.switch_version.clear();self.overlap.clear()
        self.room=cfg['room'];self.host=cfg['host'];self.revision=cfg['revision'];self.members=cfg['members']
        self.game_fixed=dict(cfg.get('game_fixed',{}));self.control_route=cfg.get('control_route','steam')
        self.control_fixed={edge(a,b):self.control_route for a,b in itertools.combinations(self.members,2)}
        self.monitor=bool(cfg.get('monitor',True));self.redundancy=cfg['redundancy']
        self.t.sync_members(self.members,self.room)
        for sid in self.members:
            if sid==self.me:continue
            p=int(sid);key=edge(self.me,sid)
            self.selectors.setdefault(p,Selector()).fixed=self.game_fixed.get(key,'auto')
            self.controls.setdefault(p,ControlSelector()).fixed=self.control_route
        for p in list(self.selectors):
            if str(p) not in self.members:
                self.selectors.pop(p,None);self.controls.pop(p,None);self.remote.pop(p,None);self.remote_at.pop(p,None)
        self.t.monitor_enabled=self.monitor;self.t.redundancy=self.redundancy

    def route(self,a,b,route,plane='game'):
        self.require_host()
        if a not in self.members or b not in self.members or a==b:raise ValueError('请选择有效玩家对')
        if route not in (*ORDER,'auto'):raise ValueError('未知线路')
        if plane not in ('game','control'):raise ValueError('未知线路用途')
        if plane=='control':self.set_control_route(route);return
        mapping=self.game_fixed
        if route=='auto':mapping.pop(edge(a,b),None)
        else:mapping[edge(a,b)]=route
        self.revision+=1;self.install(self.config());self.broadcast()

    def all_auto(self):
        self.require_host();self.game_fixed.clear();self.revision+=1;self.install(self.config());self.broadcast()

    def set_control_route(self,route):
        self.require_host()
        if route not in ORDER:raise ValueError('请选择全队统一协调线路')
        self.control_route=route;self.revision+=1;self.install(self.config());self.broadcast()

    def settings(self,monitor=None,redundancy=None):
        self.require_host()
        if monitor is not None:self.monitor=bool(monitor)
        if redundancy is not None:
            if redundancy not in ('off','window4'):raise ValueError('未知冗余模式')
            self.redundancy=redundancy
        self.revision+=1;self.install(self.config());self.broadcast()

    def lan(self,sid,ip):
        import ipaddress
        self.require_host()
        if sid not in self.members:raise ValueError('成员不存在')
        if ip:
            addr=ipaddress.IPv4Address(ip)
            if addr.is_loopback or addr.is_multicast or addr.is_unspecified:raise ValueError('请输入实际局域网 IPv4')
        self.members[sid]['lan_ip']=ip;self.revision+=1;self.install(self.config());self.broadcast()

    def kick(self,sid):
        self.require_host()
        if sid==self.me or sid not in self.members:raise ValueError('请选择其他成员')
        self.send(int(sid),'removed',{},reliable=True)
        del self.members[sid]
        for mapping in (self.game_fixed,self.control_fixed):
            for key in list(mapping):
                if sid in key.split(':'):del mapping[key]
        self.revision+=1;self.install(self.config());self.broadcast()

    def send(self,p,kind,data,reliable=False):
        message=dict(protocol=PROTOCOL,room=self.room,sender=self.me,id=secrets.token_hex(8),revision=self.revision,kind=kind,data=data,reliable=reliable)
        if reliable:
            if len(self.outbox)>=128:raise BufferError('协调消息队列已满，请等待线路恢复')
            self.outbox[p,message['id']]=[message,0,time.monotonic()]
        self.transmit(p,message)
        return message['id']

    def transmit(self,p,message):
        control=self.controls.get(p);route=control.current if control else None
        if route:self.t.send_control(p,route,message)

    def broadcast(self):
        # Only the latest room snapshot needs retransmission.
        for key,item in list(self.outbox.items()):
            if item[0]['kind']=='config':del self.outbox[key]
        for sid in self.members:
            if sid!=self.me:self.send(int(sid),'config',self.config(),True)

    def receive(self,p,message):
        if message.get('protocol')!=PROTOCOL or message.get('room')!=self.room or message.get('sender')!=str(p) or str(p) not in self.members:return
        kind=message.get('kind');data=message.get('data',{});now=time.monotonic()
        if kind=='ack':self.outbox.pop((p,data.get('id')),None);return
        if message.get('reliable'):self.send(p,'ack',{'id':message['id']})
        key=(p,message.get('id'))
        if key in self.seen:return
        self.seen[key]=now
        while len(self.seen)>4096:self.seen.popitem(last=False)
        if kind=='config' and str(p)==self.host:self.install(data)
        elif kind=='removed' and str(p)==self.host:self.cancelled=True;self.error='房主已将你移出或解散房间';self.t.suspend()
        elif kind=='health':
            self.remote[p]=data;self.remote_at[p]=now
            self.remote_revision[p]=message.get('revision',0)
            self.t.set_candidates(p,data.get('candidates',[]))
            if self.monitor and self.me==self.host:self.telemetry[str(p)]=(now,data.get('telemetry',{}))
        elif kind.startswith('switch_'):
            self.receive_switch(p,kind,data,message.get('revision'),now)

    def receive_switch(self,p,kind,data,revision,now):
        if revision!=self.revision:return
        route=data.get('route');version=data.get('version')
        if route not in ORDER or type(version)!=int:return
        selector=self.selectors[p]
        if selector.fixed!='auto' and selector.fixed!=route:return
        if route not in self.t.available(p):return
        leader=int(self.me)<p;item=self.switches.get(p)
        if kind=='switch_prepare' and not leader and version>self.switch_version[p]:
            self.switches[p]=dict(route=route,version=version,stage='ready',at=now)
            self.send(p,'switch_ready',data,True)
        elif kind=='switch_ready' and leader and item and item['version']==version and item['route']==route and item['stage']=='prepare':
            item['stage']='commit';self.send(p,'switch_commit',data,True)
        elif kind=='switch_commit' and not leader and item and item['version']==version and item['route']==route:
            self.commit(p,route,version,now);self.send(p,'switch_done',data,True)
        elif kind=='switch_done' and leader and item and item['version']==version and item['route']==route and item['stage']=='commit':
            self.commit(p,route,version,now)

    def commit(self,p,route,version,now):
        old=self.t.selected.get(p)
        if old and old!=route:self.overlap[p]=(old,now+.5)
        self.t.selected[p]=route;self.selectors[p].commit(route,now);self.switch_version[p]=version
        self.switches.pop(p,None)
        self.t.event(f'{self.members[str(p)]["player_id"]} 游戏线路切换为 {route}')
        self.t.record('route_commit',peer=str(p),route=route,previous=old,revision=version)

    def tick(self,now):
        if self.cancelled:
            for key,item in list(self.outbox.items()):
                if item[0]['kind']!='removed' or now-item[2]>10:del self.outbox[key];continue
                if now-item[1]>=.5:self.transmit(key[0],item[0]);item[1]=now
            return
        if now-self.last_offer>=1:
            self.last_offer=now
            for sid,item in list(self.invites.items()):
                if now-item['at']>120:del self.invites[sid];continue
                self.boot(sid,'invite',dict(peer=self.members[self.me],room=self.room,nonce=item['nonce']),item['peer'])
            for sid,item in list(self.offers.items()):
                if now-item['at']>120:del self.offers[sid];continue
                if item.get('accepted') and self.host!=sid:self.boot(sid,'accept',{'nonce':item['nonce']},item['peer'])
            for sid,item in list(self.awaiting.items()):
                if now-item['at']>120:del self.awaiting[sid];continue
                self.boot(sid,'welcome',dict(config=self.config(),nonce=item['nonce']),item['peer'])
        local=self.t.measurements()
        for p,selector in list(self.selectors.items()):
            available=set(self.t.available(p));remote=self.remote.get(p,{})
            fresh=now-self.remote_at.get(p,-1e9)<4
            both=available & set(remote.get('available',[])) if fresh else set()
            scores={r:quality(local.get(str(p),{}).get(r),remote.get('links',{}).get(r)) for r in ORDER}
            self.controls[p].choose(available,scores,now)
            round_id=int(now//PERIOD) if 6<=now%PERIOD<8 else None
            target=selector.choose(scores,both,now,round_id)
            item=self.switches.get(p)
            if item and now-item['at']>8:
                del self.switches[p]
                for key,out in list(self.outbox.items()):
                    if key[0]==p and out[0]['kind'].startswith('switch_'):del self.outbox[key]
            if target and target!=self.t.selected.get(p) and int(self.me)<p and p not in self.switches and self.controls[p].current:
                version=max(self.switch_version[p]+1,int(now*1000))
                self.switches[p]=dict(route=target,version=version,stage='prepare',at=now)
                self.send(p,'switch_prepare',dict(route=target,version=version),True)
        if now-self.last_health>=1:
            self.last_health=now
            for p in self.selectors:
                self.send(p,'health',dict(links=local.get(str(p),{}),available=self.t.available(p),candidates=self.t.candidates(),
                    telemetry=self.t.public_edges() if self.monitor and str(p)==self.host else {}))
        if self.me==self.host and now-self.last_state>=5:
            self.last_state=now;self.broadcast()
        for key,item in list(self.outbox.items()):
            if now-item[1]>=.5:
                self.transmit(key[0],item[0]);item[1]=now
            if now-item[2]>30:del self.outbox[key]

    def public(self):
        return dict(room=self.room,host=self.host,self=self.me,revision=self.revision,
            members=[{k:v for k,v in d.items() if k!='token'} for d in self.members.values()],
            game_fixed=dict(self.game_fixed),control_route=self.control_route,control_fixed=dict(self.control_fixed),monitor=self.monitor,redundancy=self.redundancy,
            offers=[dict(steam=s,player_id=o['peer']['player_id']) for s,o in self.offers.items() if not o.get('accepted')],
            invites=[dict(steam=s,player_id=o['peer']['player_id']) for s,o in self.invites.items()],error=self.error,
            sync_pending=[d['player_id'] for sid,d in self.members.items() if sid!=self.me and self.remote_revision.get(int(sid),0)<self.revision] if self.me==self.host else [])
