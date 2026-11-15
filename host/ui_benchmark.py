"""Observe or sequentially benchmark frozen GUIs; never program/configure the board.

CPU is process-tree CPU seconds / elapsed seconds (100% = one logical core).
Poll timings are computed from *measured-window* real monitor packets, not the
service's cumulative startup-to-shutdown percentiles. Raw observations survive
failures. --observe-root is passive and never sends controls or closes a GUI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
import uuid

import psutil


def read_json(path):
    # Existing application evidence writes are in-place. Retry a bounded
    # partial read without changing the application's persistence semantics.
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            if attempt < 2:
                time.sleep(.025)
    return {}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


class ProcessMeter:
    def __init__(self, pid):
        self.root = psutil.Process(pid)
        self.previous = {}

    def sample(self):
        processes = [self.root]
        try:
            processes += self.root.children(recursive=True)
        except psutil.Error:
            pass
        cpu_delta, rss = 0., 0
        for process in processes:
            try:
                identity = (process.pid, process.create_time())
                cpu = process.cpu_times()
                total = cpu.user + cpu.system
                # New workers begin at zero; pre-existing root's first sample
                # establishes the warm-up baseline instead of charging startup.
                before = self.previous.get(identity, total if not self.previous else 0.)
                cpu_delta += max(0., total - before)
                self.previous[identity] = total
                rss += process.memory_info().rss
            except psutil.Error:
                continue
        return cpu_delta, rss


def control(root, run_id, action, arguments=None):
    identifier = uuid.uuid4().hex
    save(root / 'state/monitor_control.json', {
        'id': identifier, 'target_run_id': run_id,
        'action': action, 'arguments': arguments or {},
    })
    return identifier


def wait_gui(root, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_json(root / 'state/monitor_gui.json')
        if state.get('pid') and state.get('state') == 'running':
            return state
        if (root / 'startup_error.log').exists():
            raise RuntimeError('GUI startup failed; see ' + str(root / 'startup_error.log'))
        time.sleep(.25)
    raise TimeoutError('No running GUI state at ' + str(root))


def measured_packets(run_path, start_time, end_time):
    """Filter host_monotonic to include only this observer's measurement window."""
    rows = []
    with (run_path / 'monitor.jsonl').open(encoding='utf8') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # A still-open final buffered line is not a packet.
            if start_time <= row.get('host_monotonic', -1) <= end_time:
                rows.append(row)
    return rows


