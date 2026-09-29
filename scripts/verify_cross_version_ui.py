"""Drive an unmodified 0.7.0 portable client through its actual update buttons."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil
from pywinauto import Desktop

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.updater import extract,EXE

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    out=ROOT/'ui-validation';record=out/'cross-version-fixture.json'
    if args.prepare:
        fixture=Path(tempfile.mkdtemp(prefix='cross-version-',dir=out));app=fixture/'app'
        extract(ROOT/'release/Isaac-Link-client-v0.7.0.zip',app)
        profile=fixture/'profile/IsaacLink';profile.mkdir(parents=True)
        settings=dict(player_id='ABCDE',theme='wine',check_updates=False)
        (profile/'profile.json').write_text(json.dumps(settings),encoding='utf-8')
        for folder in ('captures','logs'):
            (app/folder).mkdir(exist_ok=True);(app/folder/'keep.txt').write_text('preserve',encoding='ascii')
        env={**os.environ,'LOCALAPPDATA':str(fixture/'profile')}
        env.pop('QT_QPA_PLATFORM',None);env.pop('QT_SCALE_FACTOR',None)
        process=subprocess.Popen([str(app/EXE)],cwd=app,env=env)
        record.write_text(json.dumps(dict(fixture=str(fixture),pid=process.pid)),encoding='utf-8')
        time.sleep(4)
        window=Desktop(backend='uia').window(process=process.pid,title_re='Isaac-Link.*')
        window.wait('visible',timeout=20)
        print('Prepared actual 0.7.0 client. Buttons:',[b.window_text() for b in window.descendants(control_type='Button')],flush=True)
        return
    data=json.loads(record.read_text());fixture=Path(data['fixture']);app=fixture/'app';profile=fixture/'profile/IsaacLink'
    window=Desktop(backend='uia').window(process=data['pid'],title_re='Isaac-Link.*');window.wait('visible',timeout=20)
    window.child_window(title='检查更新',control_type='Button').invoke()
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        texts=[x.window_text() for x in window.descendants(control_type='Text')]
        if any('发现新版 0.7.2' in x for x in texts):break
        time.sleep(.5)
    else:raise AssertionError('Actual 0.7.0 did not detect 0.7.2: '+repr(texts))
    window.capture_as_image().save(str(out/'cross-version-detected.png'))
    print('PASS: actual 0.7.0 UI detected latest 0.7.2 directly.',flush=True)
    window.child_window(title='下载新版',control_type='Button').invoke()
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        install=window.child_window(title='安装并重启',control_type='Button')
        if install.exists() and install.is_enabled():break
        texts=[x.window_text() for x in window.descendants(control_type='Text')]
        if any('下载未完成' in x or '更新下载失败' in x for x in texts):raise AssertionError(repr(texts))
        time.sleep(1)
    else:raise TimeoutError('Actual client download did not complete')
    print('PASS: actual 0.7.0 UI downloaded and verified public 0.7.2 ZIP.',flush=True)
    install.invoke()
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        try:
            marker=json.loads((app/'.isaac-link-install.json').read_text())
            running=[p for p in psutil.process_iter(['exe']) if p.info['exe'] and Path(p.info['exe']).resolve()==(app/EXE).resolve()]
            if marker['version']=='0.7.2' and running:
                updated=Desktop(backend='uia').window(process=running[0].pid,title_re='Isaac-Link.*')
                if updated.exists() and updated.is_visible():
                    values=[x.window_text() for x in updated.descendants(control_type='Text')]
                    if '0.7.2' in values:break
        except (OSError,ValueError,psutil.Error):pass
        time.sleep(1)
    else:raise AssertionError('Updated 0.7.2 window did not appear')
    time.sleep(3);assert (app/'.isaac-link-install.json').exists()
    assert all((app/folder/'keep.txt').read_text()=='preserve' for folder in ('logs','captures'))
    settings=json.loads((profile/'profile.json').read_text());assert settings['player_id']=='ABCDE' and settings['theme']=='wine'
    backups=list(fixture.glob('app.previous-*'));assert len(backups)==1
    assert json.loads((backups[0]/'.isaac-link-install.json').read_text())['version']=='0.7.0'
    updated.capture_as_image().save(str(out/'cross-version-installed.png'))
    report=dict(result='PASS',from_version='0.7.0',skipped_version='0.7.1',to_version='0.7.2',method='Actual frozen client UI: check, download, install and restart',
                public_github_source=True,profile_preserved=True,logs_preserved=True,captures_preserved=True,backup_version='0.7.0')
    (out/'cross-version-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    updated.close()

if __name__=='__main__':main()
