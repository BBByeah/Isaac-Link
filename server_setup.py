"""Run on your own Linux server; generates local TLS and invitation files."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import ssl
import subprocess
from server_code import encode_server_code

def main():
    p=argparse.ArgumentParser(description='Generate a private Isaac server invitation')
    p.add_argument('--host',required=True,help='Public IPv4 address or hostname')
    p.add_argument('--port',type=int,default=27668);p.add_argument('--udp-port',type=int,default=27667)
    a=p.parse_args();os.umask(0o077)
    cert=Path('server.crt');key=Path('server.key');access=Path('access.key')
    if cert.exists()!=key.exists():raise SystemExit('Certificate/key incomplete; restore the pair first.')
    if not cert.exists():
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','3650','-subj','/CN=IsaacLink'],check=True)
    if not access.exists():access.write_text(secrets.token_hex(32),encoding='ascii')
    config=dict(host=a.host,port=a.port,udp_port=a.udp_port,sha256=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest(),access_key=access.read_text().strip())
    Path('server-connection-code.txt').write_text(encode_server_code(config),encoding='utf-8')
    print('Saved server-connection-code.txt; share only with invited players.')

if __name__=='__main__':main()
