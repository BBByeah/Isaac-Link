"""Four-input redundancy; outer transport authenticates the compact bundle."""
import collections
import hmac
import struct
import time
from isaac_link.transport import HEADER, DATA, Transport

ENTRY=struct.Struct('!Q40s')

class InputWindow:
    def __init__(self):
        self.history={}
        self.rescue={}

    def clear(self):
        self.history.clear();self.rescue.clear()

    def send(self,transport,peer,raw):
        if len(raw)!=HEADER.size+16+40:return None
        _,kind,_,channel,mode,seq,index,count=HEADER.unpack_from(raw)
        payload=raw[HEADER.size:-16]
        if (kind,channel,mode,index,count)!=(DATA,0,1,0,1) or payload[4:8]!=b'\x01\x01\x00\x01':return None
        history=self.history.setdefault(peer,collections.OrderedDict())
        frame=struct.unpack_from('<I',payload,24)[0]
        # A game retransmission gets a fresh transport sequence so the game
        # can acknowledge it again. It does not consume a new history slot.
        previous=[v for p,v in history.items() if p!=payload and struct.unpack_from('<I',p,24)[0]<frame][-3:]
        body=b'B'+bytes([len(previous)+1])+b''.join(ENTRY.pack(*v) for v in previous+[(seq,payload)])
        history[payload]=(seq,payload)
        while len(history)>4:history.popitem(last=False)
        route=transport.selected.get(peer)
        sent=transport.emit(peer,route,body) if route else False
        now=time.monotonic()
        self.rescue[peer]=[now+.050,now,route,body,0]
        transport.stats['window_bundles']+=1
        transport.stats['window_carried_inputs']+=len(previous)
        return sent

    def receive(self,transport,peer,route,body):
        if body[:1]!=b'B':return False
        if len(body)<2 or not 1<=body[1]<=4 or len(body)!=2+body[1]*ENTRY.size:return True
        entries=[ENTRY.unpack_from(body,2+i*ENTRY.size) for i in range(body[1])]
        if any(p[4:8]!=b'\x01\x01\x00\x01' for _,p in entries):return True
        transport.path_last[peer,route]=time.monotonic()
        source=transport.peers[peer]
        # Deliver every available input now. Missing earlier packets do not
        # block later packets; the game's frame cache decides when to advance.
        for seq,payload in entries:
            raw=HEADER.pack(b'I6D1',DATA,peer,0,1,seq,0,1)+payload
            raw+=hmac.digest(transport.keys[peer],raw,'sha256')[:16]
            Transport._receive(transport,raw,(source.ip,source.port),count_wire=False)
        transport.stats['window_received']+=1
        return True

    def maintenance(self,transport,now):
        for peer,item in list(self.rescue.items()):
            due,began,route,body,attempt=item
            if route!=transport.selected.get(peer) or now-began>.5:
                self.rescue.pop(peer,None);continue
            if now<due:continue
            if transport.emit(peer,route,body):transport.stats['window_rescue']+=1
            attempt+=1
            if attempt>=3:self.rescue.pop(peer,None)
            else:item[0]=now+(.05 if attempt==1 else .1);item[4]=attempt
