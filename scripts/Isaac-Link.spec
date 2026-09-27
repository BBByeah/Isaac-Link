# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
root=Path(SPECPATH).parent
a=Analysis([str(root/'scripts/launcher.py')],pathex=[str(root)],binaries=[],datas=[(str(root/'isaac_link/hook_v5.js'),'isaac_link'),(str(root/'isaac_link/hook.js'),'isaac_link'),(str(root/'isaac_link/web'),'isaac_link/web')],
           hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['playwright','tkinter','monitor'],noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='以撒联机助手',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=True,upx_exclude=[],runtime_tmpdir=None,console=False,disable_windowed_traceback=False,
        argv_emulation=False,target_arch=None,codesign_identity=None,entitlements_file=None)
