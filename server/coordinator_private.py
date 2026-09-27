"""Standalone invitation-protected coordinator and UDP relay."""
import argparse
import hmac
from pathlib import Path
from server.coordinator_v5 import CoordinatorV5
from server.coordinator_server import serve

class PrivateCoordinator(CoordinatorV5):
    def __init__(self,access_key):
        super().__init__();self.access_key=access_key
    def handle(self,path,data):
        if path=='/register':
            value=data.get('access_key','')
            if not isinstance(value,str) or not hmac.compare_digest(value,self.access_key):
                raise ValueError('服务器连接码无效或已更换，请联系服务器管理员。')
        return super().handle(path,data)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--cert',required=True);p.add_argument('--key',required=True);p.add_argument('--access-key-file',required=True)
    p.add_argument('--port',type=int,default=27668);p.add_argument('--udp-port',type=int,default=27667)
    a=p.parse_args();key=Path(a.access_key_file).read_text().strip()
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise SystemExit('Invalid access key file')
    serve(a.cert,a.key,port=a.port,udp_port=a.udp_port,state_factory=lambda:PrivateCoordinator(key))