def observe(root, pid, output, seconds=300, warmup=30, interval=1):
    output.mkdir(parents=True, exist_ok=True)
    state = wait_gui(root)
    run_id = state['run_id']
    deadline = time.monotonic() + warmup
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            raise RuntimeError('GUI exited during warm-up')
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    start_state = read_json(root / 'state/monitor_gui.json')
    run_path = root / 'runs' / run_id
    first = read_json(run_path / 'session_summary.json')
    meter = ProcessMeter(pid)
    meter.sample()
    start = previous = time.monotonic()
    cpu_seconds = 0.
    samples = []
    with (output / 'samples.jsonl').open('w', encoding='utf8') as stream:
        while time.monotonic() - start < seconds:
            time.sleep(min(interval, max(0, seconds - (time.monotonic() - start))))
            current = time.monotonic()
            cpu_delta, rss = meter.sample()
            cpu_seconds += cpu_delta
            gui = read_json(root / 'state/monitor_gui.json')
            sample = {'elapsed_s': current - start, 'cpu_percent': 100 * cpu_delta / max(current - previous, .001),
                      'rss_bytes': rss, 'gui': gui}
            samples.append(sample)
            stream.write(json.dumps(sample, ensure_ascii=False) + '\n')
            stream.flush()
            previous = current
            if gui.get('run_id') != run_id or not gui.get('pid') or not psutil.pid_exists(pid):
                raise RuntimeError('Observed GUI stopped or changed session; raw samples retained')
    end = time.monotonic()
    final = read_json(run_path / 'session_summary.json')
    # Allow the service's existing one-second flush; this does not extend the
    # measured interval or send a request to the worker.
    time.sleep(1.2)
    rows = measured_packets(run_path, start, end)
    intervals = [b['host_monotonic'] - a['host_monotonic'] for a, b in zip(rows, rows[1:])]
    first_row, last_row = (rows[0], rows[-1]) if rows else ({}, {})
    elapsed = end - start
    last_state = samples[-1]['gui']
    missing = {}
    for key, sequence in [('preview_missing_bins', 'preview_seq'), ('xyz_missing_preview_samples', 'xyz_seq')]:
        delta = final.get(key, 0) - first.get(key, 0)
        sequence_delta = last_row.get(sequence, 0) - first_row.get(sequence, 0)
        missing[key] = {'delta': delta, 'per_s': delta / elapsed,
                        'sequence_delta': sequence_delta,
                        'fraction': delta / sequence_delta if sequence_delta > 0 else None}
    errors = {key: last_row.get(key, 0) - first_row.get(key, 0)
              for key in ['uart_framing', 'packet_crc_errors', 'length_errors', 'overruns']}
    result = {
        'run_id': run_id, 'data_root': str(root), 'pid': pid, 'warmup_s': warmup,
        'elapsed_s': elapsed, 'sample_count': len(samples), 'packet_count': len(rows),
        'all_connected': bool(start_state.get('connected')) and all(s['gui'].get('connected') for s in samples),
        'all_live_unpaused': all(s['gui'].get('last_receive_age_s') is not None
                                 and s['gui']['last_receive_age_s'] <= 1.5
                                 and not s['gui'].get('paused') for s in samples),
        'cpu_mean_percent': 100 * cpu_seconds / elapsed,
        'rss_median_bytes': statistics.median(s['rss_bytes'] for s in samples),
        'rss_peak_bytes': max(s['rss_bytes'] for s in samples),
        'render_fps': (last_state.get('render_count', 0) - start_state.get('render_count', 0)) / elapsed,
        'poll_intervals_s': {'median': percentile(intervals, .5), 'p99': percentile(intervals, .99)},
        'missing': missing, 'board_error_deltas': errors,
        'connection_errors': final.get('connection_errors', []),
        'device': final.get('device'), 'epoch_changed': final.get('epoch') != first.get('epoch'),
        'window_monotonic': {'start': start, 'end': end},
    }
    save(output / 'result.json', result)
    return result


