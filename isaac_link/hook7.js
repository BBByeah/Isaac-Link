'use strict';
let instance=null, original=null, table=null, installed=false;
let callbacks=[], states={}, stateAt=0, queues=new Map(), bytes=0, pending=0;
let generation='', monitorEnabled=false, inputStats={};
function trackInput(id,ch,data){
 if(!monitorEnabled||ch!==0||data.byteLength!==40)return;
 const frame=new DataView(data).getUint32(24,true), now=Date.now();
 let s=inputStats[id];if(!s)s=inputStats[id]={last:0,frame:-1,gaps:[],count:0};
 if(frame===s.frame)return;
 if(s.last&&s.gaps.length<600)s.gaps.push(now-s.last);
 s.last=now;s.frame=frame;s.count++;
}
function inputSnapshot(){
 const result={};const now=Date.now();
 for(const [id,s] of Object.entries(inputStats)){
  const gaps=s.gaps.slice().sort((a,b)=>a-b);
  result[id]={samples:gaps.length,count:s.count,idle_ms:now-s.last,
   gap_p50_ms:gaps.length?gaps[Math.floor((gaps.length-1)*.5)]:null,
   gap_p95_ms:gaps.length?gaps[Math.floor((gaps.length-1)*.95)]:null,
   gap_max_ms:gaps.length?gaps[gaps.length-1]:null,over100:gaps.filter(x=>x>100).length};
  s.gaps=[];s.count=0;
 }
 return result;
}
let metrics={polls:0,sent:0,read:0,blocked:0};
let nativeCalls=[], nativeMetrics={sent:0,read:0,bytesOut:0,bytesIn:0};
const nativePeerMetrics={};
function nativeCount(id,key){if(!nativePeerMetrics[id])nativePeerMetrics[id]={sent:0,read:0};nativePeerMetrics[id][key]++;}
const api=Process.getModuleByName('steam_api.dll');
if(Process.arch!=='ia32') throw new Error('Only the verified 32-bit game is supported');
const user=new NativeFunction(api.getExportByName('SteamAPI_GetHSteamUser'),'int',[],'mscdecl')();
const obtain=new NativeFunction(api.getExportByName('SteamInternal_FindOrCreateUserInterface'),'pointer',['int','pointer'],'mscdecl');
instance=obtain(user,Memory.allocUtf8String('SteamNetworking006'));
if(instance.isNull()) throw new Error('SteamNetworking006 unavailable');
function assertOriginalTable(){if(!Process.findModuleByAddress(instance.readPointer().readPointer()))throw new Error('请先关闭旧版联机助手，再使用 0.4；不能同时接管同一份游戏。');}
assertOriginalTable();
const userVersion=api.enumerateExports().find(x=>/^SteamAPI_SteamUser_v\d+$/.test(x.name));
if(!userVersion) throw new Error('Steam user export unavailable');
const userObject=new NativeFunction(userVersion.address,'pointer',[],'mscdecl')();
const steam=new NativeFunction(api.getExportByName('SteamAPI_ISteamUser_GetSteamID'),'uint64',['pointer'],'mscdecl')(userObject).toString();
// Keep direct calls to the original object table. This channel carries only
// authenticated helper envelopes; game channels remain inside the envelope.
const CARRIER_CHANNEL=18854;
let carrierPeers=new Set(), carrierErrors=0, carrierTimer=null, carrierAcceptAt=0, captureEnabled=false;
let carrierStopped=false, steamClosing=false;
function stopCarrier(reason){
 if(carrierTimer){clearInterval(carrierTimer);carrierTimer=null;}
 if(carrierStopped)return;
 carrierStopped=true;carrierPeers.clear();
 if(reason){states={};send({type:'fatal',message:reason});}
}
function carrierFault(){steamClosing=true;carrierErrors++;stopCarrier('Steam 接口已失效，已停止轮询。请重新连接游戏。');}
const shutdownAddress=api.findExportByName('SteamAPI_Shutdown');
if(shutdownAddress)Interceptor.attach(shutdownAddress,{onEnter(){
 unregisterRequest();steamClosing=true;stopCarrier('Steam 正在关闭，已停止联机接管。');
 // Restore the table while Steam still owns the live interface object.
 if(installed){try{if(instance.readPointer().equals(table))instance.writePointer(original);}catch(e){}installed=false;}
}});
const carrierTable=instance.readPointer();
const carrierSend=new NativeFunction(carrierTable.readPointer(),'bool',['pointer','uint64','pointer','uint32','int','int'],'thiscall');
const carrierAvailable=new NativeFunction(carrierTable.add(4).readPointer(),'bool',['pointer','pointer','int'],'thiscall');
const carrierRead=new NativeFunction(carrierTable.add(8).readPointer(),'bool',['pointer','pointer','uint32','pointer','pointer','int'],'thiscall');
const carrierAccept=new NativeFunction(carrierTable.add(12).readPointer(),'bool',['pointer','uint64'],'thiscall');
const carrierClose=new NativeFunction(carrierTable.add(20).readPointer(),'bool',['pointer','uint64','int'],'thiscall');
const carrierState=new NativeFunction(carrierTable.add(24).readPointer(),'bool',['pointer','uint64','pointer'],'thiscall');
const carrierSize=Memory.alloc(4), carrierBuffer=Memory.alloc(65536), carrierSender=Memory.alloc(8);
function pollCarrier(){
 if(carrierStopped)return;
 try{
 if(Date.now()>carrierAcceptAt){carrierAcceptAt=Date.now()+1000;for(const id of carrierPeers)carrierAccept(instance,new UInt64(id));}
 for(let i=0;i<128;i++){
  if(!carrierAvailable(instance,carrierSize,CARRIER_CHANNEL))break;
  if(carrierSize.readU32()>65536){carrierErrors++;break;}
  if(!carrierRead(instance,carrierBuffer,65536,carrierSize,carrierSender,CARRIER_CHANNEL))break;
  const id=carrierSender.readU64().toString(), n=carrierSize.readU32();
  if(n<=1450 && (carrierPeers.has(id) || (n>=3 && carrierBuffer.readU8()===73 && carrierBuffer.add(1).readU8()===55 && carrierBuffer.add(2).readU8()===74)))send({type:'carrier',peer:id},carrierBuffer.readByteArray(n));
 }
 }catch(e){carrierFault();}
}

