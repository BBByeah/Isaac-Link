# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
root=Path(SPECPATH).parent
a=Analysis([str(root/'scripts/launcher.py')],pathex=[str(root)],binaries=[],datas=[(str(root/'isaac_link/hook7.js'),'isaac_link'),(str(root/'isaac_link/chevron.svg'),'isaac_link'),(str(root/'isaac_link/release_public_key.txt'),'isaac_link')],
           hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['playwright','tkinter','monitor'],noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='以撒联机助手',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,upx_exclude=[],runtime_tmpdir=None,console=False,disable_windowed_traceback=False,
        argv_emulation=False,target_arch=None,codesign_identity=None,entitlements_file=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='Isaac-Link')
