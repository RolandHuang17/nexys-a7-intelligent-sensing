"""Music command 15: complete, frozen board PCM; never uses preview audio."""
import struct,time,wave,zlib
from pathlib import Path
from audit import sha256,write_json,now

def parse_status(frame):
    p=frame.payload
    if len(p)!=128 or p[1]!=1:raise ValueError('识曲固件未就绪或状态格式不匹配')
    if p[0]:raise RuntimeError('识曲板端拒绝请求，代码 '+str(p[0]))
    def u(fmt,offset):return struct.unpack_from('<'+fmt,p,offset)[0]
    return {'state':p[2],'flags':p[3],'record_id':u('I',4),'target_samples':u('I',8),'samples':u('I',12),
        'sample_rate':u('I',16),'crc32':u('I',20),'first_tick':u('Q',24),'last_tick':u('Q',32),
        'first_index':u('Q',40),'start_tick':u('Q',48),'tick':u('Q',56),'tap_seq':u('I',64),
        'double_seq':u('I',68),'tap_tick':u('Q',72),'double_tick':u('Q',80),'center_seq':u('I',88),
        'high':u('H',92),'low':u('H',94),'center_tick':u('Q',96),'human_tick':u('Q',104),
        'prefix_crc32':u('I',112),'overruns':u('I',116),'delta':u('I',120),'max_samples':u('I',124)}

def music_status(d):return parse_status(d.request('MUSIC',b'\x02',timeout=1))
def configure(d,enabled=True,wake=True,game=False,seconds=10,high=80,low=32,min_ms=150,max_ms=600):
    half=seconds==20
    p=struct.pack('<BBBBIHHHH',0,int(enabled)|int(wake)<<1|int(game)<<2|int(half)<<3,0,0,int(seconds*(8000 if half else 16000)),high,low,min_ms,max_ms)
    return parse_status(d.request('MUSIC',p))
def start(d):
    row=parse_status(d.request('MUSIC',b'\x01'))
    if row['state'] not in (1,2,3) or not row['flags']&8:raise RuntimeError('板端未进入录音，保留状态并等待诊断')
    return row
def finish(d):return parse_status(d.request('MUSIC',b'\x05'))
def abort(d,record_id):
    """Cancel only the addressed recording; retries are idempotent on the board."""
    return parse_status(d.request('MUSIC',b'\x06',int(record_id),timeout=1))
def acknowledge(d,meta):
    return parse_status(d.request('MUSIC',struct.pack('<BII',4,meta['samples'],meta['crc32']),meta['record_id']))
def read_samples(d,meta,offset,count):
    p=d.request('MUSIC',struct.pack('<BIH',3,offset,count),meta['record_id']).payload
    if len(p)<32 or p[0] or p[1]!=1:raise ValueError('长录音数据块无效')
    identifier,returned_offset,n,rate,total,crc=struct.unpack_from('<IIHHII',p,4)
    if (identifier,returned_offset,n,rate,total,crc)!=(meta['record_id'],offset,count,meta['sample_rate'],meta['samples'],meta['crc32']) or len(p)!=32+2*count:
        raise ValueError('长录音编号、偏移、点数或校验元数据不一致')
    return p[32:]

def export(d,meta,directory,*,on_progress=None,ack=True,programming=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);started=time.monotonic();raw=bytearray()
    if meta['state']!=3 or meta['samples']!=meta['target_samples'] or meta['overruns']:
        raise ValueError('录音未完整冻结或有前端冲突，不能识曲')
    for offset in range(0,meta['samples'],240):
        raw.extend(read_samples(d,meta,offset,min(240,meta['samples']-offset)))
        if on_progress:on_progress(len(raw)//2,meta['samples'])
    (directory/'pcm.bin').write_bytes(raw)
    assert len(raw)==meta['samples']*2 and zlib.crc32(raw)==meta['crc32'],'整段PCM校验失败'
    if meta['sample_rate'] not in (8000,16000):raise ValueError('录音采样率未知')
    assert meta['last_tick']-meta['first_tick']==(meta['samples']-1)*(100000000//meta['sample_rate']),'PCM时刻不连续'
    path=directory/'audio.wav'
    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(meta['sample_rate']);w.writeframes(raw)
    result={**meta,'source':'board_microphone','captured_at':now(),'export_s':time.monotonic()-started,
        'duration_s':meta['samples']/meta['sample_rate'],'prefix_8s_samples':8*meta['sample_rate'],
        'pcm_sha256':sha256(directory/'pcm.bin'),'wav_sha256':sha256(path),'programming':programming,'wav':str(path)}
    write_json(directory/'metadata.json',result)
    if ack:acknowledge(d,meta)
    return result
