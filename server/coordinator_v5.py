"""Version 5 room lifecycle; legacy clients continue using their existing rooms."""
import argparse
import re
import ipaddress
import secrets
import time
from isaac_link.version import __version__
from server.coordinator_server import Coordinator,serve

def player_id(value):
    value=str(value).strip().upper()
    if not re.fullmatch('[A-Z]{5}',value):raise ValueError('玩家 ID 必须是五个英文字母，例如 WHEAT。')
    return value

class CoordinatorV5(Coordinator):
    def decorate_room(self,r):
        r.setdefault('epoch',secrets.token_hex(16));r.setdefault('monitor',True)
        modern=any(self.sessions[sid].get('protocol',4)>=6 for sid in r.get('members',{}).values())
        r.setdefault('redundancy','window4' if modern else 'copy5');r.setdefault('telemetry',{})
        r.setdefault('lan_ips',{})

    def reset_room(self,r):
        self.decorate_room(r)
        r['lan_ips']={k:v for k,v in r['lan_ips'].items() if k in r.get('members',{})}
        r.update(epoch=secrets.token_hex(16),reports={},telemetry={},test=0,candidates=[],plan={},selection={},fixed={},error='',switch_at={})
        r['revision']+=1
        for sid in r['members'].values():self.sessions[sid]['enabled']=False

    def detach(self,s):
        old=self.rooms.get(s['room'])
        if not old:return
        old['members'].pop(s['steam'],None)
        if not old['members']:self.rooms.pop(s['room'],None)
        else:
            if old['host']==s['steam']:old['host']=next(iter(old['members']))
            self.reset_room(old)

    def fresh(self,s):
        self.detach(s);name=secrets.token_hex(12);s['room']=name;s['enabled']=False
        self.rooms[name]=dict(host=s['steam'],members={s['steam']:s['sid']},revision=0)
        self.reset_room(self.rooms[name])

    def handle(self,path,d):
        with self.lock:
            if path=='/register':
                protocol=int(d.get('protocol',4))
                name=player_id(d.get('player_id','')) if protocol>=5 else None
                if name and any(x.get('player_id')==name and time.monotonic()-x['seen']<120 for x in self.sessions.values()):
                    raise ValueError('这个五字母 ID 正在使用，请选择另一个。')
                result=super().handle(path,d);s=self.sessions[result['sid']]
                s.update(protocol=protocol,player_id=name)
                self.decorate_room(self.room(s))
                if protocol>=6:self.room(s)['redundancy']='window4'
                result.update(server_version=__version__,max_protocol=7)
                return result
            s=self.auth(d)
            if s.get('protocol',4)<5:return super().handle(path,d)
            r=self.room(s);self.decorate_room(r)
            if path=='/lan':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以分配局域网地址。')
                if any(self.sessions[sid].get('protocol',4)<7 for sid in r['members'].values()):raise ValueError('局域网线路需要全员更新到 0.6.5。')
                peer=str(d.get('steam',''));value=str(d.get('ip','')).strip()
                if peer not in r['members']:raise ValueError('成员不在当前队伍。')
                if value:
                    try:ip=ipaddress.IPv4Address(value)
                    except ValueError:raise ValueError('请输入有效的 IPv4 地址。') from None
                    if ip.is_loopback or ip.is_multicast or ip.is_unspecified or int(ip)>=0xf0000000:raise ValueError('请输入成员的实际局域网或 Radmin IPv4 地址。')
                    value=str(ip)
                    if any(k!=peer and v==value for k,v in r['lan_ips'].items()):raise ValueError('这个地址已分配给其他成员。')
                if r['lan_ips'].get(peer,'')!=value:
                    if r['test'] and not r['selection']:raise ValueError('请等待线路测试完成后再修改地址。')
                    if value:r['lan_ips'][peer]=value
                    else:
                        if any(route=='lan' and peer in key.split(':') for key,route in r['plan'].items()):raise ValueError('请先将该成员的局域网线路切换到其他线路，再清空地址。')
                        r['lan_ips'].pop(peer,None)
                    r['reports']={};r['telemetry']={}
                path='/poll';d={**d,'report':{},'enabled':s['enabled']}
            if path=='/route' and d.get('route')=='lan':
                if any(str(d.get(k,'')) not in r['lan_ips'] for k in ('a','b')):raise ValueError('请先给两位成员填写局域网地址。')
            if path=='/new-room':
                self.fresh(s);r=self.room(s);path='/poll';d={**d,'report':{},'enabled':False}
            elif path=='/add':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以添加成员；也可以先新建组。')
                other=self.sessions.get(self.codes.get(d.get('code','')))
                if not other or time.monotonic()-other['seen']>30:raise ValueError('连接码不存在或对方不在线。')
                if other['steam'] in r['members']:raise ValueError('该玩家已在这个组中。')
                if other.get('protocol',4)<5:raise ValueError('请对方更新到 0.5 后再加入新界面的队伍。')
                if (other.get('protocol',4)>=7)!=(s.get('protocol',4)>=7):raise ValueError('请全员更新到 0.6.5 后组队。')
                if (other.get('protocol',4)>=6)!=(s.get('protocol',4)>=6):
                    raise ValueError('四帧冗余需要全员使用 0.6.4 或更新版本，请先统一客户端版本。')
                if len(r['members'])>=4:raise ValueError('最多四人；请先移出一位玩家。')
                self.detach(other);other['room']=s['room'];r['members'][other['steam']]=other['sid']
                self.reset_room(r);path='/poll';d={**d,'report':{},'enabled':False}
            elif path=='/kick':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以移出成员。')
                sid=r['members'].get(str(d.get('steam')))
                if not sid or sid==s['sid']:raise ValueError('请选择其他成员；离开当前组请使用新建组。')
                self.fresh(self.sessions[sid]);path='/poll';d={**d,'report':{},'enabled':False}
            elif path=='/settings':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以修改全组设置。')
                if 'monitor' in d:
                    if type(d['monitor']) is not bool:raise ValueError('监视开关无效')
                    r['monitor']=d['monitor'];r['telemetry']={}
                if 'redundancy' in d:
                    allowed=('off','copy5','copy10','window4') if s.get('protocol',4)>=6 else ('off','copy5','copy10')
                    if d['redundancy'] not in allowed:raise ValueError('冗余档位无效')
                    r['redundancy']=d['redundancy']
                path='/poll';d={**d,'report':{},'enabled':s['enabled']}
            elif path=='/test':
                if r['host']!=s['steam']:raise ValueError('只有主持人可以开始测试。')
                if len(r['members'])<2:raise ValueError('先添加至少一位队友。')
                # Retest in the same group without requiring process restart.
                fixed=dict(r['fixed']);self.reset_room(r);r['fixed']=fixed
            if path=='/poll' and d.get('epoch',r['epoch'])!=r['epoch']:
                d={**d,'report':{},'telemetry':None,'enabled':False}
            if path=='/poll' and r['monitor'] and isinstance(d.get('telemetry'),dict):
                # Bound data size at HTTP layer; only retain this player's newest sample.
                r['telemetry'][s['steam']]={'at':time.time(),'data':d['telemetry']}
            result=super().handle(path,d)
            if path=='/leave':return result
            r=self.room(s)
            result.update(room=s['room'],epoch=r['epoch'],monitor=r['monitor'],redundancy=r['redundancy'])
            for member in result['members']:
                member['player_id']=self.sessions[r['members'][member['steam']]].get('player_id')
                member['lan_ip']=r['lan_ips'].get(member['steam'],'')
            result['telemetry']=dict(r['telemetry']) if r['host']==s['steam'] and r['monitor'] else {}
            if r['host']!=s['steam']:result['reports']={}
            return result

    def remove(self,sid):
        s=self.sessions.get(sid)
        if s and s.get('protocol',4)>=5:
            self.detach(s);self.codes.pop(s['code'],None);self.sessions.pop(sid,None)
        else:super().remove(sid)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cert',required=True);p.add_argument('--key',required=True)
    p.add_argument('--port',type=int,default=27668);p.add_argument('--udp-port',type=int,default=27667)
    a=p.parse_args();serve(a.cert,a.key,port=a.port,udp_port=a.udp_port,state_factory=CoordinatorV5)
