'use strict';
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const token=location.hash.slice(1)||sessionStorage.getItem('isaac-token')||'';
let pageController=null,pageLeaving=false;
async function holdPage(){
 pageController=new AbortController();
 try{
  const response=await fetch('/api/page',{headers:{'X-Isaac-Token':token},signal:pageController.signal});
  if(!response.ok)return;
  const reader=response.body.getReader();while(!(await reader.read()).done){}
 }catch(e){}
 if(!pageLeaving)setTimeout(holdPage,250);
}
window.addEventListener('pagehide',()=>{pageLeaving=true;pageController?.abort()});
window.addEventListener('pageshow',e=>{if(e.persisted){pageLeaving=false;holdPage()}});
holdPage();
sessionStorage.setItem('isaac-token',token);history.replaceState(null,'',location.pathname);
const routes={ipv6:['IPv6 直连','#9ed57b'],ipv4:['IPv4 打洞','#82b7ef'],lan:['局域网','#69d7d0'],relay:['服务器中转','#e4b77b'],steam:['Steam 原生','#ba9ae2'],auto:['自动备用','#adb7ac']};
let guideShown=false;
let state={},selected=null,lastGraph='',localBusy=false,localAction='',historyKey='',series={},sampleAt=0,stopped=false;
let stateController=null,refreshId=0,pollTimer=null,chartMax=200,routeKey='';
const actionTitles={connect:'正在连接游戏…',disconnect:'正在断开…','new-room':'正在新建组…',add:'正在添加队友…',test:'正在测试线路…',route:'正在切换线路…',settings:'正在保存设置…',kick:'正在移出成员…',capture:'正在处理抓包…',theme:'正在切换主题…',guide:'正在保存设置…','network-check':'正在检测 IPv6…','network-settings':'正在打开网络设置…','open-captures':'正在打开文件夹…',exit:'正在退出…'};
const busyText=()=>localBusy?(actionTitles[localAction]||'正在处理…'):(state.busy||'');
actionTitles.lan='正在保存局域网地址…';
function setHTML(el,html){if(el._html!==html){el.innerHTML=html;el._html=html}}
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2500)}
function error(message){$('error').textContent=message;$('error').hidden=!message}
async function api(path,data,signal){const r=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'X-Isaac-Token':token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined,signal:signal||AbortSignal.timeout(15000)});const body=await r.json();if(!r.ok)throw Error(body.error||'请求失败');return body}
async function act(action,args={}){
 if(localBusy||state.busy||stopped)return;
 clearTimeout(pollTimer);stateController?.abort();refreshId++;
 localBusy=true;localAction=action;state.error='';error('');render();
 try{
  await api('action',{action,...args});
  if(action==='exit'){stopped=true;$('connection').textContent='正在退出';$('activity').textContent='助手正在退出，可以关闭此页面。';document.querySelectorAll('button').forEach(b=>b.disabled=true);return}
  await refresh();
 }catch(e){error(e.message)}finally{
  localBusy=false;localAction='';if(!stopped){render();schedulePoll(150)}
 }
}
const host=()=>state.room?.host===state.self;
const name=id=>state.room?.members?.find(p=>p.steam===id)?.player_id||'未命名';
const edge=(a,b)=>[a,b].sort((a,b)=>BigInt(a)<BigInt(b)?-1:1).join(':');
function svg(tag,attrs={},text){const el=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el}
function drawGraph(){
 const room=state.room||{},members=room.members||[],signature=JSON.stringify([members,room.plan,room.fixed,room.host,room.epoch,state.self,host()]);
 if(signature===lastGraph)return;lastGraph=signature;const graph=$('graph');graph.replaceChildren();$('empty-graph').hidden=members.length>0;
 if(!members.length)return;
 const positions=members.length===1?[[380,205]]:members.length===2?[[195,205],[565,205]]:members.length===3?[[380,90],[195,300],[565,300]]:[[200,95],[560,95],[560,315],[200,315]];
 members.forEach((a,i)=>members.slice(i+1).forEach((b,j)=>{
  const [x1,y1]=positions[i],[x2,y2]=positions[j+i+1],key=edge(a.steam,b.steam),route=room.plan?.[key],color=routes[route]?.[1]||'#465449';
  graph.append(svg('line',{x1,y1,x2,y2,stroke:color,'stroke-width':1.5,'stroke-dasharray':route?'':'5 7',opacity:.7}));
  const hit=svg('line',{x1,y1,x2,y2,class:'edge-hit',tabindex:0,role:'button','aria-label':`${a.player_id} 与 ${b.player_id} 的连接线路`});
  const open=()=>openRoute(a.steam,b.steam);hit.addEventListener('click',open);hit.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}});graph.append(hit);
  const t=members.length===4&&Math.abs(x2-x1)>250&&Math.abs(y2-y1)>150?.30:.5;
  const cx=x1+(x2-x1)*t,cy=y1+(y2-y1)*t,label=(room.fixed?.[key]?'● ':'')+(routes[route]?.[0]||'待测试');
  graph.append(svg('rect',{x:cx-51,y:cy-12,width:102,height:24,rx:12,fill:'#191e1b',stroke:'#364237','pointer-events':'none'}));
  graph.append(svg('text',{x:cx,y:cy+4,fill:color,'font-size':13,'text-anchor':'middle','pointer-events':'none'},label));
 }));
 members.forEach((p,i)=>{
  const [x,y]=positions[i],g=svg('g',{class:'node',transform:`translate(${x},${y})`});
  g.append(svg('circle',{r:37,fill:'#202a21',stroke:p.steam===state.self?'#a4d378':'#52664d','stroke-width':1.5}));
  g.append(svg('text',{y:5,fill:'#d9edcc','text-anchor':'middle','font-size':16,'font-weight':600,'letter-spacing':1.3},p.player_id));
  g.append(svg('circle',{cx:27,cy:26,r:5,fill:p.enabled?'#b3e781':'#586259',stroke:'#191e1b','stroke-width':2}));
  g.append(svg('text',{y:58,fill:'#95a798','text-anchor':'middle','font-size':13},[p.steam===state.self?'你':'',p.steam===room.host?'主持人':'',p.enabled?'已接管':'等待连接'].filter(Boolean).join(' · ')));
  graph.append(g);
 });
 if(selected&&!members.some(x=>x.steam===selected[0]))closeRoute();
}
function closeRoute(){selected=null;routeKey='';$('route-menu').hidden=true}
function openRoute(a,b){selected=[a,b];renderRoute()}
function renderRoute(){
 if(!selected)return;const [a,b]=selected,key=edge(a,b),menu=$('route-menu');
 const keyChanged=routeKey!==key;
 if(keyChanged){menu.replaceChildren();routeKey=key;const title=document.createElement('h3');title.textContent=`${name(a)} ↔ ${name(b)}`;menu.append(title)}menu.hidden=false;
 for(const [route,[label]]of Object.entries(routes)){
  let button=menu.querySelector(`[data-route="${route}"]`);
  if(!button){button=document.createElement('button');button.dataset.route=route;button.append(document.createElement('span'),document.createElement('span'));button.onclick=()=>{act('route',{a,b,route});closeRoute()};menu.append(button)}
  const locked=state.room.fixed?.[key],active=route==='auto'?!locked:locked===route;
  button.className=active?'active':'';button.disabled=!host()||!!busyText()||(state.room?.offline&&(![a,b].includes(state.self)||!['ipv6','steam','auto'].includes(route)));
  if(route==='lan'&&![a,b].every(id=>state.room.members.some(p=>p.steam===id&&p.lan_ip)))button.disabled=true;
  const measures=[state.room.reports?.[a]?.links?.[b]?.[route]?.p95,state.room.reports?.[b]?.links?.[a]?.[route]?.p95].filter(x=>Number.isFinite(x));
  button.children[0].textContent=label;button.children[1].textContent=route==='auto'?'':measures.length?Math.round(Math.max(...measures))+' ms':'未测';
 }
 if(!keyChanged)return;
 const hint=document.createElement('small');hint.textContent=host()?'固定后仅使用所选线路；自动档允许断线切换。':'由主持人修改线路。';menu.append(hint);
 const close=document.createElement('button');close.className='quiet';close.textContent='关闭';close.onclick=closeRoute;menu.append(close);
}
function fmt(x){return Number.isFinite(x)?Math.round(x):'—'}
function spark(values,color,max,now,label){
 let path='',pen=false,previous=0;
 for(const [at,v]of values){
  if(!Number.isFinite(v)){pen=false;continue}
  const x=34+Math.max(0,Math.min(1,1-(now-at)/120000))*242,y=48-Math.min(max,v)/max*42;
  if(at-previous>6000)pen=false;
  path+=`${pen?'L':'M'}${x.toFixed(1)},${y.toFixed(1)} `;pen=true;previous=at;
 }
 return `<span class="chart-axis"><span>${max}</span><span>0</span></span><svg class="spark" data-max="${max}" viewBox="34 0 246 56" preserveAspectRatio="none" role="img" aria-label="${label}，统一纵轴 0 至 ${max} 毫秒，最近两分钟"><path class="chart-grid" d="M34 6H276M34 27H276M34 48H276"/><path class="chart-data" d="${path}" fill="none" stroke="${color}" stroke-width="1.7"/></svg>`;
}
function monitor(){
 const room=state.room||{};$('monitor-section').hidden=!host()||!state.self||!!room.offline;
 if(!host())return;
 $('monitor-toggle').checked=room.monitor!==false;$('monitor-toggle').disabled=!!busyText();
 const enabled=room.monitor!==false;$('monitor-off').hidden=enabled;$('monitor-cards').hidden=!enabled;$('monitor-explanation').hidden=!enabled;
 if(!enabled){series={};return}
 if(historyKey!==room.epoch){historyKey=room.epoch;series={};sampleAt=0;chartMax=200}
 const now=Date.now(),sample=now-sampleAt>=2900;if(sample)sampleAt=now;
 const members=room.members||[],models=[];
 members.forEach((a,i)=>members.slice(i+1).forEach(b=>{
  const key=edge(a.steam,b.steam),route=room.plan?.[key],s=series[key]||(series[key]={rtt:[],gap:[]});
  const rtts=[[a,b],[b,a]].map(([source,dest])=>{
   const fresh=room.telemetry?.[source.steam]?.at,health=room.reports?.[source.steam]?.health?.[dest.steam];
   return fresh&&Date.now()/1000-fresh<9&&health?.active!==false?room.reports?.[source.steam]?.links?.[dest.steam]?.[route]?.rtt:null;
  }).filter(Number.isFinite);
  const reads=[[a,b],[b,a]].map(([source,dest])=>{const report=room.telemetry?.[dest.steam];return report&&Date.now()/1000-report.at<9?report.data?.inputs?.[source.steam]:null});
  const active=reads.filter(x=>x&&x.idle_ms<2500),gaps=active.map(x=>x.gap_p95_ms).filter(Number.isFinite),rtt=rtts.length?Math.max(...rtts):null,gap=gaps.length?Math.max(...gaps):null;
  if(sample){s.rtt.push([now,rtt]);s.gap.push([now,gap]);for(const values of [s.rtt,s.gap])while(values.length&&values[0][0]<now-120000)values.shift()}
  const note=reads.map((r,i)=>`${i?b.player_id:a.player_id} → ${i?a.player_id:b.player_id}：${r&&r.idle_ms<2500?fmt(r.gap_p95_ms)+' ms':'暂无新输入'}`).join(' · ');
  models.push({key,a,b,route,s,rtt,gap,note});
 }));
 const peak=Math.max(200,...models.flatMap(m=>[...m.s.rtt,...m.s.gap].map(x=>Number.isFinite(x[1])?x[1]:0)));
 chartMax=Math.max(chartMax,Math.ceil(peak/100)*100);
 $('monitor-explanation').textContent=`绿色：往返延迟 RTT · 蓝色：输入间隔 P95｜所有图统一 0–${chartMax} ms，最近 2 分钟`;
 const container=$('monitor-cards'),keys=models.map(m=>m.key).join(',');
 if(container.dataset.keys!==keys){
  container.dataset.keys=keys;
  container.innerHTML=models.map(m=>`<article class="edge-card" data-edge="${m.key}"><div class="edge-title"><strong></strong><span></span></div><div class="metric-row"><div><small>双向较高 RTT</small><b class="rtt-value"></b></div><div><small>输入间隔 P95</small><b class="gap-value"></b></div></div><div class="chart-slot rtt-chart"></div><div class="chart-slot gap-chart"></div><div class="edge-foot"></div></article>`).join('')||'<p class="muted small">添加一位队友后开始显示连接监视。</p>';
 }
 for(const m of models){
  const card=container.querySelector(`[data-edge="${m.key}"]`);
  card.querySelector('strong').textContent=`${m.a.player_id} ↔ ${m.b.player_id}`;card.querySelector('.edge-title span').textContent=routes[m.route]?.[0]||'待测试';
  setHTML(card.querySelector('.rtt-value'),`${fmt(m.rtt)}<em>ms</em>`);setHTML(card.querySelector('.gap-value'),`${fmt(m.gap)}<em>ms</em>`);
  setHTML(card.querySelector('.rtt-chart'),spark(m.s.rtt,'#9ed57b',chartMax,sampleAt,'往返延迟'));
  setHTML(card.querySelector('.gap-chart'),spark(m.s.gap,'#82b7ef',chartMax,sampleAt,'输入间隔'));
  const foot=card.querySelector('.edge-foot');foot.textContent=m.note;foot.title=m.note;
 }
}
let playersKey='';
function renderPlayers(members,room,busy){
 const key=JSON.stringify([room.host,state.self,!!room.offline,members.map(p=>[p.steam,p.player_id])]);
 if(key!==playersKey){
  playersKey=key;
  $('players').innerHTML=members.map(p=>`<div class="player" data-player="${esc(p.steam)}"><div class="player-name">${esc(p.player_id)}<small>${p.steam===room.host?'主持人':'队友'}${p.steam===state.self?' · 你':''}</small></div>${host()&&p.steam!==state.self?`<button class="quiet kick" data-peer="${esc(p.steam)}" aria-label="移出 ${esc(p.player_id)}">移出</button>`:'<span></span>'}<div class="lan-editor"><input class="lan-ip" aria-label="${esc(p.player_id)} 局域网 IP" placeholder="局域网 / Radmin IP" maxlength="15" autocomplete="off" spellcheck="false"><button class="lan-save">保存</button></div></div>`).join('');
  for(const row of $('players').children){
   const input=row.querySelector('.lan-ip'),button=row.querySelector('.lan-save');
   input.oninput=()=>{input.dataset.dirty='1'};
   button.onclick=()=>act('lan',{steam:row.dataset.player,ip:input.value.trim()});
   input.onkeydown=e=>{if(e.key==='Enter'&&!button.disabled)button.click()};
  }
 }
 for(const row of $('players').children){
  const member=members.find(p=>p.steam===row.dataset.player),input=row.querySelector('.lan-ip'),button=row.querySelector('.lan-save');
  const value=member.lan_ip||'';
  if(input.value===value)input.dataset.dirty='';
  if(!input.dataset.dirty&&document.activeElement!==input)input.value=value;
  input.disabled=busy||!host()||!!room.offline;button.hidden=!host()||!!room.offline;button.disabled=busy;
 }
}
function render(){
  document.getElementById("app-version").textContent=state.version || "";
 renderGuide();
 const theme=state.profile?.theme||"green";document.documentElement.dataset.theme=theme;$("theme").value=theme;$("theme").disabled=!!busyText();
 const room=state.room||{},members=room.members||[],busy=!!busyText(),connected=!!state.self,connecting=localAction==='connect'||state.busy==='正在连接游戏…';
 $('connection').textContent=connecting?'正在连接游戏…':state.failure?'连接已断开':connected?'游戏已连接':'尚未连接游戏';$('connection').classList.toggle('ready',connected&&!state.failure&&!connecting);
 $('disconnect').hidden=!connected;$('connect').textContent=connecting?'连接中…':state.failure?'重新连接':'连接游戏';$('connect').disabled=busy||(connected&&!state.failure);$('disconnect').disabled=busy;
 $('connect').setAttribute('aria-busy',String(connecting));
 if(document.activeElement!==$('name')&&state.profile?.player_id)$('name').value=state.profile.player_id;
 $('name').disabled=connected||busy;
 $('own-code').textContent=state.code||'连接游戏后生成';$('copy').disabled=!state.code;
 $('member-count').textContent=`${members.length} / 4`;
 for(const id of ['test','add','redundancy'])$(id).disabled=busy||!connected||!host();
 $('new-room').disabled=busy||!connected;$('address').disabled=busy||connected;
 $('capture').disabled=busy||!connected;$('capture').textContent=state.capture?.active?'停止并保存':'开始抓包';
 $('capture-status').textContent=state.capture?.active?`已记录 ${(state.capture.records||0).toLocaleString()} 条`:state.capture?.path?'已保存到本地抓包文件夹':'未抓包';
 $('session-status').textContent=!connected?'先连接游戏':state.failure?'请重新连接游戏':room.error?room.error:room.test&&!room.selection?`正在测试线路 · ${Math.min(29,Math.floor(room.elapsed||0))} / 29 秒`:members.length<2?'等待队友加入':members.every(p=>p.enabled)?'已就绪，可进官方房间':room.plan_complete?'正在连接':'等待选择线路';
 renderPlayers(members,room,busy);
 document.querySelectorAll('.kick').forEach(b=>{b.disabled=busy;b.onclick=()=>act('kick',{steam:b.dataset.peer})});
 $('redundancy').value=room.redundancy||'off';
 $('activity').textContent=busy?busyText():state.control_failure?'协调连接正在恢复':'准备就绪';
 if(state.error)error(state.error);$('logs').textContent=(state.logs||[]).join('\n');
 const options=state.addresses||[];if($('address').options.length!==options.length+1){$('address').innerHTML='<option value="">自动选择</option>'+options.map(ip=>`<option value="${esc(ip)}">${esc(ip)}</option>`).join('')}
 $('server-code').disabled=busy||connected;
 $('test').textContent=room.offline?'启用直连':'自动测试';
 if(room.offline){for(const id of ['redundancy','capture','new-room'])$(id).disabled=true;document.querySelectorAll('.kick').forEach(b=>b.disabled=true)}
 drawGraph();monitor();if(selected)renderRoute();
}
async function refresh(){
 stateController?.abort();const controller=new AbortController();stateController=controller;const id=++refreshId;
 const timeout=setTimeout(()=>controller.abort(),5000);
 try{const next=await api('state',undefined,controller.signal);if(id!==refreshId||stopped)return;state=next;render()}
 catch(e){if(id===refreshId&&e.name!=='AbortError')error('助手连接中断：'+e.message)}finally{clearTimeout(timeout)}
}
$('connect').onclick=()=>act('connect',{player_id:$('name').value,ip:$('address').value,server_code:$('server-code').value});
let serverCodeEdited=false;
$('server-code').addEventListener('input',()=>{serverCodeEdited=true});
api('server-code').then(data=>{if(!serverCodeEdited)$('server-code').value=data.code||''}).catch(()=>{});
$('disconnect').onclick=()=>act('disconnect');$('new-room').onclick=()=>{closeRoute();act('new-room')};$('add').onclick=()=>act('add',{code:$('join-code').value});
$('join-code').onkeydown=e=>{if(e.key==='Enter')$('add').click()};$('test').onclick=()=>act('test');$('redundancy').onchange=()=>act('settings',{redundancy:$('redundancy').value});
$('monitor-toggle').onchange=()=>act('settings',{monitor:$('monitor-toggle').checked});$('capture').onclick=()=>act('capture');$('open-captures').onclick=()=>act('open-captures');
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(state.code);toast('连接码已复制')}catch(e){error('复制失败，请从连接码处手动复制。')}};
$('close-log').onclick=()=>$('log-panel').hidden=true;
$('show-log').onclick=()=>$('log-panel').hidden=!$('log-panel').hidden;$('exit').onclick=()=>act('exit');
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeRoute();$('log-panel').hidden=true}});
function schedulePoll(delay){clearTimeout(pollTimer);if(!stopped)pollTimer=setTimeout(loop,delay)}
async function loop(){if(stopped||localBusy)return;await refresh();schedulePoll(state.busy?200:document.hidden?2000:1000)}loop();