def run_case(executable, output, serial, seconds, warmup, width, height, program=False):
    profile = output / 'profile'
    profile.mkdir(parents=True, exist_ok=False)
    save(profile / 'state/ui_preferences.json', {'theme': '浅色'})
    environment = {**os.environ, 'NEXYS_MONITOR_DATA': str(profile), 'NEXYS_PORTABLE_RUNTIME': '1'}
    command = [str(executable)] + (['--serial', serial] if serial else []) + (['--program'] if program else [])
    checksum = hashlib.sha256()
    with executable.open('rb') as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b''):
            checksum.update(chunk)
    save(output / 'launch.json', {'command': command, 'exe_sha256': checksum.hexdigest(),
                                 'data_root': str(profile), 'width': width, 'height': height,
                                 'logical_cpu_count': psutil.cpu_count()})
    process = subprocess.Popen(command, env=environment, cwd=str(output),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    state = None
    try:
        state = wait_gui(profile)
        deadline = time.monotonic() + (150 if program else 30)
        while time.monotonic() < deadline:
            state = read_json(profile / 'state/monitor_gui.json')
            age = state.get('last_receive_age_s')
            if state.get('connected') and age is not None and age < 1.5:
                break
            if process.poll() is not None:
                raise RuntimeError('Owned GUI exited before connection')
            time.sleep(.25)
        else:
            save(output / 'connection_failure.json', {'state': state, 'timeout_s': 150 if program else 30})
            raise RuntimeError('No fresh board data within connection timeout; benchmark stopped before measurement')
        print('CASE_CONNECTED ' + output.name + ' ' + state['run_id'], flush=True)
        identifier = control(profile, state['run_id'], 'resize', {'width': width, 'height': height})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if read_json(profile / 'state/monitor_control_result.json').get('id') == identifier:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('GUI did not acknowledge benchmark geometry')
        result=observe(profile, process.pid, output, seconds, warmup)
        result['firmware_programmed_for_case']=program
        if program:
            expected=read_json(executable.parent/'软件版本.json')['firmware']['build_id']
            assert result['device']['build_id']==expected,'Actual firmware differs from this EXE'
            result['expected_build_id']=expected
            save(output/'result.json',result)
        return result
    finally:
        if state and process.poll() is None:
            control(profile, state['run_id'], 'close')
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # Do not advance to a second UART owner after a hung shutdown.
                save(output / 'shutdown_failure.json', {'pid': process.pid, 'action': 'manual recovery required'})
                raise RuntimeError('Owned GUI did not close; benchmark sequence stopped')


def compare(results):
    before, candidate, after = results
    baseline = lambda key: (before[key] + after[key]) / 2
    checks = {
        'all_runs_connected': all(r['all_connected'] and r['packet_count'] > 10 for r in results),
        'all_runs_live_unpaused': all(r['all_live_unpaused'] for r in results),
        'cpu': candidate['cpu_mean_percent'] <= baseline('cpu_mean_percent') * 1.10,
        'rss': candidate['rss_median_bytes'] <= baseline('rss_median_bytes') + 25 * 1024**2,
        'refresh': candidate['render_fps'] >= baseline('render_fps') * .95,
        'board_identity': (all(r['device'].get('usb_serial')==before['device'].get('usb_serial') and
                               r['device'].get('port')==before['device'].get('port') and
                               r['device'].get('build_id')==r.get('expected_build_id') for r in results)
                           if all(r.get('firmware_programmed_for_case') for r in results)
                           else before['device'] == candidate['device'] == after['device']),
        'no_resets': not any(r['epoch_changed'] for r in results),
        'no_connection_errors': not any(r['connection_errors'] for r in results),
        'no_new_board_errors': not any(candidate['board_error_deltas'].values()),
    }
    for key in ['median', 'p99']:
        values = [r['poll_intervals_s'][key] for r in results]
        checks['poll_' + key] = all(v is not None for v in values) and values[1] <= (values[0] + values[2]) / 2 * 1.10
    for key in candidate['missing']:
        values = [r['missing'][key]['fraction'] for r in results]
        checks[key] = all(v is not None and v >= 0 for v in values) and values[1] <= (values[0] + values[2]) / 2 * 1.10
    return {'passed': all(checks.values()), 'checks': checks, 'runs': results,
            'cpu_definition': 'process tree CPU seconds / wall seconds; 100% is one core'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--observe-root', type=Path)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--serial')
    parser.add_argument('--program-each-case',action='store_true',help='Reload each bundled SRAM bitstream before warm-up; no Flash writes')
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--warmup', type=float, default=30)
    parser.add_argument('--width', type=int, default=1460)
    parser.add_argument('--height', type=int, default=960)
    args = parser.parse_args()
    if args.seconds <= 0 or args.warmup < 0:
        parser.error('seconds must be positive; warmup must be nonnegative')
    args.output = args.output.resolve()
    if args.observe_root:
        root = args.observe_root.resolve()
        state = wait_gui(root)
        result = observe(root, args.pid or state['pid'], args.output, args.seconds, args.warmup)
    else:
        if not args.old or not args.candidate:
            parser.error('Provide --old and --candidate, or passive --observe-root')
        cases = [('A1_old', args.old.resolve()), ('B_candidate', args.candidate.resolve()), ('A2_old', args.old.resolve())]
        results = []
        for name, exe in cases:
            print('CASE_START ' + name, flush=True)
            result = run_case(exe, args.output / name, args.serial, args.seconds, args.warmup,
                              args.width, args.height,args.program_each_case)
            results.append(result)
            print('CASE_DONE ' + name + ' ' + json.dumps({k: result[k] for k in [
                'cpu_mean_percent', 'rss_median_bytes', 'render_fps', 'poll_intervals_s', 'missing']}, ensure_ascii=False), flush=True)
        result = compare(results)
        save(args.output / 'comparison.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('passed', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
