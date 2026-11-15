"""Version 1 UART framing: A5 5A + <BBHIH header + payload + CRC32."""
from __future__ import annotations
from dataclasses import dataclass
import struct
import time
import zlib

SYNC=b"\xa5\x5a"
HEADER=struct.Struct("<BBHIH")
COMMANDS={"HELLO":1,"STATUS":2,"CAL":3,"SET":4,"ARM":5,"SNAP":6,"LIST":7,"READ":8,"ACK":9,"REPLAY":10,"ECHO":11,
          "MONITOR":12,"PREVIEW":13,"AUDIO":14,"MUSIC":15,"PANEL":16}


@dataclass(frozen=True)
class Frame:
    command:int
    seq:int=0
    event_id:int=0
    payload:bytes=b""

    def encode(self):
        if len(self.payload)>512:raise ValueError("payload exceeds 512 bytes")
        body=HEADER.pack(1,self.command,self.seq,self.event_id,len(self.payload))+self.payload
        return SYNC+body+struct.pack("<I",zlib.crc32(body))


class Decoder:
    def __init__(self):
        self.buffer=bytearray();self.crc_errors=0;self.discarded=0;self.frames=0

    def feed(self,data):
        self.buffer.extend(data);out=[]
        while True:
            start=self.buffer.find(SYNC)
            if start<0:
                keep=1 if self.buffer[-1:]==SYNC[:1] else 0
                self.discarded+=len(self.buffer)-keep
                if keep:self.buffer[:]=self.buffer[-1:]
                else:self.buffer.clear()
                break
            if start:self.discarded+=start;del self.buffer[:start]
            if len(self.buffer)<12:break
            version,command,seq,event_id,length=HEADER.unpack_from(self.buffer,2)
            if version!=1 or length>512:
                self.discarded+=1;del self.buffer[0];continue
            total=16+length
            if len(self.buffer)<total:break
            body=self.buffer[2:12+length]
            if zlib.crc32(body)!=struct.unpack_from("<I",self.buffer,12+length)[0]:
                self.crc_errors+=1;del self.buffer[0];continue
            out.append(Frame(command,seq,event_id,bytes(self.buffer[12:12+length])))
            self.frames+=1;del self.buffer[:total]
        return out


class Device:
    def __init__(self,serial_port,run,baud=460800,audit_responses=True):
        import serial
        self.serial=serial.Serial(serial_port,baudrate=baud,timeout=.1,write_timeout=2)
        self.run=run;self.seq=0;self.decoder=Decoder();self.retries=0;self.audit_responses=audit_responses
        self.rx=(run.path/"uart_rx.bin").open("ab");self.tx=(run.path/"uart_tx.bin").open("ab")
        run.event("serial_opened",port=serial_port,baud=baud,bits=8,parity="N",stopbits=1)

    def request(self,command,payload=b"",event_id=0,timeout=3,retries=2):
        command=COMMANDS[command] if isinstance(command,str) else command
        self.seq=(self.seq+1)&65535
        request=Frame(command,self.seq,event_id,payload)
        for attempt in range(retries+1):
            wire=request.encode();self.tx.write(wire);self.tx.flush();self.serial.write(wire)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                data=self.serial.read(max(1,self.serial.in_waiting))
                if not data:continue
                self.rx.write(data);self.rx.flush()
                for frame in self.decoder.feed(data):
                    if frame.seq==self.seq and frame.command==(command|128):
                        if self.audit_responses:
                            self.run.event("serial_response",command=command,seq=self.seq,event_id=frame.event_id,
                                           bytes=len(frame.payload),attempt=attempt,payload_crc32=f"{zlib.crc32(frame.payload):08x}")
                        return frame
            self.retries+=1
            self.run.event("serial_retry",command=command,seq=self.seq,attempt=attempt+1)
        raise TimeoutError(f"No valid response to command {command}, seq {self.seq}")

    def close(self):
        self.serial.close();self.rx.close();self.tx.close()
        self.run.event("serial_closed",crc_errors=self.decoder.crc_errors,retries=self.retries,
                       frames=self.decoder.frames,discarded_bytes=self.decoder.discarded)

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
