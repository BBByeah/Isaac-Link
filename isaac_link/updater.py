"""Separate executable: validate, stage, swap, confirm startup, or roll back."""
import argparse
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from isaac_link.updates import verified_manifest, verify_package,version

EXE='以撒联机助手.exe'

def extract(archive,destination):
    destination=Path(destination).resolve();total=0;names=set()
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist())>10000:raise ValueError('更新包文件过多')
        for info in bundle.infolist():
            name=info.filename
            p=PurePosixPath(name)
            if not name or '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or any(x.rstrip(' .')!=x for x in p.parts):raise ValueError('更新包路径无效')
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('更新包不允许符号链接')
            if name.lower() in names:raise ValueError('更新包包含重复文件')
            names.add(name.lower());total+=info.file_size
            if total>1536*1024*1024:raise ValueError('更新包解压大小超限')
            target=(destination/name).resolve()
            if not target.is_relative_to(destination):raise ValueError('更新包路径越界')
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with bundle.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
    for required in (EXE,'updater.exe','.isaac-link-install.json'):
        if not (destination/required).is_file():raise ValueError('更新包缺少 '+required)

def wait_parent(pid,timeout=60):
    if os.name!='nt':return
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x00100000,False,pid)
    if not handle:return
    try:
        if kernel.WaitForSingleObject(handle,int(timeout*1000))!=0:raise TimeoutError('主程序仍在运行，未安装更新')
    finally:kernel.CloseHandle(handle)

def install(job,launch=None,timeout=30):
    root=Path(job['root']).resolve();archive=Path(job['archive']).resolve()
    if root==root.parent or not (root/EXE).is_file() or not (root/'.isaac-link-install.json').is_file():raise ValueError('不是有效的 Isaac-Link 安装目录')
    manifest=verified_manifest(Path(job['manifest']).read_bytes());verify_package(archive,manifest)
    installed=json.loads((root/'.isaac-link-install.json').read_text(encoding='utf-8'))
    if version(manifest['version'])<=version(installed['version']):raise ValueError('拒绝安装相同或更旧的版本')
    stage=Path(tempfile.mkdtemp(prefix=root.name+'.staged-',dir=root.parent)).resolve()
    extract(archive,stage)
    marker=json.loads((stage/'.isaac-link-install.json').read_text(encoding='utf-8'))
    if marker.get('version')!=manifest['version']:raise ValueError('更新包版本与清单不一致')
    wait_parent(int(job['pid']))
    backup=root.with_name(root.name+'.previous-'+str(time.time_ns()))
    failed=root.with_name(root.name+'.failed-'+str(time.time_ns()))
    # Resolved siblings, no shell commands or recursive deletion of user directories.
    if any(p.parent!=root.parent for p in (stage,backup,failed)):raise ValueError('更新目录越界')
    root.rename(backup)
    process=None
    try:
        stage.rename(root)
        for name in ('logs','captures'):
            if (backup/name).exists():shutil.copytree(backup/name,root/name,dirs_exist_ok=True)
        ready=Path(tempfile.gettempdir())/('IsaacLink-ready-'+str(time.time_ns()))
        command=[str(root/EXE),'--update-ready',str(ready)]
        process=launch(command) if launch else subprocess.Popen(command,cwd=root)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if ready.is_file():return backup
            if process.poll() is not None:break
            time.sleep(.1)
        raise RuntimeError('新版未能启动，正在恢复旧版')
    except Exception:
        if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        if root.exists():root.rename(failed)
        backup.rename(root)
        if launch is None:subprocess.Popen([str(root/EXE)],cwd=root)
        raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args()
    job_path=Path(args.job)
    try:install(json.loads(job_path.read_text(encoding='utf-8')))
    except Exception as e:
        (job_path.parent/'update-error.txt').write_text(str(e),encoding='utf-8')
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,str(e),'Isaac-Link 更新未完成',0x10)

if __name__=='__main__':main()
