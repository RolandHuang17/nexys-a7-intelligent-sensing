"""Decode telemetry in physical units while keeping every raw value and source time."""
import struct
import numpy as np
from capture import checked

BUTTONS=('BTNU','BTND','BTNL','BTNR','BTNC')

def unpack(fmt,data,offset):
    values=struct.unpack_from('<'+fmt,data,offset)
    return values[0] if len(values)==1 else list(values)

def monitor_packet(frame):
    p=checked(frame)
    if len(p)<192 or p[1]!=1:raise ValueError('unsupported monitor header')
    count=unpack('H',p,188)
    if count>16 or len(p)!=192+16*count or p[190]!=1:raise ValueError('invalid XYZ telemetry length')
    flags=p[2];mask=p[117];first=unpack('I',p,184)
    raw_xadc=unpack('4H',p,56)
    row={'source':'board_live_monitor','version':1,'build_id':f'{unpack("I",p,4):08x}',
        'tick':unpack('Q',p,8),'pcm_count':unpack('Q',p,16),'xyz_count':unpack('Q',p,24),
        'adxl_configured':bool(flags&1),'adxl_id_ok':bool(flags&2),'adt_configured':bool(flags&4),
        'adt_valid':bool(flags&8),'adxl_temperature_valid':bool(flags&16),'xadc_valid_mask':mask,
        'adt_tick':unpack('Q',p,32),'adt_raw':unpack('h',p,40),'adt_identity':p[42],
        'adt_configuration':p[43],'adt_errors':unpack('I',p,44),'adt_samples':unpack('I',p,124),
        'xadc_tick':unpack('Q',p,48),'xadc_raw':raw_xadc,'xadc_samples':unpack('I',p,120),
        'adxl_temperature_raw':unpack('h',p,64),'adxl_temperature_tick':unpack('Q',p,176),
        'switches_raw':unpack('H',p,66),'switches':unpack('H',p,68),
        'buttons_raw':p[70],'buttons':p[71],'gpio_changes':unpack('I',p,72),
        'presses':unpack('5I',p,76),'releases':unpack('5I',p,96),'temperature_pins':p[116],
        'xyz_latest':unpack('3h',p,128),'overruns':unpack('I',p,136),'xyz_rails':unpack('I',p,140),
        'audio_clips':unpack('I',p,144),'uart_framing':unpack('I',p,148),
        'packet_crc_errors':unpack('I',p,152),'length_errors':unpack('I',p,156),
        'ready_mask':p[160],'frozen_mask':p[161],'post_mask':p[162],
        'mode':p[163]&3,'armed':bool(p[163]&4),'replay':bool(p[163]&8),
        'preview_seq':unpack('I',p,164),'xyz_seq':unpack('I',p,168),'audio_snapshot_id':unpack('I',p,172),
        'xyz_first_seq':first,'xyz_records':[]}
    row['adt_c']=row['adt_raw']/128.0 if row['adt_valid'] else None
    row['die_c']=raw_xadc[0]*503.975/65536-273.15 if mask&1 else None
    for bit,name in ((1,'vccint_v'),(2,'vccaux_v'),(3,'vccbram_v')):
        row[name]=raw_xadc[bit]*3.0/65536 if mask&(1<<bit) else None
    for i in range(count):
        tick,x,y,z,unused=struct.unpack_from('<QhhhH',p,192+16*i)
        row['xyz_records'].append({'seq':(first+i)&0xffffffff,'tick':tick,'x':x,'y':y,'z':z})
    return row

def preview_packet(frame):
    p=checked(frame)
    if len(p)<24 or p[1]!=1:raise ValueError('unsupported audio preview')
    count=p[2];first=unpack('I',p,4);last_tick=unpack('Q',p,8)
    size=unpack('H',p,20);rate=unpack('H',p,22)
    if count>64 or len(p)!=24+count*4 or size!=16 or rate!=16000:raise ValueError('preview shape/rate')
    start=last_tick-((count-1)*16+15)*6250 if count else 0
    points=[]
    for i in range(count):
        low,high=struct.unpack_from('<hh',p,24+4*i)
        if low>high:raise ValueError('min/max order')
        points.append({'seq':(first+i)&0xffffffff,'tick':start+i*100000,'low':low,'high':high})
    return {'source':'board_live_preview','first_seq':first,'last_bin_end_tick':last_tick,
            'pcm_count_low32':unpack('I',p,16),'bin_samples':size,'sample_rate':rate,'points':points}

def audio_packet(frame):
    p=checked(frame)
    if len(p)<32 or p[1]!=1:raise ValueError('unsupported audio snapshot')
    result={'snapshot_id':unpack('I',p,4),'ready':bool(p[2]),'first_tick':unpack('Q',p,8),
            'first_index':unpack('Q',p,16),'samples':unpack('H',p,24),'period_ticks':unpack('H',p,26),
            'offset':unpack('H',p,28),'count':unpack('H',p,30)}
    if result['samples']!=512 or result['period_ticks']!=6250 or len(p)!=32+result['count']*2:raise ValueError('snapshot shape')
    result['pcm']=np.frombuffer(p[32:],dtype='<i2').copy()
    return result

def begin_audio(device):return audio_packet(device.request('AUDIO',struct.pack('<BHH',0,0,0)))
def read_audio(device,identifier,offset,count):
    row=audio_packet(device.request('AUDIO',struct.pack('<BHH',1,offset,count),identifier))
    if row['snapshot_id']!=identifier or row['offset']!=offset or row['count']!=count:raise ValueError('snapshot response mismatch')
    return row

def spectrum(pcm):
    x=np.asarray(pcm,dtype=float);window=np.hanning(len(x));x=x-x.mean()
    amplitude=2*np.abs(np.fft.rfft(x*window))/max(window.sum(),1)/32768
    dbfs=20*np.log10(np.maximum(amplitude,1e-6))
    hz=np.fft.rfftfreq(len(x),1/16000)
    first=max(1,int(np.searchsorted(hz,100)))
    peak=first+int(np.argmax(amplitude[first:]))
    return hz,dbfs,float(hz[peak])

class SequenceCursor:
    def __init__(self):self.last=None;self.missing=0;self.received=0
    def accept(self,records):
        fresh=[]
        for row in records:
            delta=None if self.last is None else (row['seq']-self.last)&0xffffffff
            if delta is not None and (delta==0 or delta>=0x80000000):continue
            if delta is not None:self.missing+=delta-1
            self.last=row['seq'];self.received+=1;fresh.append(row)
        return fresh
