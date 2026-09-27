import socket
import struct
import threading
import unittest
from isaac_link.network_priority import NetworkPriority, sockaddr, prioritize_thread


class PriorityTest(unittest.TestCase):
    def test_sockaddr_layout(self):
        raw=sockaddr(socket.AF_INET,('192.0.2.1',27667))
        self.assertEqual(len(raw),16)
        self.assertEqual(raw[2:4],struct.pack('!H',27667))
        self.assertEqual(raw[4:8],socket.inet_pton(socket.AF_INET,'192.0.2.1'))
        raw=sockaddr(socket.AF_INET6,('2001:db8::1',27667,0,7))
        self.assertEqual(len(raw),28)
        self.assertEqual(raw[8:24],socket.inet_pton(socket.AF_INET6,'2001:db8::1'))
        self.assertEqual(raw[24:],struct.pack('=I',7))

    def test_slow_setup_does_not_block_send_and_deduplicates(self):
        entered=threading.Event();release=threading.Event();calls=[];closed=[]
        class Qos:
            def add(self,sock,target):calls.append(target);entered.set();release.wait(3)
            def close(self):closed.append(True)
        priority=NetworkPriority(factory=Qos)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            priority.request(sock,('192.0.2.1',27667))
            self.assertTrue(entered.wait(1))
            for _ in range(100):priority.request(sock,('192.0.2.1',27667))
            self.assertEqual(priority.queue.qsize(),0)
            release.set();priority.close()
        self.assertEqual(len(calls),1);self.assertTrue(closed)

    def test_unavailable_qos_does_not_raise_on_send(self):
        messages=[];done=threading.Event()
        def unavailable():done.set();raise OSError(5,'denied')
        p=NetworkPriority(messages.append,factory=unavailable)
        self.assertTrue(done.wait(1));p.close()
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:p.request(sock,('192.0.2.1',27667))
        self.assertTrue(messages)

    @unittest.skipUnless(__import__('os').name=='nt','Windows only')
    def test_thread_priority_on_temporary_worker(self):
        result=[]
        t=threading.Thread(target=lambda:result.append(prioritize_thread()))
        t.start();t.join()
        self.assertEqual(result,[True])
