const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('isaac_link/hook_v5.js','utf8');
const lifecycle=source.slice(source.indexOf('let carrierPeers='),source.indexOf('const carrierTable='));
const poll=source.slice(source.indexOf('function pollCarrier(){'),source.indexOf('function active('));
function fixture(fault){
 const trace=[],messages=[];let shutdown;
 const context={Date,Set,clearInterval:()=>trace.push('timer-stop'),send:x=>messages.push(x),
 api:{findExportByName:()=>({})},Interceptor:{attach:(a,h)=>{shutdown=h.onEnter;}},
 instance:{readPointer:()=>({equals:()=>true}),writePointer:()=>trace.push('restore-table')},
 installed:true,original:{},table:{},states:{},UInt64:function(v){return v},CARRIER_CHANNEL:18854,
 carrierAccept:()=>{},carrierAvailable:()=>{trace.push('native-call');if(fault)throw Error('access violation');return false;},carrierSize:{}};
 vm.createContext(context);vm.runInContext(lifecycle+poll+'\ncarrierTimer=123;',context);
 return {context,trace,messages,shutdown};
}
let f=fixture(true);vm.runInContext('pollCarrier();pollCarrier();pollCarrier()',f.context);
assert.equal(f.trace.filter(x=>x==='native-call').length,1);assert.equal(f.messages.length,1);assert(f.trace.includes('timer-stop'));
f=fixture(false);f.shutdown();vm.runInContext('pollCarrier()',f.context);
assert.deepEqual(f.trace,['timer-stop','restore-table']);assert.equal(f.messages.length,1);
console.log('PASS: native failure stops subsequent calls, shutdown stops timer before restoring table');
