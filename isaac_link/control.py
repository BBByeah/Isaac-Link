import hashlib
import http.client
import json
import ssl
from pathlib import Path

class Control:
    def __init__(self, config=None):
        self.config=config or {}
        self.credentials={}

    def call(self,path,**data):
        if not self.config:raise ValueError('请先填写服务器连接码。')
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
        conn=http.client.HTTPSConnection(self.config['host'],self.config['port'],context=ctx,timeout=4)
        try:
            conn.connect()
            actual=hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
            if actual!=self.config['sha256']:raise ConnectionError('协调服务器证书不匹配，未发送连接凭据。')
            if path=='/register' and self.config.get('access_key'):data={**data,'access_key':self.config['access_key']}
            conn.request('POST',path,json.dumps({**self.credentials,**data}),{'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(262145)
            if len(raw)>262144:raise ValueError('服务器响应过大')
            result=json.loads(raw)
            if response.status!=200:raise RuntimeError(result.get('error','服务器请求失败'))
            return result
        finally:conn.close()

    def register(self,steam,ipv6,port,token):
        r=self.call('/register',steam=str(steam),ipv6=ipv6,port=port,token=token.hex())
        self.credentials={k:r[k] for k in ('sid','auth')};return r['code']
