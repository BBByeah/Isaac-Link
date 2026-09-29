const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('isaac_link/hook7.js','utf8');
const lifecycle=source.slice(source.indexOf('let carrierPeers='),source.indexOf('const carrierTable='));
const poll=source.slice(source.indexOf('function pollCarrier(){'),source.indexOf('const callbackRegister'));
let calls=0,shutdown;const events=[];
const context={Date,Set,clearInterval:()=>events.push('timer-stop'),send:x=>events.push(x.type),
 api:{findExportByName:()=>({})},Interceptor:{attach:(p,h)=>shutdown=h.onEnter},
 instance:{readPointer:()=>({equals:()=>true}),writePointer:()=>events.push('restore')},
 installed:true,original:{},table:{},states:{},UInt64:function(v){return v},CARRIER_CHANNEL:18854,
 unregisterRequest:()=>events.push('unregister'),carrierAccept:()=>{},carrierAvailable:()=>{calls++;throw Error('interface gone')},carrierSize:{}};
vm.createContext(context);vm.runInContext(lifecycle+poll+'\ncarrierTimer=1;pollCarrier();pollCarrier();',context);
assert.equal(calls,1);assert.equal(events.filter(x=>x==='fatal').length,1);
assert(source.includes('callbackRegister(requestObject,1202)'));
assert(source.includes("raw[21]===68||raw[21]===66"));
assert(source.includes("if(!states[id.toString()] || nativeRoute"));
shutdown();assert(events.includes('unregister'));assert(events.indexOf('unregister')<events.lastIndexOf('restore'));
console.log('PASS: v7 carrier stops invalid interface calls, unregisters callback, preserves managed packet modes');
