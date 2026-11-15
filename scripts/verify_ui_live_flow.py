"""Verify a running isolated GUI through its existing local control inbox.

This performs real-board recording (ambient sound, no accuracy claim), but never
programs firmware or launches a competing UART owner. It leaves the GUI open.
Run only against the explicitly selected test profile, after A/B/A measurement.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
import sys
import time
import traceback
import wave
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from ui_benchmark import read_json, save, control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--resume', action='store_true', help='Resume the same recorded job from an existing output after an observer interruption')
    args = parser.parse_args()
    root = args.data_root.resolve()
    report = {'data_root': str(root), 'purpose': 'real_board_ui_flow_ambient_not_recognition_accuracy',
              'firmware_programmed': False, 'online_requests_intended': 0,
              'commands': [], 'stages': [], 'checks': {}}
    gui_path = root / 'state/monitor_gui.json'
    music_path = root / 'state/music_gui.json'
    gui = read_json(gui_path)
    run_id = gui.get('run_id')
    report['run_id'] = run_id

    def wait(predicate, description, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = read_json(gui_path)
            if snapshot.get('run_id') and snapshot['run_id'] != run_id:
                raise RuntimeError('GUI session changed during ' + description)
            value = predicate()
            if value:
                return value
            time.sleep(.1)
        raise TimeoutError(description)

    def send(action, arguments=None):
        identifier = control(root, run_id, action, arguments)
        report['commands'].append({'id': identifier, 'action': action, 'arguments': arguments or {}})
        wait(lambda: read_json(root / 'state/monitor_control_result.json').get('id') == identifier,
             'control acknowledgement: ' + action)

    def stage(name):
        value = {'stage': name, 'host_monotonic': time.monotonic(),
                 'gui': read_json(gui_path), 'music': read_json(music_path)}
        report['stages'].append(value)
        save(args.output, report)
        print(name, flush=True)
        return value

    try:
        if args.resume:
            existing = read_json(args.output)
            if existing.get('run_id') != run_id or not existing.get('job_id'):
                raise RuntimeError('Resume requires the same existing GUI run and saved job ID')
            report = existing
            previous_error = report.pop('exception', None)
            report.setdefault('observer_recoveries', []).append({'reason': previous_error, 'resumed_monotonic': time.monotonic()})
            report['passed'] = False
            job_id = report['job_id']
            stage('resumed_same_real_job_after_observer_read_race')
        else:
            if not gui.get('pid') or gui.get('state') != 'running' or not gui.get('connected'):
                raise RuntimeError('Selected profile does not have a running connected GUI')
            if gui.get('last_receive_age_s') is None or gui['last_receive_age_s'] > 1.5:
                raise RuntimeError('Selected GUI has no fresh board data')
            if read_json(music_path).get('busy'):
                raise RuntimeError('Existing audio task is busy; leave it intact and retry after completion')
            if gui.get('paused'):
                send('pause')
                wait(lambda: not read_json(gui_path).get('paused'), 'initial unpause')
            send('ui_page', {'page': 'monitor'})
            send('pause')
            wait(lambda: read_json(gui_path).get('paused'), 'pause state')
            first = stage('paused_baseline')['gui']
            time.sleep(2.2)
            second = stage('paused_sampling_continues')['gui']
            report['checks']['pause_freezes_render_but_sampling_continues'] = (
                second['render_count'] == first['render_count'] and second['last_board_tick'] > first['last_board_tick'])
            send('ui_theme', {'theme': '深色'})
            time.sleep(1.2)
            themed = stage('theme_changed_while_paused')['gui']
            report['checks']['theme_keeps_pause_and_sampling'] = (
                themed['paused'] and themed['render_count'] == first['render_count'] and themed['last_board_tick'] > second['last_board_tick']
                and read_json(root / 'state/ui_preferences.json').get('theme') == '深色')
            send('pause')
            wait(lambda: not read_json(gui_path).get('paused'), 'unpause state')
            time.sleep(1.2)
            resumed = stage('render_resumed')['gui']
            report['checks']['unpause_resumes_render'] = resumed['render_count'] > first['render_count']
            # Selecting auto first enforces the existing GUI's full 20-second value;
            # no audio is submitted. The actual recording uses offline policy only.
            send('music_policy', {'policy': '自动'})
            send('music_policy', {'policy': '仅离线'})
            wait(lambda: read_json(music_path).get('policy') == 'offline', 'offline test policy')
            previous_job = read_json(music_path).get('job_id')
            send('music_record')
            started = wait(lambda: (lambda row: row if row.get('busy') and row.get('job_id') and row['job_id'] != previous_job else None)(read_json(music_path)),
                           'new real recording job', timeout=15)
            job_id = started['job_id']
            report['job_id'] = job_id
            stage('real_recording_started')
            wait(lambda: (read_json(music_path).get('status') or {}).get('target_samples') == 160000,
                 '20-second board target')
            switches = [('ui_page', {'page': 'events'}), ('ui_theme', {'theme': '浅色'}),
                        ('ui_page', {'page': 'monitor'}), ('ui_theme', {'theme': '深色'}),
                        ('ui_page', {'page': 'audio'})]
            continuity = []
            for action, arguments in switches:
                prior_time = read_json(music_path).get('time')
                send(action, arguments)
                updated = wait(lambda: (lambda row: row if row.get('time') != prior_time else None)(read_json(music_path)),
                               'music state update after ' + action)
                continuity.append(updated.get('busy') and updated.get('job_id') == job_id)
                stage('during_recording_' + action + '_' + next(iter(arguments.values())))
            report['checks']['recording_survives_pages_and_themes'] = all(continuity)
        def completed_job():
            live = read_json(music_path)
            if live.get('job_id') == job_id and not live.get('busy') and live.get('wav') and live.get('result') is not None:
                return live
            # Wake mode can legitimately start a second recording after the
            # first finishes. Recover only the original immutable job, and
            # require both its SQLite result and board completion audit event.
            database = root / 'music/music.sqlite3'
            if not database.exists():
                return None
            with sqlite3.connect('file:' + database.as_posix() + '?mode=ro', uri=True) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute('SELECT * FROM history WHERE id=?', (job_id,)).fetchone()
            if row is None:
                return None
            finished = None
            for line in (root / 'runs' / run_id / 'actions.jsonl').read_text(encoding='utf8').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('kind') == 'music_job_finished' and event.get('job_id') == job_id:
                    finished = event
            if finished is None:
                return None
            report['completion_evidence'] = {'source': 'SQLite_readonly_and_board_job_finished_audit',
                                              'job_id': job_id, 'finished_event': finished,
                                              'history_mode': row['mode'], 'history_status': row['status'],
                                              'subsequent_live_job_id': live.get('job_id')}
            return {'job_id': job_id, 'busy': False, 'policy': row['mode'],
                    'wav': row['wav'], 'result': json.loads(row['details'])}
        complete = wait(completed_job, 'complete recording export and local result', timeout=args.timeout)
        stage('real_recording_complete')
        wav_path = Path(complete['wav'])
        metadata = read_json(wav_path.parent / 'metadata.json')
        pcm = (wav_path.parent / 'pcm.bin').read_bytes()
        with wave.open(str(wav_path), 'rb') as recording:
            wav_info = {'channels': recording.getnchannels(), 'sample_width': recording.getsampwidth(),
                        'rate': recording.getframerate(), 'frames': recording.getnframes()}
            wav_pcm = recording.readframes(recording.getnframes())
        digest = lambda value: hashlib.sha256(value).hexdigest()
        report['recording'] = {'wav': str(wav_path), 'metadata': metadata, 'wav_info': wav_info,
                               'pcm_crc32_computed': zlib.crc32(pcm), 'pcm_sha256_computed': digest(pcm),
                               'wav_sha256_computed': digest(wav_path.read_bytes()),
                               'matched': complete['result'].get('matched'),
                               'recognition_order': complete['result'].get('recognition_order'),
                               'accuracy_assessed': False}
        report['checks']['offline_policy_used'] = (complete.get('policy') == 'offline'
                                                   and complete['result'].get('mode') == 'offline'
                                                   and complete['result'].get('recognition_order') == 'offline_only')
        report['checks']['full_20s_8k_real_board_pcm'] = (
            wav_info == {'channels': 1, 'sample_width': 2, 'rate': 8000, 'frames': 160000}
            and metadata.get('source') == 'board_microphone' and metadata.get('samples') == 160000
            and metadata.get('target_samples') == 160000 and metadata.get('overruns') == 0
            and len(pcm) == 320000 and pcm == wav_pcm)
        report['checks']['full_crc_hash_and_tick_continuity'] = (
            zlib.crc32(pcm) == metadata.get('crc32')
            and digest(pcm) == metadata.get('pcm_sha256')
            and digest(wav_path.read_bytes()) == metadata.get('wav_sha256')
            and metadata['last_tick'] - metadata['first_tick'] == 159999 * 12500)
        send('music_disable')
        wait(lambda: not read_json(music_path).get('enabled') and not read_json(music_path).get('busy'), 'explicit audio exit')
        report['checks']['explicit_exit_restores_monitoring'] = True
        stage('explicit_audio_exit_complete')
    except Exception:
        report['exception'] = traceback.format_exc()
    finally:
        report['passed'] = len(report['checks']) == 8 and all(report['checks'].values()) and not report.get('exception')
        save(args.output, report)
        print(json.dumps({'passed': report['passed'], 'checks': report['checks'],
                          'exception': report.get('exception')}, ensure_ascii=False, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
