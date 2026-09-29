"""Exercise the real frozen updater in an isolated disposable installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.updater import extract,EXE
from isaac_link.updates import verified_manifest,verify_package

def main():
    out=ROOT/'ui-validation';out.mkdir(exist_ok=True)
    fixture=Path(tempfile.mkdtemp(prefix='frozen-update-',dir=out))
    archive=ROOT/'release/Isaac-Link-client-v0.7.0.zip';manifest=ROOT/'release/update.json'
    verified=verified_manifest(manifest.read_bytes());verify_package(archive,verified)
    app=fixture/'app';extract(archive,app)
    # Fixture has current files but an older installation marker; this is a lifecycle test.
    (app/'.isaac-link-install.json').write_text(json.dumps({'version':'0.6.5','fixture':True}),encoding='utf-8')
    (app/'captures').mkdir();(app/'captures/keep.txt').write_text('preserve fixture evidence',encoding='ascii')
    job=fixture/'job.json';job.write_text(json.dumps(dict(root=str(app),archive=str(archive),manifest=str(manifest),pid=0)),encoding='utf-8')
    env={**os.environ,'LOCALAPPDATA':str(fixture/'profile'),'QT_QPA_PLATFORM':'offscreen'}
    process=subprocess.Popen([str(ROOT/'dist/updater.exe'),'--job',str(job)],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process.wait(timeout=45)
        if process.returncode:raise RuntimeError('Frozen updater exited with '+str(process.returncode))
        if (fixture/'update-error.txt').exists():raise RuntimeError((fixture/'update-error.txt').read_text(encoding='utf-8'))
        backups=list(fixture.glob('app.previous-*'))
        assert len(backups)==1,'No successful directory swap'
        assert json.loads((app/'.isaac-link-install.json').read_text())['version']=='0.7.0'
        assert (app/'captures/keep.txt').read_text()=='preserve fixture evidence'
        report=dict(result='PASS',scope='Real frozen updater and frozen desktop startup in an isolated copied install; synthetic old-version marker, no published download',
                    fixture=str(fixture),backup_retained=True,user_capture_preserved=True)
        (out/'frozen-update.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        target=(app/EXE).resolve()
        for p in psutil.process_iter(['pid','exe']):
            try:
                if p.info['exe'] and Path(p.info['exe']).resolve()==target:p.terminate();p.wait(timeout=10)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass

if __name__=='__main__':main()
