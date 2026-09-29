"""Versioned invitations and bounded authenticated control envelopes."""
import base64
import hmac
import ipaddress
import json
import secrets
import zlib
from isaac_link.transport import Peer

PROTOCOL=8
PREFIX='ISAAC7-'

def encode(value):return json.dumps(value,separators=(',',':'),sort_keys=True).encode('utf-8')

def descriptor(peer,name):
    return dict(steam=str(peer.steam),ipv6=peer.ip,port=peer.port,token=peer.token.hex(),player_id=name)

def peer_from(d):
    sid=int(d['steam']);port=d['port'];token=bytes.fromhex(d['token']);ip=d.get('ipv6','')
    if not 0<sid<2**64 or type(port)!=int or not 0<port<65536 or len(token)!=16:raise ValueError('玩家连接信息无效')
    if ip and not isinstance(ip,str):raise ValueError('IPv6 无效')
    return Peer(sid,ip,port,token)

def connection_code(d):return PREFIX+base64.urlsafe_b64encode(encode({'protocol':PROTOCOL,'peer':d})).decode().rstrip('=')

def parse_code(code):
    if not code.startswith(PREFIX):raise ValueError('需要 0.7.0 或兼容版本的连接码；不支持旧版混组。')
    if len(code)>1024:raise ValueError('连接码过长')
    try:
        tail=code[len(PREFIX):];value=json.loads(base64.b64decode(tail+'='*(-len(tail)%4),altchars=b'-_',validate=True))
        if value['protocol']!=PROTOCOL:raise ValueError()
        peer_from(value['peer']);return value['peer']
    except (KeyError,TypeError,ValueError) as e:raise ValueError('连接码无效或协议版本不兼容') from e

def bootstrap(value, token):
    data=b'I7J'+zlib.compress(encode(value))
    if len(data)>1176:raise ValueError('邀请数据过大')
    return data+hmac.digest(token,data,'sha512')[:24]

def read_bootstrap(raw,token,sender):
    if not 28<=len(raw)<=1200 or raw[:3]!=b'I7J':return None
    if not hmac.compare_digest(raw[-24:],hmac.digest(token,raw[:-24],'sha512')[:24]):return None
    try:
        dec=zlib.decompressobj();payload=dec.decompress(raw[3:-24],16385)
        if len(payload)>16384 or not dec.eof or dec.unused_data:return None
        value=json.loads(payload)
        if value.get('protocol')!=PROTOCOL or int(value['sender'])!=sender:return None
        return value
    except (ValueError,KeyError,TypeError,zlib.error):return None

def endpoint(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2:return None
    try:
        ip=ipaddress.IPv4Address(value[0]);port=value[1]
        if type(port)!=int or not 0<port<65536 or ip.is_unspecified or ip.is_multicast:return None
        return str(ip),port
    except (ValueError,TypeError):return None
