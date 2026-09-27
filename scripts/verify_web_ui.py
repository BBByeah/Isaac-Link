"""Optional Edge/Playwright UI check, with isolated delayed fixture responses."""
import copy
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from isaac_link.browser_app import make_server
from isaac_link.version import __version__
from playwright.sync_api import sync_playwright

class Fixture:
    def __init__(self):
        self.saved_server_code='SAVED-UI-FIXTURE'
        self.actions=[]
        self.value=dict(version=__version__,profile={'hide_startup_guide':True},network={'status':'available'},addresses=[],busy='',error='',logs=[],self='',code='',failure='',control_failure='',capture={},room={})

    def state(self):
        value=copy.deepcopy(self.value)
        for t in value['room'].get('telemetry',{}).values():t['at']=time.time()
        return value

    def submit(self,data):
        self.actions.append(data)
        if data['action']=='lan':
            for member in self.value['room']['members']:
                if member['steam']==data['steam']:member['lan_ip']=data['ip']
            return
        time.sleep(.8)  # The button must react before even this response arrives.
        self.value['busy']='正在连接游戏…'
        def complete():
            time.sleep(.5);self.connected();self.value['busy']=''
        threading.Thread(target=complete,daemon=True).start()

    def connected(self):
        members=[dict(steam=str(i),player_id=n,enabled=True) for i,n in enumerate(('WHEAT','MELON','ISAAC','AZAZL'),1)]
        reports={};telemetry={};plan={}
        for a in members:
            reports[a['steam']]={'links':{}};telemetry[a['steam']]={'at':time.time(),'data':{'inputs':{}}}
            for b in members:
                if a==b:continue
                delay=50 if {a['steam'],b['steam']}=={'1','2'} else 480
                reports[a['steam']]['links'][b['steam']]={r:dict(rtt=delay,p95=delay) for r in ('ipv6','ipv4','relay','steam')}
                telemetry[a['steam']]['data']['inputs'][b['steam']]=dict(idle_ms=0,gap_p95_ms=33)
                plan[':'.join(sorted((a['steam'],b['steam']))) ]='ipv6'
        self.value.update(self='1',code='UI-FIXTURE-NOT-A-CONNECTION-CODE',room=dict(host='1',members=members,epoch='fixture',monitor=True,redundancy='window4',plan_complete=True,plan=plan,fixed={},reports=reports,telemetry=telemetry))

def main():
    fixture=Fixture();server,token=make_server(fixture)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    out=Path(__file__).resolve().parent.parent/'ui-validation';out.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1366,'height':660},bypass_csp=True);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#{token}')
            page.wait_for_function("document.getElementById('app-version').textContent.length>0")
            page.wait_for_function("document.getElementById('server-code').value==='SAVED-UI-FIXTURE'")
            page.locator('#name').fill('WHEAT')
            feedback=page.evaluate("""()=>{const b=document.getElementById('connect'),at=performance.now();b.click();b.click();return {ms:performance.now()-at,text:b.textContent,disabled:b.disabled}}""")
            assert feedback['text']=='连接中…' and feedback['disabled'],feedback
            assert feedback['ms']<100,feedback
            page.wait_for_selector('.edge-card',timeout=5000)
            assert len(fixture.actions)==1
            page.wait_for_function("document.getElementById('connection').textContent==='游戏已连接'")
            field=page.get_by_role('textbox',name='WHEAT 局域网 IP')
            field.fill('26.1.2.3')
            page.evaluate('render()')
            assert field.input_value()=='26.1.2.3'
            page.locator('[data-player="1"] .lan-save').click()
            page.wait_for_function("state.room.members[0].lan_ip==='26.1.2.3' && !localBusy && !state.busy")
            page.get_by_role('textbox',name='MELON 局域网 IP').fill('26.4.5.6')
            page.locator('[data-player="2"] .lan-save').click()
            page.wait_for_function("state.room.members[1].lan_ip==='26.4.5.6' && !localBusy && !state.busy")
            page.evaluate("""()=>{for(const s of Object.values(series)){const at=Date.now();s.rtt=Array.from({length:40},(_,i)=>[at-(39-i)*3000,s.rtt.at(-1)[1]+Math.sin(i)*12]);s.gap=Array.from({length:40},(_,i)=>[at-(39-i)*3000,33+Math.sin(i)*5])}sampleAt=Date.now();render()}""")
            assert page.locator('.spark').evaluate_all('(xs)=>new Set(xs.map(x=>x.dataset.max)).size===1')
            assert page.locator('.spark').first.get_attribute('data-max')=='500'
            # Same height and numerical scale across every edge and metric.
            assert page.locator('.spark').evaluate_all('(xs)=>Math.max(...xs.map(x=>x.getBoundingClientRect().height))-Math.min(...xs.map(x=>x.getBoundingClientRect().height))<1')
            assert page.evaluate("""()=>{const c=document.querySelector('.edge-card'),s=c.querySelector('svg');render();return c===document.querySelector('.edge-card')&&s===c.querySelector('svg')}""")
            page.evaluate("openRoute('1','2')")
            assert page.locator('[data-route="lan"]').is_enabled()
            assert page.evaluate("""()=>{const b=document.querySelector('[data-route=ipv4]');state.room.reports['1'].links['2'].ipv4.p95=90;render();return b===document.querySelector('[data-route=ipv4]')}""")
            page.keyboard.press('Escape')
            for w,h in ((800,600),(960,640),(1366,660),(1920,1080)):
                page.set_viewport_size({'width':w,'height':h})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight'),(w,h)
                assert page.locator('.edge-card').evaluate_all('(xs)=>xs.every(x=>x.scrollHeight<=x.clientHeight)'),(w,h)
                page.screenshot(path=str(out/f'v064-ui-{w}x{h}.png'))
            # Missing data creates a break, rather than connecting across it.
            assert page.evaluate("""()=>{const now=Date.now(),s=spark([[now-6000,20],[now-3000,null],[now,30]],'x',500,now,'test');return !s.includes('L')}""")
            assert not errors,errors
            browser.close()
            print(f'PASS: immediate feedback {feedback["ms"]:.1f} ms, one action, shared axes, stable DOM, missing-data gaps, four viewport sizes.')
    finally:
        server.page_stop.set();server.shutdown();thread.join();server.server_close()

if __name__=='__main__':main()
