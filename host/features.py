import csv,struct,time
from pathlib import Path
import numpy as np
from audit import write_json
from capture import checked,status
from reference import feature_reference,Pairing


def configure(device,audio_threshold,accel_threshold,window_ms,config_id=1):
    checked(device.request('SET',struct.pack('<IIII',int(audio_threshold),int(accel_threshold),int(window_ms)*100000,config_id)))


def arm(device,enabled,mode=3):
    checked(device.request('ARM',bytes((mode,int(enabled)))))


def read_features(device,cursor,count=15,source='board_live_features'):
    p=checked(device.request('CAL',struct.pack('<QB',cursor,count)))
    code,n,start,config_id=struct.unpack_from('<BBQI',p)
    if len(p)!=14+32*n or start!=cursor:raise ValueError('CAL length/cursor mismatch')
    rows=[]
    for index in range(n):
        t,a,v,an,xn,flags,reason,cfg,agea,agev=struct.unpack_from('<QIIHHBBHII',p,14+index*32)
        rows.append({'seq':cursor+index,'tick':t,'audio':a if flags&1 else None,'accel':v if flags&2 else None,
                     'audio_n':an,'xyz_n':xn,'audio_cross':bool(flags&4),'accel_cross':bool(flags&8),
                     'joint_pair':bool(flags&16),'joint_confirm':bool(flags&32),'deduplicated':bool(flags&64),
                     't_audio':t-agea if flags&16 else None,'t_accel':t-agev if flags&16 else None,
                     'storage_reason':reason,'config_id_low16':cfg,'source':source})
    return rows


def collect_features(device,duration,progress=None):
    cursor=struct.unpack_from('<Q',checked(device.request('STATUS')),84)[0]
    start=time.monotonic();rows=[]
    while time.monotonic()-start<duration:
        part=read_features(device,cursor)
        rows.extend(part);cursor+=len(part)
        if progress:progress(time.monotonic()-start)
        if not part:time.sleep(.025)
    if len(rows)<duration*90:raise ValueError('feature stream too short or interrupted')
    return rows


def load_event(directory):
    import json
    directory=Path(directory)
    meta=json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
    audio=np.frombuffer((directory/'payload.bin').read_bytes()[:48000],dtype='<i2')
    with (directory/'xyz.csv').open(encoding='utf-8') as f:
        xyz=[(int(row['relative_tick']),int(row['x_mg']),int(row['y_mg']),int(row['z_mg'])) for row in csv.DictReader(f)]
    first=meta['first_pcm_tick']-meta['window_start']
    return meta,audio,xyz,first


def independent_features(directory):
    meta,audio,xyz,first=load_event(directory)
    return feature_reference(audio,xyz,first,end_tick=150000000)


def replay(device,directory,output):
    meta,audio,xyz,first=load_event(directory)
    events=[(first+i*6250,1,int(a),0,0,0) for i,a in enumerate(audio)]
    events += [(t,2,0,x,y,z) for t,x,y,z in xyz]
    events.sort(key=lambda row:row[0])
    for attempt in range(3):
        try:
            checked(device.request('REPLAY',b'\x01'))
            for offset in range(0,len(events),39):
                chunk=events[offset:offset+39]
                body=bytes((2,len(chunk)))+b''.join(struct.pack('<IBhhhh',*e) for e in chunk)
                checked(device.request('REPLAY',body,retries=0))
            checked(device.request('REPLAY',struct.pack('<BI',3,150010004)))
            rows=[]
            while True:
                part=read_features(device,len(rows),source='board_replay')
                if not part:break
                rows+=part
            if len(rows)!=150:raise ValueError(f'REPLAY emitted {len(rows)} windows')
            write_json(output,{'source':'board_replay','input_hash':meta['input_hash'],'rows':rows,'attempt':attempt})
            return rows
        except (TimeoutError,ValueError,RuntimeError) as error:
            device.run.event('replay_attempt_failed',input_hash=meta['input_hash'],attempt=attempt,error=repr(error))
            if attempt==2:raise


def compare_reference(rows,directory,audio_threshold,accel_threshold,window_ms):
    expected=independent_features(directory);pairing=Pairing(audio_threshold,accel_threshold,window_ms*100000)
    for index,(actual,reference) in enumerate(zip(rows,expected)):
        for key in ('tick','audio','accel','audio_n','xyz_n'):
            if actual[key]!=reference[key]:raise ValueError(f'first feature mismatch window {index} {key}: {actual[key]} != {reference[key]}')
        trigger=pairing.step(reference['tick'],reference['audio'],reference['accel']);joint=trigger['joint']
        if actual['audio_cross']!=trigger['audio_cross'] or actual['accel_cross']!=trigger['accel_cross']:
            raise ValueError(f'candidate mismatch window {index}')
        if actual['joint_pair']!=(joint is not None) or actual['joint_confirm']!=(joint is not None and not joint['dedup']):
            raise ValueError(f'joint mismatch window {index}')
        if joint and (actual['t_audio'],actual['t_accel'],actual['tick'])!=(joint['t_audio'],joint['t_accel'],joint['t_confirm']):
            raise ValueError(f'pairing time mismatch window {index}')
    if len(rows)!=len(expected):raise ValueError('window count mismatch')
    return {'windows':len(rows),'features_equal':True,'all_three_strategies_equal':True}
