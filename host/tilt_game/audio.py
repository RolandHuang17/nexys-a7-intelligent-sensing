"""Small locally synthesized effects; no playback worker or online service."""
import math
from pathlib import Path
import struct
import wave


class SoundBank:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.ready=False

    def prepare(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        for name,notes,duration in (
            ('energy',(880,1320),.10),('core',(523,659,784),.22),
            ('checkpoint',(659,988),.16),('death',(220,147),.18),
            ('win',(523,659,784,1046),.42),('gate_open',(440,880),.16)):
            path=self.directory/(name+'.wav')
            if path.exists():
                continue
            rate=22050
            count=int(rate*duration)
            samples=[]
            for i in range(count):
                t=i/rate
                note=notes[min(len(notes)-1,int(i/count*len(notes)))]
                envelope=min(1,t/.008)*(1-i/count)**1.5
                samples.append(int(4200*envelope*math.sin(math.tau*note*t)))
            with wave.open(str(path),'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(struct.pack('<'+'h'*count,*samples))
        self.ready=True

    def play(self,name):
        if not self.ready:
            return
        path=self.directory/(name+'.wav')
        if not path.exists():
            return
        try:
            import winsound
            winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        except (ImportError,RuntimeError):
            pass
