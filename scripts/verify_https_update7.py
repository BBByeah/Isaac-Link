"""Verified local HTTPS download -> real signed ZIP -> standalone frozen updater.

The old-version marker is synthetic. This does not publish or simulate a GitHub release.
"""
import base64
from datetime import datetime,timedelta,timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request
from unittest.mock import patch
import psutil
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.updates import UpdateManager,verified_manifest,verify_package
from isaac_link.updater import extract,EXE

def main():
    out=ROOT/'ui-validation';out.mkdir(exist_ok=True)
    fixture=Path(tempfile.mkdtemp(prefix='https-update-',dir=out));web=fixture/'web';web.mkdir()
    archive=ROOT/'release/Isaac-Link-client-v0.7.0.zip'
    manifest=verified_manifest((ROOT/'release/update.json').read_bytes());verify_package(archive,manifest)
    # Serve the actual package without modifying its contents or signature.
    os.link(archive,web/archive.name)
    tlskey=Ed25519PrivateKey.generate();subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Isaac-Link local update test')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tlskey.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(tlskey,None))
    certfile=fixture/'local-cert.pem';keyfile=fixture/'local-key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(tlskey.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(web)))
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certfile,keyfile)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'https://127.0.0.1:{server.server_port}'
    manifest['urls']=[base+'/'+archive.name]
    publisher=Path(os.environ['LOCALAPPDATA'])/'IsaacLinkPublisher/release-ed25519.pem'
    signing_key=serialization.load_pem_private_key(publisher.read_bytes(),password=None)
    payload=json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    wrapper=dict(payload=base64.b64encode(payload).decode(),signature=base64.b64encode(signing_key.sign(payload)).decode())
    (web/'update.json').write_text(json.dumps(wrapper),encoding='utf-8')
    manager=UpdateManager(fixture/'download-profile',sources=(base+'/update.json',))
    trusted=ssl.create_default_context(cafile=str(certfile))
    local_opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=trusted))
    try:
        with patch('isaac_link.updates.__version__','0.6.9'),patch('urllib.request.urlopen',side_effect=local_opener.open):
            manager.check();assert manager.status=='available'
            manager.download();assert manager.status=='ready' and manager.progress==100
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
    app=fixture/'app';extract(archive,app)
    (app/'.isaac-link-install.json').write_text('{"version":"0.6.9","fixture":true}',encoding='utf-8')
    (app/'captures').mkdir();(app/'captures/keep.txt').write_text('keep',encoding='ascii')
    (app/'logs').mkdir(exist_ok=True);(app/'logs/keep.txt').write_text('keep',encoding='ascii')
    env={**os.environ,'LOCALAPPDATA':str(fixture/'user-profile'),'QT_QPA_PLATFORM':'offscreen'}
    profile=Path(env['LOCALAPPDATA'])/'IsaacLink';profile.mkdir(parents=True)
    settings=dict(player_id='ABCDE',theme='wine',check_updates=False)
    (profile/'profile.json').write_text(json.dumps(settings),encoding='utf-8')
    job=fixture/'job.json';job.write_text(json.dumps(dict(root=str(app),archive=str(manager.archive),manifest=str(manager.folder/'update.json'),pid=0)),encoding='utf-8')
    process=subprocess.Popen([str(ROOT/'dist/updater.exe'),'--job',str(job)],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process.wait(timeout=45)
        assert process.returncode==0
        assert not (fixture/'update-error.txt').exists()
        assert json.loads((app/'.isaac-link-install.json').read_text())['version']=='0.7.0'
        assert (app/'captures/keep.txt').read_text()=='keep' and (app/'logs/keep.txt').read_text()=='keep'
        assert json.loads((profile/'profile.json').read_text())==settings
        assert len(list(fixture.glob('app.previous-*')))==1
        report=dict(result='PASS',https_certificate_verified=True,manifest_signature_verified=True,package_signature_verified=True,
                    download='100%',frozen_updater=True,frozen_desktop_started=True,profile_preserved=True,logs_preserved=True,captures_preserved=True,
                    scope='Local HTTPS with explicitly trusted temporary certificate; actual signed 0.7.0 artifact; synthetic old version; not GitHub publication')
        (out/'https-update.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        for p in psutil.process_iter(['exe']):
            try:
                if p.info['exe'] and Path(p.info['exe']).resolve()==(app/EXE).resolve():p.terminate();p.wait(timeout=10)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass

if __name__=='__main__':main()
