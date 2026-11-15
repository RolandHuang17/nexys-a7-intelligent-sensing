"""Physical UART upload to the shared RTL engine, not a host-only replay."""
import json,time,struct
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from program import find_port
from protocol import Device,Frame
from capture import checked,status
from features import configure,replay,compare_reference

def check(directory):
    run=Run('physical_replay_check');run.snapshot('实板共享引擎逐窗回放与传输坏CRC/丢弃响应恢复')
    write_json(run.path/'programming.json',json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8')))
    with hardware_lock(run),Device(find_port(),run) as device:
        checked(device.request('HELLO'));before=status(device)
        # Raw corrupted request must be ignored without releasing any bank.
        wire=bytearray(Frame(11,60000,0,b'bad CRC probe').encode());wire[-1]^=1
        device.tx.write(wire);device.tx.flush();device.serial.write(wire);time.sleep(.1)
        after=status(device);assert after['packet_crc_errors']==before['packet_crc_errors']+1
        # Discard one complete ECHO response on purpose, then reread the same sequence.
        wire=Frame(11,60001,0,b'discard and retry').encode()
        device.tx.write(wire);device.tx.flush();device.serial.write(wire);time.sleep(.05)
        lost=device.serial.read(device.serial.in_waiting);device.rx.write(lost);device.rx.flush()
        assert lost
        device.tx.write(wire);device.tx.flush();device.serial.write(wire);time.sleep(.05)
        recovered=device.serial.read(device.serial.in_waiting);device.rx.write(recovered);device.rx.flush()
        assert lost==recovered
        configure(device,50,20,50,991)
        started=time.monotonic();rows=replay(device,directory,run.path/'board_replay.json')
        result=compare_reference(rows,directory,50,20,50)
        result.update(replay_wall_s=time.monotonic()-started,bad_crc_rejected=True,
                      discarded_response_recovered=True,before=before,after=status(device),input_directory=str(directory))
        write_json(run.path/'comparison.json',result)
        checked(device.request('REPLAY',b'\x00'))
    run.status('physical_replay_check','passed','真实板端150窗特征、三策略及CRC/丢弃响应恢复均与参考一致',
               [str((run.path/'comparison.json').relative_to(ROOT))], '进入集中真实采样')
    run.manifest();print(json.dumps(result,ensure_ascii=False));print('RUN_ID='+run.run_id)
    return 0

if __name__=='__main__':
    import sys
    raise SystemExit(check(ROOT/sys.argv[1]))
