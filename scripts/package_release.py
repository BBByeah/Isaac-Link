"""Package only listed public files; never copy a user's runtime directory."""
from pathlib import Path
import zipfile
import sys
import hashlib

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.version import __version__ as VERSION
out=ROOT/'release';out.mkdir(exist_ok=True)
exe=ROOT/'dist/以撒联机助手.exe'
if not exe.is_file():raise SystemExit('Build Isaac-Link.spec first.')
with zipfile.ZipFile(out/f'Isaac-Link-client-v{VERSION}.zip','w',zipfile.ZIP_DEFLATED) as z:
    z.write(exe,exe.name)
    for name in ('README.md','LICENSE','licenses/THIRD_PARTY_NOTICES.md','licenses/FRIDA-COPYING.txt'):
        z.write(ROOT/name,name)
with zipfile.ZipFile(out/f'Isaac-Link-server-v{VERSION}.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in ('server/__init__.py','server/coordinator_private.py','server/coordinator_v5.py','server/coordinator_server.py','server/server_setup.py','isaac_link/__init__.py','isaac_link/version.py','isaac_link/routing.py','isaac_link/server_code.py','docs/server-deployment.md','LICENSE'):
        z.write(ROOT/name,name)
print('Client and server ZIPs written to release/.')

assets=[out/f"Isaac-Link-{kind}-v{VERSION}.zip" for kind in ("client","server")]
(out/"SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets),encoding="utf-8")
