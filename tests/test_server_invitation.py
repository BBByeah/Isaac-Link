import unittest
from isaac_link.server_code import encode_server_code,decode_server_code
from server.coordinator_private import PrivateCoordinator

class InvitationTests(unittest.TestCase):
    def test_roundtrip_and_rejection(self):
        c=dict(host='example.com',port=27668,udp_port=27667,sha256='a'*64,access_key='b'*64)
        self.assertEqual(decode_server_code(encode_server_code(c)),c)
        for value in ('','ISAAC-SERVER1-bad','https://example.com'):
            with self.assertRaises(ValueError):decode_server_code(value)
    def test_registration_requires_key(self):
        s=PrivateCoordinator('b'*64)
        d=dict(steam='123',ipv6='',port=27667,token='a'*32,protocol=5,player_id='WHEAT')
        for key in ('','c'*64):
            with self.assertRaises(ValueError):s.handle('/register',{**d,'access_key':key})
        self.assertEqual(len(s.sessions),0)
        result=s.handle('/register',{**d,'access_key':'b'*64})
        self.assertIn('code',result)

if __name__=='__main__':unittest.main()
