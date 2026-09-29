"""Synthetic visual/performance checks, explicitly separate from game measurements."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
OUT=ROOT/'ui-validation';OUT.mkdir(exist_ok=True)

def native_worker(scale):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from isaac_link.desktop import Window,THEMES
    from isaac_link.desktop_backend import DesktopBackend
    temp=tempfile.TemporaryDirectory();app=QApplication([])
    # Windows' offscreen plugin does not enumerate system fonts automatically.
    for name in ('msyh.ttc','msyhbd.ttc','segoeui.ttf','segoeuib.ttf'):
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    w=Window(DesktopBackend(Path(temp.name)),demo=True);w.show()
    timings=[];last=time.perf_counter();began=last
    def tick():
        nonlocal last
        now=time.perf_counter();timings.append((now-last)*1000);last=now
    timer=QTimer();timer.timeout.connect(tick);timer.start(250)
    def screenshots():
        for theme in THEMES:
            w.theme.setCurrentIndex(w.theme.findData(theme));app.processEvents();w.grab().save(str(OUT/f'desktop-{theme}-{scale}.png'))
    QTimer.singleShot(1500,screenshots)
    def finish():
        (OUT/f'native-timers-{scale}.json').write_text(json.dumps(timings),encoding='utf-8');w.close()
    QTimer.singleShot(16000,finish);app.exec();temp.cleanup()

def legacy_worker():
    import threading
    from playwright.sync_api import sync_playwright
    from scripts.verify_web_ui import Fixture
    from isaac_link.browser_app import make_server
    fixture=Fixture();fixture.connected();server,token=make_server(fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1320,'height':860},device_scale_factor=1)
        page.goto(f'http://127.0.0.1:{server.server_port}/#{token}')
        page.wait_for_selector('.edge-card')
        page.evaluate('window.checkTimes=[];window.lastCheck=performance.now();setInterval(()=>{let n=performance.now();checkTimes.push(n-lastCheck);lastCheck=n},250)')
        page.wait_for_timeout(15000)
        page.screenshot(path=str(OUT/'legacy-four-player.png'))
        (OUT/'legacy-timers.json').write_text(json.dumps(page.evaluate('checkTimes')),encoding='utf-8')
        browser.close()
    server.shutdown();server.server_close()

def benchmark():
    import psutil
    results={}
    for mode in ('legacy','native'):
        env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_SCALE_FACTOR':'1'}
        started=time.monotonic();process=subprocess.Popen([sys.executable,__file__,'--worker',mode],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        root=psutil.Process(process.pid);samples=[];cpu={}
        while process.poll() is None:
            rss=0
            try:family=[root]+root.children(recursive=True)
            except psutil.Error:family=[]
            for p in family:
                try:
                    rss+=p.memory_info().rss;times=p.cpu_times();cpu[p.pid]=times.user+times.system
                except psutil.Error:pass
            if time.monotonic()-started>=4:samples.append(rss/1024/1024)
            time.sleep(.25)
        stdout,stderr=process.communicate()
        if process.returncode:raise RuntimeError(stderr.decode(errors='replace'))
        elapsed=time.monotonic()-started
        results[mode]=dict(elapsed_s=elapsed,cpu_seconds=sum(cpu.values()),average_one_core_percent=100*sum(cpu.values())/elapsed,
                           peak_working_set_mb=max(samples,default=0),samples=len(samples))
    results['scope']='Synthetic 4 players / 6 links, legacy Edge headless vs native Qt offscreen. Includes process-family startup. No Steam, game, real network, or GPU-window claim.'
    (OUT/'performance.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worker',choices=['native','legacy']);parser.add_argument('--scale',default='100');args=parser.parse_args()
    if args.worker=='native':native_worker(args.scale)
    elif args.worker=='legacy':legacy_worker()
    else:benchmark()