const callbackRegister = new NativeFunction(api.getExportByName('SteamAPI_RegisterCallback'),'void',['pointer','int'],'mscdecl');
const callbackUnregister = new NativeFunction(api.getExportByName('SteamAPI_UnregisterCallback'),'void',['pointer'],'mscdecl');
const requestTable=Memory.alloc(12), requestObject=Memory.alloc(12);
requestObject.writeByteArray(new Uint8Array(12));requestObject.writePointer(requestTable);requestObject.add(8).writeS32(1202);
let requestRegistered=false, acceptWindow=0, acceptCount=0;
function onSessionRequest(data){
 if(carrierStopped || steamClosing)return;
 const now=Date.now();if(now-acceptWindow>1000){acceptWindow=now;acceptCount=0;}
 if(++acceptCount>16)return;
 try{carrierAccept(instance,data.readU64());}catch(e){carrierFault();}
}
const requestRun=new NativeCallback((self,data)=>onSessionRequest(data),'void',['pointer','pointer'],'thiscall');
const requestRunCall=new NativeCallback((self,data,failed,call)=>{if(!failed)onSessionRequest(data);},'void',['pointer','pointer','bool','uint64'],'thiscall');
const requestSize=new NativeCallback(self=>8,'int',['pointer'],'thiscall');
requestTable.writePointer(requestRun);requestTable.add(4).writePointer(requestRunCall);requestTable.add(8).writePointer(requestSize);
callbackRegister(requestObject,1202);requestRegistered=true;
function unregisterRequest(){if(requestRegistered){requestRegistered=false;try{callbackUnregister(requestObject);}catch(e){}}}
carrierTimer=setInterval(pollCarrier,5);