$("theme").onchange=()=>act("theme",{theme:$("theme").value});

function renderGuide(){
 const status=state.network?.status||'checking';
 const messages={
  checking:['正在检测 IPv6…',''],
  available:['已检测到公网 IPv6 地址','是否能与队友直连，还需要双方连接后验证。'],
  disabled:['当前已连接网卡未启用 IPv6','可打开网络设置，右键正在使用的 Wi-Fi 或以太网 → 属性，勾选“Internet 协议版本 6 (TCP/IPv6)”。启用后点击重新检测。'],
  no_address:['未检测到公网 IPv6 地址','可在网络设置中检查：右键正在使用的网络 → 属性，勾选“Internet 协议版本 6 (TCP/IPv6)”。若已勾选，还需要路由器和运营商提供 IPv6。没有 IPv6 也可使用 Steam；填服务器码后还可尝试 IPv4 打洞或中转。'],
  unknown:['未能完成 IPv6 检测','可以打开网络设置检查 IPv6，或点击重新检测。']
 };
 const message=messages[status]||messages.unknown;
 $('ipv6-result').textContent=message[0];$('ipv6-detail').textContent=message[1];
 $('network-check').disabled=status==='checking'||!!state.busy;
 if(!guideShown&&state.network&&status!=='checking'){
  guideShown=true;
  if(!state.profile?.hide_startup_guide){$('hide-guide').checked=false;$('startup-guide').showModal()}
 }
}
$('show-guide').onclick=()=>{guideShown=true;$('hide-guide').checked=!!state.profile?.hide_startup_guide;$('startup-guide').showModal()};
$('network-settings').onclick=()=>act('network-settings');
$('network-check').onclick=()=>act('network-check');
$('guide-done').onclick=async()=>{await act('guide',{hide:$('hide-guide').checked});if(!state.error)$('startup-guide').close()};
