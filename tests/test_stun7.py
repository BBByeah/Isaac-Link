import socket
import struct
import unittest
from isaac_link.stun import COOKIE,parse,request,Discovery,parse_servers

class Stun(unittest.TestCase):
    def response(self,tid):
        value=struct.pack('!BBHI',0,1,45678^(COOKIE>>16),int.from_bytes(socket.inet_aton('8.8.8.8'),'big')^COOKIE)
        return struct.pack('!HHI12s',0x101,12,COOKIE,tid)+struct.pack('!HH',0x20,8)+value
    def test_xor_mapping_and_transaction_match(self):
        tid=b'a'*12;raw=self.response(tid)
        self.assertEqual(parse(raw,tid),('8.8.8.8',45678));self.assertIsNone(parse(raw,b'b'*12))
        self.assertIsNone(parse(raw[:-1],tid));self.assertEqual(len(request(tid)),20)
    def test_only_outstanding_transaction_from_expected_server(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            d=Discovery(sock,());tid=b'a'*12;d.pending[tid]=(('1.1.1.1',3478),0)
            d.receive(self.response(tid),('9.9.9.9',3478));self.assertFalse(d.found)
            d.receive(self.response(tid),('1.1.1.1',3478));self.assertIn(('8.8.8.8',45678),d.found)

    def test_configured_servers_are_bounded(self):
        self.assertEqual(parse_servers('stun.example.com:3478\nstun.example.com:3478'),[('stun.example.com',3478)])
        for invalid in ('','https://example.com:443','host:70000','host:not-a-port'):
            with self.assertRaises(ValueError):parse_servers(invalid)

if __name__=='__main__':unittest.main()