function active(id){return Date.now()-stateAt<1500 && states[id] && states[id].active;}
function nativeRoute(id){return Date.now()-stateAt<1500 && states[id] && states[id].route==='steam';}
function reliableReady(id){return Date.now()-stateAt<1500 && states[id] && !states[id].error && (states[id].queued||0)<7000;}
function queue(ch){if(!queues.has(ch))queues.set(ch,[]);return queues.get(ch);}
function clear(id,ch){for(const [c,q] of queues){if(ch!==undefined&&c!==ch)continue;queues.set(c,q.filter(p=>{if(p.id===id){bytes-=p.data.byteLength;return false;}return true;}));}}
function add(slot,args,fn){const cb=new NativeCallback(function(...values){return fn(...values)?1:0;},'bool',args,'thiscall');callbacks.push(cb);table.add(slot*4).writePointer(cb);}
function install(){
 if(carrierStopped)throw new Error('Steam 接口已关闭，请重新连接游戏。');
 if(installed)return;
 assertOriginalTable();
 if(!Object.keys(states).length || !Object.keys(states).some(id=>active(id)||nativeRoute(id)))throw new Error('IPv6 peers are not connected');
 original=instance.readPointer();table=Memory.alloc(22*4);Memory.copy(table,original,22*4);
 const signatures=[['pointer','uint64','pointer','uint32','int','int'],['pointer','pointer','int'],['pointer','pointer','uint32','pointer','pointer','int'],['pointer','uint64'],['pointer','uint64'],['pointer','uint64','int'],['pointer','uint64','pointer'],['pointer','bool']];
 nativeCalls=signatures.map((s,i)=>new NativeFunction(original.add(i*4).readPointer(),'bool',s,'thiscall'));
 add(0,['pointer','uint64','pointer','uint32','int','int'],function(self,id,p,n,mode,ch){
  if(ch===CARRIER_CHANNEL){send({type:'fatal',message:'Steam helper channel conflicts with the game'});return false;}
  if(!states[id.toString()] || nativeRoute(id.toString())){const ok=nativeCalls[0](self,id,p,n,mode,ch);if(ok){nativeMetrics.sent++;nativeMetrics.bytesOut+=n;nativeCount(id.toString(),'sent');}return ok;}
  id=id.toString();if(!(mode>=2?reliableReady(id):active(id))||n>1048576||pending>=1024){metrics.blocked++;return false;}
   pending++;metrics.sent++;send({type:'packet',peer:id,channel:ch,mode:mode,generation:generation,wall_ms:captureEnabled?Date.now():null},n?p.readByteArray(n):new ArrayBuffer(0));return true;
 });
 add(1,['pointer','pointer','int'],function(self,out,ch){metrics.polls++;const q=queue(ch);if(q.length){if(!out.isNull())out.writeU32(q[0].data.byteLength);return true;}return nativeCalls[1](self,out,ch);});
 add(2,['pointer','pointer','uint32','pointer','pointer','int'],function(self,dst,cap,out,sender,ch){
  const q=queue(ch);if(!q.length){

   const ok=nativeCalls[2](self,dst,cap,out,sender,ch);
   if(ok && !sender.isNull() && (!states[sender.readU64().toString()] || nativeRoute(sender.readU64().toString()))){nativeMetrics.read++;nativeCount(sender.readU64().toString(),'read');if(!out.isNull())nativeMetrics.bytesIn+=out.readU32();return true;}
   return false;
  }
  const p=q.shift();bytes-=p.data.byteLength;const n=Math.min(cap,p.data.byteLength);
  if(n)dst.writeByteArray(p.data.slice(0,n));if(!out.isNull())out.writeU32(n);if(!sender.isNull())sender.writeU64(new UInt64(p.id));metrics.read++;
  trackInput(p.id,ch,p.data);
  if(captureEnabled)send({type:'game_read',peer:p.id,channel:ch,wall_ms:Date.now()},p.data.slice(0,n));return true;
 });
 add(3,['pointer','uint64'],(self,id)=>(!states[id.toString()]||nativeRoute(id.toString()))?nativeCalls[3](self,id):!!reliableReady(id.toString()));
 add(4,['pointer','uint64'],(self,id)=>{clear(id.toString());return (!states[id.toString()]||nativeRoute(id.toString()))?nativeCalls[4](self,id):true;});
 add(5,['pointer','uint64','int'],(self,id,ch)=>{clear(id.toString(),ch);return (!states[id.toString()]||nativeRoute(id.toString()))?nativeCalls[5](self,id,ch):true;});
 add(6,['pointer','uint64','pointer'],function(self,id,out){
  if(!states[id.toString()]||nativeRoute(id.toString()))return nativeCalls[6](self,id,out);
  id=id.toString();if(!states[id]||out.isNull())return false;out.writeByteArray(new Uint8Array(20));
  out.writeU8(active(id)?1:0);out.add(1).writeU8(!active(id)&&!states[id].error?1:0);out.add(2).writeU8(states[id].error?4:0);out.add(8).writeS32(states[id].queued||0);return true;
 });
 add(7,['pointer','bool'],(self,allow)=>nativeCalls[7](self,allow));
 instance.writePointer(table);installed=true;
}
function messages(){recv('control',function(m,data){const p=m.payload;
 if(p.generation!==undefined&&p.generation!==generation){messages();return;}
 if(p.kind==='states'){states=p.states;stateAt=Date.now();}
 if(p.kind==='ack')pending=Math.max(0,pending-1);
 if(p.kind==='capture')captureEnabled=!!p.enabled;
 if(p.kind==='carrier' && !carrierStopped && data && data.byteLength<=1450){
  try{
  const buf=Memory.alloc(data.byteLength);buf.writeByteArray(data);
   // Transport data must never wait inside Steam's connection buffer. Control
   // probes retain Unreliable so they can establish a not-yet-ready P2P session.
   const raw=new Uint8Array(data);
   const mode=raw.length>21&&raw[0]===73&&raw[1]===54&&raw[2]===87&&raw[3]===50&&(raw[21]===68||raw[21]===66)?1:0;
   const ok=carrierSend(instance,new UInt64(p.peer),buf,data.byteLength,mode,CARRIER_CHANNEL);
  if(!ok)carrierErrors++;
   if(captureEnabled)send({type:'carrier_sent',peer:p.peer,success:!!ok,mode:mode,wall_ms:Date.now()},data);
  }catch(e){carrierFault();}
 }
 if(p.kind==='receive'){
  if(bytes+(data?data.byteLength:0)>16777216){send({type:'fatal',message:'Game receive queue full'});states={};}
  else {queue(p.channel).push({id:p.peer,data:data||new ArrayBuffer(0)});bytes+=data?data.byteLength:0;}
 }
 messages();});}
