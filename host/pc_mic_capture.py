"""Native Windows microphone capture. No UART, FPGA, loopback or board code."""
import ctypes as c
from ctypes import wintypes as w
import math,time,wave,zlib
from pathlib import Path
import numpy as np


class WaveFormat(c.Structure):
    _pack_=1
    _fields_=[('format',w.WORD),('channels',w.WORD),('rate',w.DWORD),('bytes_per_second',w.DWORD),
              ('block_align',w.WORD),('bits',w.WORD),('extra',w.WORD)]


class WaveHeader(c.Structure):
    _fields_=[('data',c.c_void_p),('length',w.DWORD),('recorded',w.DWORD),('user',c.c_size_t),
              ('flags',w.DWORD),('loops',w.DWORD),('next',c.c_void_p),('reserved',c.c_size_t)]


class InputCaps(c.Structure):
    _fields_=[('manufacturer',w.WORD),('product',w.WORD),('version',w.DWORD),('name',w.WCHAR*32),
              ('formats',w.DWORD),('channels',w.WORD),('reserved',w.WORD)]


def api():
    dll=c.WinDLL('winmm.dll')
    dll.waveInGetNumDevs.restype=w.UINT
    dll.waveInGetDevCapsW.argtypes=[c.c_size_t,c.POINTER(InputCaps),w.UINT]
    dll.waveInGetErrorTextW.argtypes=[w.UINT,w.LPWSTR,w.UINT]
    dll.waveInOpen.argtypes=[c.POINTER(c.c_void_p),w.UINT,c.POINTER(WaveFormat),c.c_size_t,c.c_size_t,w.DWORD]
    for name in ('waveInPrepareHeader','waveInUnprepareHeader','waveInAddBuffer'):
        getattr(dll,name).argtypes=[c.c_void_p,c.POINTER(WaveHeader),w.UINT]
    for name in ('waveInStart','waveInStop','waveInReset','waveInClose'):getattr(dll,name).argtypes=[c.c_void_p]
    return dll


def checked(dll,code,action):
    if code:
        message=c.create_unicode_buffer(256);dll.waveInGetErrorTextW(code,message,len(message))
        raise RuntimeError(f'{action}失败（Windows {code}）：{message.value}')


def input_devices():
    dll=api();result=[]
    for device in range(dll.waveInGetNumDevs()):
        caps=InputCaps();checked(dll,dll.waveInGetDevCapsW(device,c.byref(caps),c.sizeof(caps)),'读取输入设备')
        name=caps.name;loopback=any(word in name.casefold() for word in ('立体声混音','stereo mix','loopback','what u hear'))
        result.append({'id':device,'name':name,'channels':caps.channels,'loopback_name':loopback,
                       'label':f'{device} · {name}'})
    return result


def audio_metrics(raw):
    a=np.frombuffer(raw,dtype='<i2').astype(float)
    if not len(a):return {'samples':0,'rms_dbfs':-120,'peak_dbfs':-120,'clipped_samples':0}
    rms=float(np.sqrt(np.mean((a-a.mean())**2)));peak=float(np.max(np.abs(a)))
    return {'samples':len(a),'rms_dbfs':20*math.log10(max(rms,1e-2)/32768),
        'peak_dbfs':20*math.log10(max(peak,1e-2)/32768),'dc_counts':float(a.mean()),
        'clipped_samples':int(np.count_nonzero(np.abs(a)>=32767))}


def record(device,seconds,path,*,stop=None,progress=None,rate=16000):
    """Queue the entire capture before starting, retaining all buffer lifetimes."""
    if rate!=16000 or not 0<seconds<=60:raise ValueError('录音长度或采样率无效')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    dll=api();handle=c.c_void_p();fmt=WaveFormat(1,1,rate,rate*2,2,16,0)
    total=int(seconds*rate);blocks=[];prepared=[];chunks=[];started=None;cancelled=False;frames=0
    checked(dll,dll.waveInOpen(c.byref(handle),int(device),c.byref(fmt),0,0,0),'打开电脑麦克风')
    try:
        for offset in range(0,total,rate//4):
            n=min(rate//4,total-offset);buffer=c.create_string_buffer(n*2)
            header=WaveHeader(c.addressof(buffer),n*2,0,0,0,0,None,0);blocks.append((buffer,header))
            checked(dll,dll.waveInPrepareHeader(handle,c.byref(header),c.sizeof(header)),'准备录音缓冲');prepared.append(header)
            checked(dll,dll.waveInAddBuffer(handle,c.byref(header),c.sizeof(header)),'提交录音缓冲')
        checked(dll,dll.waveInStart(handle),'启动电脑麦克风');started=time.monotonic()
        for buffer,header in blocks:
            while not header.flags&1:
                if stop and stop.is_set():cancelled=True;break
                if time.monotonic()-started>seconds+10:raise TimeoutError('麦克风没有按时返回完整声音，请检查输入设备或权限')
                time.sleep(.025)
            if cancelled:break
            raw=buffer.raw[:header.recorded]
            if header.recorded!=header.length:raise RuntimeError('麦克风返回了不完整数据块，未提交API')
            chunks.append(raw);frames+=len(raw)//2
            if progress:progress(frames,total,audio_metrics(raw))
    finally:
        dll.waveInStop(handle);dll.waveInReset(handle)
        for header in prepared:
            for attempt in range(100):
                code=dll.waveInUnprepareHeader(handle,c.byref(header),c.sizeof(header))
                if code!=33:break
                time.sleep(.01)
            checked(dll,code,'释放录音缓冲')
        checked(dll,dll.waveInClose(handle),'关闭电脑麦克风')
    raw=b''.join(chunks)
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(raw)
    complete=not cancelled and frames==total
    return {'source':'computer_microphone','device_id':int(device),'sample_rate':rate,'channels':1,'sample_bits':16,
        'samples':frames,'expected_samples':total,'duration_s':frames/rate,'complete':complete,'cancelled':cancelled,
        'elapsed_s':time.monotonic()-started if started else None,'pcm_crc32':f'{zlib.crc32(raw):08x}',
        'audio_metrics':audio_metrics(raw),'wav':str(path)}
