"""Physical event export with packet and whole-event integrity checks."""
import csv,json,struct,time,wave,zlib
from pathlib import Path
import numpy as np
from audit import ROOT,sha256,write_json


def checked(frame):
    if not frame.payload or frame.payload[0]:
        raise RuntimeError(f"Board command {frame.command:#x} error: {frame.payload.hex()}")
    return frame.payload


def status(device):
    p=checked(device.request("STATUS"))
    return {"ready_mask":p[1],"frozen_mask":p[2],"post_mask":p[3],
            "clock_hz":struct.unpack_from("<I",p,4)[0],"ticks":struct.unpack_from("<Q",p,8)[0],
            "pcm_count":struct.unpack_from("<Q",p,16)[0],"xyz_count":struct.unpack_from("<Q",p,24)[0],
            "sensor_identity":f"{struct.unpack_from('<I',p,32)[0]:08x}",
            "sensor_config":f"{struct.unpack_from('<I',p,36)[0]:08x}",
            "xyz":struct.unpack_from("<hhh",p,40),"configured":bool(p[46]),"id_ok":bool(p[47]),
            "overruns":struct.unpack_from("<I",p,48)[0],"xyz_rails":struct.unpack_from("<I",p,52)[0],
            "audio_clips":struct.unpack_from("<I",p,56)[0],"uart_framing":struct.unpack_from("<I",p,60)[0],
            "packet_crc_errors":struct.unpack_from("<I",p,64)[0],"length_errors":struct.unpack_from("<I",p,68)[0],
            "last_xyz_tick":struct.unpack_from("<Q",p,72)[0],"build_id":f"{struct.unpack_from('<I',p,80)[0]:08x}",
            "feature_count":struct.unpack_from('<Q',p,84)[0],"suppressed_post":struct.unpack_from('<I',p,92)[0],
            "suppressed_not_ready":struct.unpack_from('<I',p,96)[0],"suppressed_dedup":struct.unpack_from('<I',p,100)[0],
            "late_xyz":struct.unpack_from('<I',p,104)[0],"threshold_id":struct.unpack_from('<I',p,108)[0],
            "button_pressed":bool(p[125]),"button_presses":struct.unpack_from('<H',p,126)[0],
            "audio_threshold":struct.unpack_from('<I',p,112)[0],"accel_threshold":struct.unpack_from('<I',p,116)[0],
            "pair_window_ticks":struct.unpack_from('<I',p,120)[0],"trigger_mode":p[124]&3,"armed":bool(p[124]&4)}


def list_events(device):
    p=checked(device.request("LIST"));events=[]
    for bank in range(2):
        if not(p[1]&(1<<bank)):continue
        row=p[4+bank*96:4+(bank+1)*96]
        values=struct.unpack_from("<IQQQIIII",row)
        event=dict(zip(("event_id","anchor_tick","first_pcm_index","first_pcm_tick","pcm_count","xyz_count","payload_length","payload_crc32"),values))
        event.update(bank=bank,config_id=struct.unpack_from("<I",row,44)[0],
                     mode=row[48],
                     t_audio=struct.unpack_from("<Q",row,52)[0],t_accel=struct.unpack_from("<Q",row,60)[0],
                     t_confirm=struct.unpack_from("<Q",row,68)[0],window_start=struct.unpack_from("<Q",row,76)[0],
                     window_end=struct.unpack_from("<Q",row,84)[0])
        for name in ('t_audio','t_accel'):
            if event[name]==0xffffffffffffffff:event[name]=None
        events.append(event)
    return events


def snap(device,after_anchor=None):
    deadline=time.monotonic()+5
    while not status(device)["ready_mask"]:
        if time.monotonic()>deadline:raise TimeoutError("no bank READY")
        time.sleep(.05)
    response=device.request("SNAP",retries=0);p=checked(response)
    event_id,anchor=struct.unpack_from("<IQ",p,1)
    device.run.event("snap_anchor",event_id=event_id,anchor_tick=anchor)
    if after_anchor:after_anchor(event_id,anchor)
    deadline=time.monotonic()+4
    while True:
        for event in list_events(device):
            if event["event_id"]==event_id:return event
        if time.monotonic()>deadline:raise TimeoutError("event did not freeze")
        time.sleep(.05)


def export_event(device,event,directory,source="board_snap",ack=True,on_block=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();payload=bytearray();blocks=[]
    for offset in range(0,event["payload_length"],480):
        count=min(480,event["payload_length"]-offset)
        frame=device.request("READ",struct.pack("<IH",offset,count),event["event_id"])
        chunk=checked(frame)[1:]
        if len(chunk)!=count:raise ValueError("READ silently truncated")
        payload.extend(chunk);blocks.append({"offset":offset,"bytes":count,"crc32":f"{zlib.crc32(chunk):08x}"})
        if on_block:on_block(offset)
    (directory/"payload.bin").write_bytes(payload)
    if len(payload)!=event["payload_length"] or zlib.crc32(payload)!=event["payload_crc32"]:
        raise ValueError("whole-event length/CRC mismatch; bank retained")
    audio=np.frombuffer(payload[:48000],dtype="<i2")
    assert len(audio)==24000
    xyz=[struct.unpack_from("<Ihhh",payload,offset) for offset in range(48000,len(payload),10)]
    assert len(xyz)==event["xyz_count"]
    with wave.open(str(directory/"audio.wav"),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(payload[:48000])
    with (directory/"xyz.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f);writer.writerow(("relative_tick","absolute_tick","t_from_anchor_s","x_mg","y_mg","z_mg"))
        for relative,x,y,z in xyz:
            t=event["window_start"]+relative
            writer.writerow((relative,t,(t-event["anchor_tick"])/1e8,x,y,z))
    assert event["window_start"]<=event["first_pcm_tick"]<event["window_start"]+6250
    assert event["first_pcm_tick"]+23999*6250<event["window_end"]
    intervals=np.diff([row[0] for row in xyz])
    assert all(0<=row[0]<150000000 for row in xyz) and np.all(intervals>0)
    event={**event,"source":source,"export_s":time.monotonic()-start,"input_hash":sha256(directory/"payload.bin"),
           "timestamp_semantics":"audio PCM data available / XYZ synchronized DATA_READY, tick=10 ns",
           "audio_peak":int(np.max(np.abs(audio.astype(np.int32)))),"audio_rms":float(np.sqrt(np.mean(audio.astype(float)**2))),
           "audio_std":float(audio.astype(float).std()),"audio_saturated_samples":int(np.count_nonzero((audio==32767)|(audio==-32768))),
           "xyz_interval_ticks":{"min":int(intervals.min()),"max":int(intervals.max()),"mean":float(intervals.mean())} if len(intervals) else {},
           "gravity_mg":float(np.linalg.norm(np.mean(np.array(xyz)[:,1:],axis=0))) if xyz else None}
    write_json(directory/"metadata.json",event);write_json(directory/"crc_blocks.json",blocks)
    if ack:checked(device.request("ACK",struct.pack("<II",len(payload),zlib.crc32(payload)),event["event_id"]))
    device.run.event("event_exported",event_id=event["event_id"],directory=str(directory.relative_to(ROOT)),
                     input_hash=event["input_hash"],bytes=len(payload),crc32=f"{zlib.crc32(payload):08x}",acknowledged=ack)
    return event
