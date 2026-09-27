"""Package only listed public files; never copy a user's runtime directory."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
VERSION='0.6.2'
out=ROOT/'release';out.mkdir(exist_ok=True)
exe=ROOT/'dist/以撒联机助手.exe'
if not exe.is_file():raise SystemExit('Build Isaac-Link.spec first.')
with zipfile.ZipFile(out/f'Isaac-Link-client-v{VERSION}.zip','w',zipfile.ZIP_DEFLATED) as z:
    z.write(exe,exe.name)
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','licenses/FRIDA-COPYING.txt'):
        z.write(ROOT/name,name)
with zipfile.ZipFile(out/f'Isaac-Link-server-v{VERSION}.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in ('coordinator_private.py','coordinator_v5.py','coordinator_server.py','routing.py','server_setup.py','server_code.py','docs/server-deployment.md','LICENSE'):
        z.write(ROOT/name,name)
print('Client and server ZIPs written to release/.')
