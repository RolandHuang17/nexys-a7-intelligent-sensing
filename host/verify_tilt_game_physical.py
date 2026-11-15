"""Short real-board telemetry/lifecycle probe; does not claim physical gameplay."""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import statistics
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output=args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ['NEXYS_MONITOR_DATA']=str(args.output/'runtime')
    os.environ['NEXYS_PORTABLE_RUNTIME']='1'
    from audit import Run
    from tilt_game.board import make_service
    from tilt_game.input import TiltInput
    run=Run('tilt_game_physical_connection')
    inbox=queue.Queue()
    service=make_service(run,inbox.put)
    tilt=TiltInput()
    rows=[]
    identity=None
    started=time.perf_counter()
    last_text=''
    restored=False
    errors=[]
    neutral_started=False
    service.start()
    try:
        while time.perf_counter()-started<18 and len(rows)<125:
            try:
                message=inbox.get(timeout=.1)
            except queue.Empty:
                continue
            tilt.feed(message,message.get('received_at',time.perf_counter()))
            if message['kind']=='identity':
                identity=message['device']
            elif message['kind']=='status':
                last_text=message.get('text','')
            elif message['kind']=='data':
                rows.append(message)
                if not neutral_started and tilt.fresh(time.perf_counter()):
                    tilt.begin()
                    neutral_started=True
    finally:
        service.stop_event.set()
        service.join(timeout=15)
        while not inbox.empty():
            message=inbox.get_nowait()
            if message['kind']=='game_session' and message.get('restored'):
                restored=True
            if message['kind']=='game_session' and message.get('restored') is False:
                errors.append(message.get('text'))
        run.manifest()
    latest=[row['row'] for row in rows]
    gravity=[math.sqrt(sum(v*v for v in row['xyz_latest'])) for row in latest]
    samples=[sample for row in rows for sample in row.get('xyz',[])]
    timestamps=[s['tick'] for s in samples]
    neutral_verified=tilt.phase=='right'
    passed=len(rows)>=125 and restored and not service.is_alive() and tilt.received>500 and neutral_verified and all(b>a for a,b in zip(timestamps,timestamps[1:]))
    result={'source':'real_board_monitor_packets','passed':passed,'device':identity,
            'poll_count':len(rows),'fresh_xyz_samples':len(samples),'source_cursor_missing':tilt.missing,
            'strictly_increasing_sample_ticks':all(b>a for a,b in zip(timestamps,timestamps[1:])),
            'gravity_raw_median':statistics.median(gravity) if gravity else None,
            'triggers_restored':restored,'worker_closed':not service.is_alive(),
            'run_directory':str(run.path),'last_status':last_text,'restore_errors':errors,
            'physical_calibration_verified':False,'physical_button_verified':False,
            'physical_neutral_stability_verified':neutral_verified,'neutral_phase':tilt.phase,
            'physical_campaign_completions':0,'playtest_approval':'pending',
            'scope':'connection, real XYZ source, neutral stability including actual Z sign, sequence order, unchanged thresholds and trigger restore; no human axis mapping or gameplay'}
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if not passed:
        raise SystemExit(1)


if __name__=='__main__':
    main()