messages();
rpc.exports={info(){return{steam:steam,architecture:Process.arch,interface:'SteamNetworking006'};},
 resetroom(epoch){generation=epoch;states={};stateAt=0;queues.clear();bytes=0;pending=0;inputStats={};},
 monitoring(enabled){monitorEnabled=!!enabled;if(!monitorEnabled)inputStats={};},
 inputs(){return monitorEnabled?inputSnapshot():{};},
 carrierconfigure(ids){if(carrierStopped)return;try{const next=new Set(ids);for(const id of carrierPeers)if(!next.has(id))carrierClose(instance,new UInt64(id),CARRIER_CHANNEL);carrierPeers=next;for(const id of ids)carrierAccept(instance,new UInt64(id));if(!carrierTimer)carrierTimer=setInterval(pollCarrier,5);}catch(e){carrierFault();}},
 carrierstatus(){const result={};if(carrierStopped)return{peers:result,errors:carrierErrors};try{for(const id of carrierPeers){const out=Memory.alloc(20);out.writeByteArray(new Uint8Array(20));const ok=carrierState(instance,new UInt64(id),out);result[id]={active:!!ok&&out.readU8()!==0,relay:!!ok&&out.add(3).readU8()!==0,error:ok?out.add(2).readU8():0};}}catch(e){carrierFault();}return{peers:result,errors:carrierErrors};},
 configure(s){states=s;stateAt=Date.now();},install:install,
 status(){const peers={};if(installed){for(const id of Object.keys(states)){if(!nativeRoute(id))continue;const out=Memory.alloc(20);out.writeByteArray(new Uint8Array(20));const ok=nativeCalls[6](instance,new UInt64(id),out);peers[id]={...nativePeerMetrics[id],active:!!ok&&out.readU8()!==0,connecting:!!ok&&out.add(1).readU8()!==0,relay:!!ok&&out.add(3).readU8()!==0,error:ok?out.add(2).readU8():0,queued:ok?out.add(8).readS32():0};}}return{installed:installed,metrics:metrics,pending:pending,buffered:bytes,native:nativeMetrics,nativePeers:peers};},
 restore(){unregisterRequest();const peers=Array.from(carrierPeers);stopCarrier();if(!steamClosing){try{if(installed&&instance.readPointer().equals(table))instance.writePointer(original);for(const id of peers)carrierClose(instance,new UInt64(id),CARRIER_CHANNEL);}catch(e){steamClosing=true;}}installed=false;queues.clear();bytes=0;}
};
