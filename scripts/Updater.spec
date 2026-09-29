from pathlib import Path
root=Path(SPECPATH).parent
a=Analysis([str(root/'scripts/updater_launcher.py')],pathex=[str(root)],datas=[(str(root/'isaac_link/release_public_key.txt'),'isaac_link')],excludes=['PySide6','frida','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='updater',console=False,upx=False)
