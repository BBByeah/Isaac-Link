import hmac
import struct
import unittest
from server.coordinator7 import Coordinator7

class Relay(unittest.TestCase):
    def test_registration_discovery_room_isolation_and_restart(self):
        server=Coordinator7('secret')
        with self.assertRaises(ValueError):server.handle('/v7/register',dict(access_key='wrong',protocol=8,steam='1',room='a'*24))
        def register(sid,room):return server.handle('/v7/register',dict(access_key='secret',protocol=8,steam=str(sid),room=room))
        def packet(s,magic,body=b''):
            head=magic+bytes.fromhex(s['sid']);return head+hmac.digest(bytes.fromhex(s['auth']),head+body,'sha256')+body
        a=register(1,'a'*24);b=register(2,'a'*24);c=register(3,'c'*24)
        for i,s in enumerate((a,b,c),1):self.assertIsNotNone(server.udp(packet(s,b'I7H2'),('127.0.0.1',1000+i)))
        result=server.udp(packet(a,b'I7R2',struct.pack('!Q',2)+b'payload'),('127.0.0.1',1001))
        self.assertEqual(result,(b'payload',('127.0.0.1',1002)))
        self.assertIsNone(server.udp(packet(a,b'I7R2',struct.pack('!Q',3)+b'payload'),('127.0.0.1',1001)))
        self.assertIsNone(server.udp(packet(a,b'I7R2',struct.pack('!Q',2)+b'payload'),('127.0.0.1',9999)))
        newer=register(1,'a'*24)
        with self.assertRaises(ValueError):server.handle('/v7/alive',a)
        self.assertTrue(server.handle('/v7/alive',newer)['ok'])

if __name__=='__main__':unittest.main()
