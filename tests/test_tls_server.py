import datetime
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time
import unittest
from server.coordinator_server import CoordinatorHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'OK')


@unittest.skipUnless(importlib.util.find_spec('cryptography'),'Certificate generation requires test-only cryptography')
class TLSConcurrency(unittest.TestCase):
    def setUp(self):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost-test')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(key,hashes.SHA256())
        folder=Path(self.temp.name)
        (folder/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);self.context.load_cert_chain(folder/'cert.pem',folder/'key.pem')

    def request(self,port,timeout=1):
        conn=http.client.HTTPSConnection('127.0.0.1',port,timeout=timeout,context=ssl._create_unverified_context())
        try:conn.request('GET','/');r=conn.getresponse();return r.status,r.read()
        finally:conn.close()

    def test_old_listener_reproduces_global_handshake_block(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.socket=self.context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        stalled=socket.create_connection(server.server_address);time.sleep(.05)
        try:
            with self.assertRaises(TimeoutError):self.request(server.server_port,.2)
        finally:stalled.close();server.shutdown();thread.join(2);server.server_close()

    def test_stalled_handshakes_and_headers_do_not_block_normal_client(self):
        server=CoordinatorHTTPServer(('127.0.0.1',0),Handler,self.context,connection_timeout=.4)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();sockets=[]
        try:
            for _ in range(6):sockets.append(socket.create_connection(server.server_address))
            partial=ssl._create_unverified_context().wrap_socket(socket.create_connection(server.server_address),server_hostname='localhost')
            sockets.append(partial);partial.sendall(b'GET / HTTP/1.1\r\n')
            self.assertEqual(self.request(server.server_port),(200,b'OK'))
            time.sleep(.5)
            sockets[0].settimeout(.5);self.assertEqual(sockets[0].recv(1),b'')
            self.assertEqual(self.request(server.server_port),(200,b'OK'))
        finally:
            for sock in sockets:sock.close()
            server.shutdown();thread.join(2);server.server_close()
