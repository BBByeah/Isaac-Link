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
const routes={ipv6:['IPv6 直连','#9ed57b'],ipv4:['IPv4 打洞','#82b7ef'],relay:['服务器中转','#e4b77b'],steam:['Steam 原生','#ba9ae2'],auto:['自动备用','#adb7ac']};
let guideShown=false;
let state={},selected=null,lastGraph='',localBusy=false,historyKey='',series={},sampleAt=0,stopped=false;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2500)}
function error(message){$('error').textContent=message;$('error').hidden=!message}
async function api(path,data){const r=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'X-Isaac-Token':token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});const body=await r.json();if(!r.ok)throw Error(body.error||'请求失败');return body}
async function act(action,args={}){if(localBusy||state.busy)return;localBusy=true;error('');try{await api('action',{action,...args});if(action==='exit'){stopped=true;$('connection').textContent='正在退出';$('activity').textContent='助手正在退出，可以关闭此页面。';document.querySelectorAll('button').forEach(b=>b.disabled=true);return}await refresh()}catch(e){error(e.message)}finally{localBusy=false}}
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
function closeRoute(){selected=null;$('route-menu').hidden=true}
function openRoute(a,b){selected=[a,b];renderRoute()}
function renderRoute(){
 if(!selected)return;const [a,b]=selected,key=edge(a,b),menu=$('route-menu');
 menu.replaceChildren();menu.hidden=false;const title=document.createElement('h3');title.textContent=`${name(a)} ↔ ${name(b)}`;menu.append(title);
 for(const [route,[label]]of Object.entries(routes)){
  const button=document.createElement('button'),locked=state.room.fixed?.[key],active=route==='auto'?!locked:locked===route;
  button.className=active?'active':'';button.disabled=!host()||state.busy||(state.room?.offline&&(![a,b].includes(state.self)||!['ipv6','steam','auto'].includes(route)));
  const measures=[state.room.reports?.[a]?.links?.[b]?.[route]?.p95,state.room.reports?.[b]?.links?.[a]?.[route]?.p95].filter(x=>Number.isFinite(x));
  button.innerHTML=`<span>${label}</span><span>${route==='auto'?'':measures.length?Math.round(Math.max(...measures))+' ms':'未测'}</span>`;
  button.onclick=()=>{act('route',{a,b,route});closeRoute()};menu.append(button);
 }
 const hint=document.createElement('small');hint.textContent=host()?'固定后仅使用所选线路；自动档允许断线切换。':'由主持人修改线路。';menu.append(hint);
 const close=document.createElement('button');close.className='quiet';close.textContent='关闭';close.onclick=closeRoute;menu.append(close);
}
function fmt(x){return Number.isFinite(x)?Math.round(x):'—'}
function spark(values,color){
 const good=values.filter(Number.isFinite);if(!good.length)return '<svg class="spark" viewBox="0 0 280 56"><path d="M0 40H280" stroke="#334034" stroke-dasharray="3 5"/></svg>';
 const max=Math.max(50,...good),points=values.map((v,i)=>Number.isFinite(v)?`${i*280/Math.max(1,values.length-1)},${50-v/max*43}`:null).filter(Boolean);
 return `<svg class="spark" viewBox="0 0 280 56" preserveAspectRatio="none"><path d="M0 50H280" stroke="#2c382e"/><polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="1.7"/></svg>`;
}
function monitor(){
 const room=state.room||{};$('monitor-section').hidden=!host()||!state.self||!!room.offline;
 if(!host())return;
 $('monitor-toggle').checked=room.monitor!==false;$('monitor-toggle').disabled=state.busy;
 const enabled=room.monitor!==false;$('monitor-off').hidden=enabled;$('monitor-cards').hidden=!enabled;$('monitor-explanation').hidden=!enabled;
 if(!enabled){series={};return}
 if(historyKey!==room.epoch){historyKey=room.epoch;series={};sampleAt=0}
 const now=Date.now(),sample=now-sampleAt>=2900;if(sample)sampleAt=now;
 const members=room.members||[],cards=[];
 members.forEach((a,i)=>members.slice(i+1).forEach(b=>{
  const key=edge(a.steam,b.steam),route=room.plan?.[key],s=series[key]||(series[key]={rtt:[],gap:[]});
  const rtts=[[a,b],[b,a]].map(([source,dest])=>{
   const fresh=room.telemetry?.[source.steam]?.at,health=room.reports?.[source.steam]?.health?.[dest.steam];
   return fresh&&Date.now()/1000-fresh<9&&health?.active!==false?room.reports?.[source.steam]?.links?.[dest.steam]?.[route]?.rtt:null;
  }).filter(Number.isFinite);
  const reads=[[a,b],[b,a]].map(([source,dest])=>{const report=room.telemetry?.[dest.steam];return report&&Date.now()/1000-report.at<9?report.data?.inputs?.[source.steam]:null});
  const active=reads.filter(x=>x&&x.idle_ms<2500),gaps=active.map(x=>x.gap_p95_ms).filter(Number.isFinite),rtt=rtts.length?Math.max(...rtts):null,gap=gaps.length?Math.max(...gaps):null;
  if(sample){s.rtt.push(rtt);s.gap.push(gap);if(s.rtt.length>40){s.rtt.shift();s.gap.shift()}}
  const note=reads.map((r,i)=>`${i?b.player_id:a.player_id} → ${i?a.player_id:b.player_id}：${r&&r.idle_ms<2500?fmt(r.gap_p95_ms)+' ms':'暂无新输入'}`).join(' · ');
  cards.push(`<article class="edge-card"><div class="edge-title"><strong>${esc(a.player_id)} ↔ ${esc(b.player_id)}</strong><span>${routes[route]?.[0]||'待测试'}</span></div><div class="metric-row"><div><small>双向较高 RTT</small><b>${fmt(rtt)}<em>ms</em></b></div><div><small>输入间隔 P95</small><b>${fmt(gap)}<em>ms</em></b></div></div>${spark(s.rtt,'#9ed57b')}${spark(s.gap,'#82b7ef')}<div class="edge-foot" title="${esc(note)}">${esc(note)}</div></article>`);
 }));$('monitor-cards').innerHTML=cards.join('')||'<p class="muted small">添加一位队友后开始显示连接监视。</p>';
}
function render(){
 renderGuide();
 const theme=state.profile?.theme||"green";document.documentElement.dataset.theme=theme;$("theme").value=theme;$("theme").disabled=!!state.busy;
 const room=state.room||{},members=room.members||[],busy=!!state.busy,connected=!!state.self;
 $('connection').textContent=state.failure?'连接已断开':connected?'游戏已连接':'尚未连接游戏';$('connection').classList.toggle('ready',connected&&!state.failure);
 $('disconnect').hidden=!connected;$('connect').textContent=state.failure?'重新连接':'连接游戏';$('connect').disabled=busy||(connected&&!state.failure);$('disconnect').disabled=busy;
 if(document.activeElement!==$('name')&&state.profile?.player_id)$('name').value=state.profile.player_id;
 $('name').disabled=connected||busy;
 $('own-code').textContent=state.code||'连接游戏后生成';$('copy').disabled=!state.code;
 $('member-count').textContent=`${members.length} / 4`;
 for(const id of ['test','add','redundancy'])$(id).disabled=busy||!connected||!host();
 $('new-room').disabled=busy||!connected;$('address').disabled=busy||connected;
 $('capture').disabled=busy||!connected;$('capture').textContent=state.capture?.active?'停止并保存':'开始抓包';
 $('capture-status').textContent=state.capture?.active?`已记录 ${(state.capture.records||0).toLocaleString()} 条`:state.capture?.path?'已保存到本地抓包文件夹':'未抓包';
 $('session-status').textContent=!connected?'先连接游戏':state.failure?'请重新连接游戏':room.error?room.error:room.test&&!room.selection?`正在测试线路 · ${Math.min(29,Math.floor(room.elapsed||0))} / 29 秒`:members.length<2?'等待队友加入':members.every(p=>p.enabled)?'已就绪，可进官方房间':room.plan_complete?'正在连接':'等待选择线路';
 $('players').innerHTML=members.map(p=>`<div class="player"><div class="avatar">${esc(p.player_id?.slice(0,2))}</div><div class="player-name">${esc(p.player_id)}<small>${p.steam===room.host?'主持人':'队友'}${p.steam===state.self?' · 你':''}</small></div>${host()&&p.steam!==state.self?`<button class="quiet kick" data-peer="${esc(p.steam)}" aria-label="移出 ${esc(p.player_id)}">移出</button>`:''}</div>`).join('');
 document.querySelectorAll('.kick').forEach(b=>{b.disabled=busy;b.onclick=()=>act('kick',{steam:b.dataset.peer})});
 $('redundancy').value=room.redundancy||'off';
 $('activity').textContent=busy?state.busy:state.control_failure?'协调连接正在恢复':'准备就绪';
 if(state.error)error(state.error);$('logs').textContent=(state.logs||[]).join('\n');
 const options=state.addresses||[];if($('address').options.length!==options.length+1){$('address').innerHTML='<option value="">自动选择</option>'+options.map(ip=>`<option value="${esc(ip)}">${esc(ip)}</option>`).join('')}
 $('server-code').disabled=busy||connected;
 $('test').textContent=room.offline?'启用直连':'自动测试';
 if(room.offline){for(const id of ['redundancy','capture','new-room'])$(id).disabled=true;document.querySelectorAll('.kick').forEach(b=>b.disabled=true)}
 drawGraph();monitor();if(selected)renderRoute();
}
async function refresh(){try{state=await api('state');render()}catch(e){error('助手连接中断：'+e.message)}}
$('connect').onclick=()=>act('connect',{player_id:$('name').value,ip:$('address').value,server_code:$('server-code').value});
$('disconnect').onclick=()=>act('disconnect');$('new-room').onclick=()=>{closeRoute();act('new-room')};$('add').onclick=()=>act('add',{code:$('join-code').value});
$('join-code').onkeydown=e=>{if(e.key==='Enter')$('add').click()};$('test').onclick=()=>act('test');$('redundancy').onchange=()=>act('settings',{redundancy:$('redundancy').value});
$('monitor-toggle').onchange=()=>act('settings',{monitor:$('monitor-toggle').checked});$('capture').onclick=()=>act('capture');$('open-captures').onclick=()=>act('open-captures');
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(state.code);toast('连接码已复制')}catch(e){error('复制失败，请从连接码处手动复制。')}};
$('close-log').onclick=()=>$('log-panel').hidden=true;
$('show-log').onclick=()=>$('log-panel').hidden=!$('log-panel').hidden;$('exit').onclick=()=>act('exit');
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeRoute();$('log-panel').hidden=true}});
async function loop(){if(stopped)return;await refresh();if(!stopped)setTimeout(loop,state.busy?700:2000)}loop();

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
