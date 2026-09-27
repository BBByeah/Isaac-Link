"""Streaming, loss-explicit application packet capture. Never blocks game I/O on disk."""
import base64
import collections
import json
import os
from pathlib import Path
import queue
import struct
import threading
import time
import uuid

def describe(raw):
    result={}
    if raw.startswith(b'I6H2'):return {'packet_type':'registration_heartbeat'}
    if raw.startswith(b'I6R2') and len(raw)>=60:
        result['relay_wrapper_bytes']=60;raw=raw[60:]
    if raw.startswith(b'I6W2') and len(raw)>=22:
        _,sender,target,route=struct.unpack_from('!4sQQB',raw)
        result.update(sender=str(sender),target=str(target),route=('ipv6','ipv4','relay','steam','lan')[route] if route<5 else 'unknown')
        body=raw[21:-16];kind=body[:1]
        result['packet_type']={b'?':'probe',b'!':'probe_reply',b'Q':'round_probe',b'A':'round_reply',b'D':'transport'}.get(kind,'unknown')
        if kind==b'B' and len(body)>=2 and 1<=body[1]<=4 and len(body)==2+48*body[1]:
            result.update(packet_type='input_bundle',inputs=[
                dict(sequence=str(struct.unpack_from('!Q',body,2+48*i)[0]),
                     frame=struct.unpack_from('<I',body,2+48*i+8+24)[0]) for i in range(body[1])])
        if kind in (b'?',b'!',b'Q',b'A') and len(body)>=9:result['probe_sequence']=str(struct.unpack_from('!Q',body,1)[0])
        if kind==b'D' and len(body)>=31:
            magic,kind,peer,ch,mode,seq,index,count=struct.unpack_from('!4sBQiBQHH',body,1)
            if magic==b'I6D1':result.update(packet_type={1:'ping',2:'pong',3:'data',4:'ack'}.get(kind,'unknown'),channel=ch,mode=mode,sequence=str(seq),fragment=index,fragments=count)
    return result

class Capture:
    def __init__(self,limit=64*1024*1024):
        self.lock=threading.Lock();self.limit=limit;self.active=False;self.path=None;self.thread=None;self.error='';self.count=0;self.written=0;self.dropped=0;self.pending=0

    def start(self,folder,metadata=None):
        with self.lock:
            if self.active or (self.thread and self.thread.is_alive()):raise RuntimeError('抓包正在运行或保存中。')
            Path(folder).mkdir(parents=True,exist_ok=True)
            self.path=Path(folder)/('capture-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.jsonl')
            self.file=self.path.open('x',encoding='utf-8',buffering=1024*1024)
            self.queue=queue.Queue();self.done=threading.Event();self.count=self.written=self.dropped=self.pending=0;self.error=''
            self.start_ns=time.perf_counter_ns()
            self.file.write(json.dumps(dict(event='capture_start',format='isaac-capture-v1',wall_ns=time.time_ns(),mono_ns=self.start_ns,metadata=metadata or {},scope='game hook, helper UDP payloads, Steam P2P API payloads; excludes OS headers and Steam encrypted wire internals'),ensure_ascii=False)+'\n')
            self.file.flush();self.active=True
            self.thread=threading.Thread(target=self._write,daemon=True);self.thread.start()
            return str(self.path)

    def record(self,event,data=b'',**fields):
        if not self.active:return
        with self.lock:
            if not self.active:return
            data=bytes(data);size=len(data)+512
            if self.pending+size>self.limit:
                self.dropped+=1;self.error='抓包写入积压超过限制，已停止抓包；文件不完整。';self.active=False;self.done.set();return
            self.count+=1;self.pending+=size
            row=dict(event=event,id=self.count,wall_ns=time.time_ns(),mono_ns=time.perf_counter_ns(),**fields)
            self.queue.put_nowait((row,data,size))

    def _write(self):
        counts=collections.Counter();payload_bytes=0;flush_at=time.monotonic()+1
        try:
            while not self.done.is_set() or not self.queue.empty():
                try:row,data,size=self.queue.get(timeout=.1)
                except queue.Empty:row=None
                if row is not None:
                    row.update(length=len(data),payload_b64=base64.b64encode(data).decode('ascii'))
                    if data:row['decoded']=describe(data)
                    self.file.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
                    counts[row['event']]+=1;payload_bytes+=len(data)
                    with self.lock:self.written+=1;self.pending-=size
                if time.monotonic()>=flush_at:self.file.flush();flush_at=time.monotonic()+1
            self.file.write(json.dumps(dict(event='capture_end',wall_ns=time.time_ns(),records=self.written,counts=dict(counts),payload_bytes=payload_bytes,dropped=self.dropped,complete=not self.error,error=self.error),ensure_ascii=False)+'\n')
            self.file.flush();os.fsync(self.file.fileno())
        except Exception as e:
            with self.lock:self.error='抓包文件写入失败：'+str(e);self.active=False
        finally:
            try:self.file.close()
            except Exception:pass
            with self.lock:
                self.active=False
                while not self.queue.empty():
                    try:self.queue.get_nowait();self.dropped+=1
                    except queue.Empty:break
                self.pending=0

    def stop(self):
        with self.lock:
            self.active=False
            if not self.thread:return None
            self.done.set();thread=self.thread
        thread.join()
        if self.error:raise RuntimeError(self.error+' 文件：'+str(self.path))
        return str(self.path)

    def status(self):
        with self.lock:return dict(active=self.active,saving=bool(self.thread and self.thread.is_alive() and not self.active),path=str(self.path) if self.path else '',records=self.written,dropped=self.dropped,error=self.error)
