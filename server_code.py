"""Portable server invitation format; contains connection access, never SSH credentials."""
import base64
import json
import re

PREFIX='ISAAC-SERVER1-'

def decode_server_code(value):
    value=str(value).strip()
    if len(value)>2048 or not value.startswith(PREFIX):raise ValueError('服务器连接码格式无效')
    try:
        raw=value[len(PREFIX):]
        data=json.loads(base64.b64decode(raw+'='*(-len(raw)%4),altchars=b'-_',validate=True))
        host=data['host'];port=data['port'];udp=data['udp_port'];pin=data['sha256'];key=data['access_key']
        if not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',host):raise ValueError()
        if type(port)!=int or type(udp)!=int or not 1<=port<=65535 or not 1<=udp<=65535:raise ValueError()
        if not isinstance(pin,str) or not re.fullmatch('[a-f0-9]{64}',pin):raise ValueError()
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key):raise ValueError()
        return dict(host=host,port=port,udp_port=udp,sha256=pin,access_key=key)
    except (ValueError,TypeError,KeyError):raise ValueError('服务器连接码内容无效') from None

def encode_server_code(config):
    result=PREFIX+base64.urlsafe_b64encode(json.dumps(config,separators=(',',':')).encode()).decode().rstrip('=')
    decode_server_code(result)
    return result
