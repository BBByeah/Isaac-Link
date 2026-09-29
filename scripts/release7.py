"""Build artifacts and Ed25519 signatures. Private key lives outside the checkout."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.version import __version__

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--init-key',action='store_true');parser.add_argument('--key',type=Path,
        default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'IsaacLinkPublisher'/'release-ed25519.pem');parser.add_argument('--out',type=Path,default=ROOT/'release');args=parser.parse_args()
    key_path=args.key.resolve()
    if key_path.is_relative_to(ROOT):raise SystemExit('The signing key must be outside the repository.')
    if args.init_key:
        if not key_path.exists():
            key_path.parent.mkdir(parents=True,exist_ok=True)
            key_path.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key=serialization.load_pem_private_key(key_path.read_bytes(),password=None)
        (ROOT/'isaac_link/release_public_key.txt').write_text(key.public_key().public_bytes_raw().hex()+'\n',encoding='ascii')
        print('Publisher public key installed. Private key remains outside the checkout.');return
    key=serialization.load_pem_private_key(key_path.read_bytes(),password=None)
    expected=(ROOT/'isaac_link/release_public_key.txt').read_text().strip()
    if key.public_key().public_bytes_raw().hex()!=expected:raise SystemExit('Signing key does not match client trust root.')
    app=ROOT/'dist/Isaac-Link';out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'dist/updater.exe',app/'updater.exe')
    (app/'.isaac-link-install.json').write_text(json.dumps(dict(product='Isaac-Link',version=__version__)),encoding='utf-8')
    for name in ('README.md','LICENSE'):shutil.copy2(ROOT/name,app/name)
    shutil.copytree(ROOT/'licenses',app/'licenses',dirs_exist_ok=True)
    (app/'docs').mkdir(exist_ok=True)
    for name in ('V0.7.0.md','server-deployment.md'):shutil.copy2(ROOT/'docs'/name,app/'docs'/name)
    if (ROOT/'docs/images').exists():shutil.copytree(ROOT/'docs/images',app/'docs/images',dirs_exist_ok=True)
    archive=out/f'Isaac-Link-client-v{__version__}.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(app.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(app).as_posix())
    server_archive=out/f'Isaac-Link-server-v{__version__}.zip'
    with zipfile.ZipFile(server_archive,'w',zipfile.ZIP_DEFLATED) as z:
        for folder in ('server','isaac_link'):
            names=['__init__.py','version.py','routing.py','server_code.py','protocol7.py','transport.py','network_priority.py'] if folder=='isaac_link' else [p.name for p in (ROOT/folder).glob('*.py')]
            for name in names:z.write(ROOT/folder/name,f'{folder}/{name}')
        z.write(ROOT/'docs/server-deployment.md','docs/server-deployment.md');z.write(ROOT/'LICENSE','LICENSE')
    payload=dict(version=__version__,protocol=8,platform='windows-x64',size=archive.stat().st_size,
        urls=[f'https://github.com/BBByeah/Isaac-Link/releases/download/v{__version__}/{archive.name}'],
        notes='原生深色桌面、Steam 组队、STUN 打洞、每对玩家持续自动选路、可选签名更新。',
        package_signature=base64.b64encode(key.sign(archive.read_bytes())).decode())
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    wrapper=dict(payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw)).decode())
    (out/'update.json').write_text(json.dumps(wrapper),encoding='utf-8')
    print('Signed client, server and update.json packaged. NOT published.')

if __name__=='__main__':main()
