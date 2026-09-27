"""Server-free manual peer exchange, using the original IPv6/native Steam path."""
import threading
from types import SimpleNamespace
from runtime import Runtime
from transport import Peer
from capture import Capture
from routing import edge

class OfflineRuntime(Runtime):
    def __init__(self,log,name):
        super().__init__(log);self.control=SimpleNamespace(name=name)
        self.code='';self.room={};self.capture=Capture();self.control_failure='';self.enabled=False
        self.names={};self.forced={}
    def start(self,ip,port):
        self.code=super().start(ip,port)
        original=self.transport.native
        self.transport.native=lambda peer: self.forced.get(peer)=='steam' or (peer not in self.forced and original(peer))
        self.names[self.transport.local.steam]=self.control.name
        self.refresh_room()
        return self.code
    def refresh_room(self):
        local=self.transport.local;snap=self.transport.snapshot()['peers']
        members=[dict(steam=str(local.steam),player_id=self.control.name,enabled=self.enabled)]
        plan={}
        for peer in self.transport.peers:
            native=self.transport.native(peer)
            members.append(dict(steam=str(peer),player_id=self.names.get(peer,'ID'+str(peer)[-5:]),enabled=bool(snap.get(str(peer),{}).get('active'))))
            plan[edge(local.steam,peer)]='steam' if native else 'ipv6'
        self.room=dict(host=str(local.steam),members=members,plan=plan,fixed=plan,monitor=False,redundancy='off',plan_complete=self.enabled,offline=True)
    def add(self,code):
        peer=Peer.parse(code)
        if peer.steam==self.transport.local.steam:raise ValueError('不能添加自己的连接码。')
        if len(self.transport.peers)>=3 and peer.steam not in self.transport.peers:raise ValueError('最多四人。')
        self.transport.add(peer);self.refresh_room()
        self.log('已添加队友；请对方也添加你的连接码，然后双方点击启用直连。')
    def test(self):
        self.enable();self.enabled=True;self.refresh_room()
    def set_route(self,a,b,route):
        local=str(self.transport.local.steam)
        if local not in (a,b):raise ValueError('无服务器模式只能设置自己与队友之间的线路。')
        peer=int(b if a==local else a)
        if peer not in self.transport.peers:raise ValueError('请先添加队友。')
        if route not in ('ipv6','steam','auto'):raise ValueError('IPv4 打洞和中转需要服务器连接码。')
        if route=='ipv6' and not (self.transport.local.ip and self.transport.peers[peer].ip):raise ValueError('双方都需要公网 IPv6。')
        if route=='auto':self.forced.pop(peer,None)
        else:self.forced[peer]=route
        self.refresh_room();self.log('线路已修改；请队友选择相同线路，并在双方点击启用直连。')
    def settings(self,**data):raise ValueError('全队监视和输入副本请在服务器组队模式下使用。')
    def new_room(self):raise ValueError('无服务器模式请断开后重新连接游戏，以清空本次队友。')
    def kick(self,steam):raise ValueError('无服务器模式请断开后重新添加队友。')
    def start_capture(self,folder):raise ValueError('完整抓包请在服务器组队模式下使用。')
    def stop_capture(self):return self.capture.stop()
