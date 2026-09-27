'use strict';
let instance=null, original=null, table=null, installed=false;
let callbacks=[], states={}, stateAt=0, queues=new Map(), bytes=0, pending=0;
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
const userVersion=api.enumerateExports().find(x=>/^SteamAPI_SteamUser_v\d+$/.test(x.name));
if(!userVersion) throw new Error('Steam user export unavailable');
const userObject=new NativeFunction(userVersion.address,'pointer',[],'mscdecl')();
const steam=new NativeFunction(api.getExportByName('SteamAPI_ISteamUser_GetSteamID'),'uint64',['pointer'],'mscdecl')(userObject).toString();
function active(id){return Date.now()-stateAt<1500 && states[id] && states[id].active;}
function nativeRoute(id){return Date.now()-stateAt<1500 && states[id] && states[id].route==='steam';}
function reliableReady(id){return Date.now()-stateAt<1500 && states[id] && !states[id].error && (states[id].queued||0)<7000;}
function queue(ch){if(!queues.has(ch))queues.set(ch,[]);return queues.get(ch);}
function clear(id,ch){for(const [c,q] of queues){if(ch!==undefined&&c!==ch)continue;queues.set(c,q.filter(p=>{if(p.id===id){bytes-=p.data.byteLength;return false;}return true;}));}}
function add(slot,args,fn){const cb=new NativeCallback(function(...values){return fn(...values)?1:0;},'bool',args,'thiscall');callbacks.push(cb);table.add(slot*4).writePointer(cb);}
function install(){
 if(installed)return;
 if(!Object.keys(states).length || !Object.keys(states).every(id=>active(id)||nativeRoute(id)))throw new Error('IPv6 peers are not connected');
 original=instance.readPointer();table=Memory.alloc(22*4);Memory.copy(table,original,22*4);
 const signatures=[['pointer','uint64','pointer','uint32','int','int'],['pointer','pointer','int'],['pointer','pointer','uint32','pointer','pointer','int'],['pointer','uint64'],['pointer','uint64'],['pointer','uint64','int'],['pointer','uint64','pointer'],['pointer','bool']];
 nativeCalls=signatures.map((s,i)=>new NativeFunction(original.add(i*4).readPointer(),'bool',s,'thiscall'));
 add(0,['pointer','uint64','pointer','uint32','int','int'],function(self,id,p,n,mode,ch){
  if(nativeRoute(id.toString())){const ok=nativeCalls[0](self,id,p,n,mode,ch);if(ok){nativeMetrics.sent++;nativeMetrics.bytesOut+=n;nativeCount(id.toString(),'sent');}return ok;}
  id=id.toString();if(!(mode>=2?reliableReady(id):active(id))||n>1048576||pending>=1024){metrics.blocked++;return false;}
  pending++;metrics.sent++;send({type:'packet',peer:id,channel:ch,mode:mode},n?p.readByteArray(n):new ArrayBuffer(0));return true;
 });
 add(1,['pointer','pointer','int'],function(self,out,ch){metrics.polls++;const q=queue(ch);if(q.length){if(!out.isNull())out.writeU32(q[0].data.byteLength);return true;}return Object.keys(states).some(nativeRoute)?nativeCalls[1](self,out,ch):false;});
 add(2,['pointer','pointer','uint32','pointer','pointer','int'],function(self,dst,cap,out,sender,ch){
  const q=queue(ch);if(!q.length){
   if(!Object.keys(states).some(nativeRoute))return false;
   const ok=nativeCalls[2](self,dst,cap,out,sender,ch);
   if(ok && !sender.isNull() && nativeRoute(sender.readU64().toString())){nativeMetrics.read++;nativeCount(sender.readU64().toString(),'read');if(!out.isNull())nativeMetrics.bytesIn+=out.readU32();return true;}
   return false;
  }
  const p=q.shift();bytes-=p.data.byteLength;const n=Math.min(cap,p.data.byteLength);
  if(n)dst.writeByteArray(p.data.slice(0,n));if(!out.isNull())out.writeU32(n);if(!sender.isNull())sender.writeU64(new UInt64(p.id));metrics.read++;return true;
 });
 add(3,['pointer','uint64'],(self,id)=>nativeRoute(id.toString())?nativeCalls[3](self,id):!!reliableReady(id.toString()));
 add(4,['pointer','uint64'],(self,id)=>{clear(id.toString());return nativeRoute(id.toString())?nativeCalls[4](self,id):true;});
 add(5,['pointer','uint64','int'],(self,id,ch)=>{clear(id.toString(),ch);return nativeRoute(id.toString())?nativeCalls[5](self,id,ch):true;});
 add(6,['pointer','uint64','pointer'],function(self,id,out){
  if(nativeRoute(id.toString()))return nativeCalls[6](self,id,out);
  id=id.toString();if(!states[id]||out.isNull())return false;out.writeByteArray(new Uint8Array(20));
  out.writeU8(active(id)?1:0);out.add(1).writeU8(!active(id)&&!states[id].error?1:0);out.add(2).writeU8(states[id].error?4:0);out.add(8).writeS32(states[id].queued||0);return true;
 });
 add(7,['pointer','bool'],(self,allow)=>nativeCalls[7](self,allow));
 instance.writePointer(table);installed=true;
}
function messages(){recv('control',function(m,data){const p=m.payload;
 if(p.kind==='states'){states=p.states;stateAt=Date.now();}
 if(p.kind==='ack')pending=Math.max(0,pending-1);
 if(p.kind==='receive'){
  if(bytes+(data?data.byteLength:0)>16777216){send({type:'fatal',message:'Game receive queue full'});states={};}
  else {queue(p.channel).push({id:p.peer,data:data||new ArrayBuffer(0)});bytes+=data?data.byteLength:0;}
 }
 messages();});}
messages();
rpc.exports={info(){return{steam:steam,architecture:Process.arch,interface:'SteamNetworking006'};},
 configure(s){states=s;stateAt=Date.now();},install:install,
 status(){const peers={};if(installed){for(const id of Object.keys(states)){if(!nativeRoute(id))continue;const out=Memory.alloc(20);out.writeByteArray(new Uint8Array(20));const ok=nativeCalls[6](instance,new UInt64(id),out);peers[id]={...nativePeerMetrics[id],active:!!ok&&out.readU8()!==0,connecting:!!ok&&out.add(1).readU8()!==0,relay:!!ok&&out.add(3).readU8()!==0,error:ok?out.add(2).readU8():0,queued:ok?out.add(8).readS32():0};}}return{installed:installed,metrics:metrics,pending:pending,buffered:bytes,native:nativeMetrics,nativePeers:peers};},
 restore(){if(installed){instance.writePointer(original);installed=false;}queues.clear();bytes=0;}
};
