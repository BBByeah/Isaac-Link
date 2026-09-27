"""Process-lifetime Windows priorities. QoS setup never blocks packet sends."""
import ctypes
from ctypes import wintypes
import os
import queue
import socket
import struct
import threading


def prioritize_thread(log=lambda message: None):
    if os.name != 'nt':return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentThread.restype = wintypes.HANDLE
    kernel.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel.SetThreadPriority.restype = wintypes.BOOL
    ok = bool(kernel.SetThreadPriority(kernel.GetCurrentThread(), 1))
    log('网络线程优先级：' + ('高于正常' if ok else '保持默认'))
    return ok


def sockaddr(family, target):
    host, port = target[:2]
    if family == socket.AF_INET:
        return struct.pack('=H', family)+struct.pack('!H',port)+socket.inet_pton(family,host)+bytes(8)
    scope = target[3] if len(target)>3 else 0
    return struct.pack('=H',family)+struct.pack('!H',port)+bytes(4)+socket.inet_pton(family,host)+struct.pack('=I',scope)


class WindowsQos:
    def __init__(self):
        self.dll = ctypes.WinDLL('qwave', use_last_error=True)
        self.handle = wintypes.HANDLE()
        self.dll.QOSCreateHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE)]
        self.dll.QOSCreateHandle.restype = wintypes.BOOL
        self.dll.QOSAddSocketToFlow.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_int, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.dll.QOSAddSocketToFlow.restype = wintypes.BOOL
        self.dll.QOSCloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.QOSCloseHandle.restype = wintypes.BOOL
        version = (ctypes.c_ushort*2)(1,0)
        if not self.dll.QOSCreateHandle(version,ctypes.byref(self.handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, sock, target):
        addr = ctypes.create_string_buffer(sockaddr(sock.family,target))
        flow = wintypes.DWORD()
        # ExcellentEffort, non-adaptive: priority without traffic shaping.
        if not self.dll.QOSAddSocketToFlow(self.handle,sock.fileno(),addr,2,2,ctypes.byref(flow)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:self.dll.QOSCloseHandle(self.handle);self.handle=wintypes.HANDLE()


class NetworkPriority:
    def __init__(self, log=lambda message: None, factory=None):
        self.log=log;self.factory=factory or WindowsQos
        self.queue=queue.Queue(64);self.seen=set();self.lock=threading.Lock()
        self.stop=threading.Event();self.disabled=os.name!='nt' and factory is None
        self.thread=threading.Thread(target=self.run,daemon=True)
        if not self.disabled:self.thread.start()

    def request(self,sock,target):
        if self.disabled or self.stop.is_set():return
        key=(sock.fileno(),tuple(target))
        with self.lock:
            if key in self.seen or len(self.seen)>=64:return
            self.seen.add(key)
            try:self.queue.put_nowait((sock,target))
            except queue.Full:self.seen.discard(key)

    def run(self):
        qos=None;reported=False
        try:
            qos=self.factory()
            while not self.stop.is_set():
                try:sock,target=self.queue.get(timeout=.2)
                except queue.Empty:continue
                try:
                    qos.add(sock,target)
                    if not reported:self.log('UDP 发送优先级：Windows QoS 已接受申请');reported=True
                except OSError as e:
                    self.log('UDP QoS 未生效，保持正常发送（错误码 '+str(getattr(e,'winerror',None) or e.errno)+'）')
        except OSError as e:
            self.disabled=True
            self.log('UDP QoS 不可用，保持正常发送（错误码 '+str(getattr(e,'winerror',None) or e.errno)+'）')
        finally:
            if qos:qos.close()

    def close(self):
        self.stop.set()
        if self.thread.is_alive():self.thread.join(1)
