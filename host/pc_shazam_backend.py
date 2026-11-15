"""ShazamIO-only PC recognition, isolated process deadline and saved evidence."""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit
import wave
from email.utils import parsedate_to_datetime

from songrec_probe import center_clip, digest, grade, now, parse_reply, write_json

VERSION = '1.0.0'
SHAZAMIO_VERSION = '0.9.0'
CORE_VERSION = '2.0.0'
REASONS = {
    'timeout': '识别超时，录音已保留，可以稍后手动重试。',
    'rate_limited': 'Shazam 暂时限流，请稍后手动重试。',
    'network_error': '网络连接未完成，录音已保留。',
    'invalid_response': '服务响应不完整，未将候选当作匹配。',
    'invalid_audio': '声音片段无法生成有效指纹。',
    'worker_error': '识别进程未完成，录音已保留。',
    'cancelled': '录音已停止，本次没有请求识别。',
}


def data_root():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'ShazamMicTest'


def versions():
    return {name: importlib.metadata.version(name) for name in
            ('shazamio', 'shazamio-core', 'aiohttp', 'aiohttp-retry', 'numpy')}


def parse_response(reply):
    result = parse_reply(reply)
    result['source'] = 'shazamio'
    if result['status'] == 'invalid_response':
        result['message'] = REASONS['invalid_response']
    track = reply.get('track', {}) if isinstance(reply, dict) else {}
    if result.get('matched'):
        result['track_url'] = track.get('url', '') if isinstance(track.get('url', ''), str) else ''
    return result


def error_result(error):
    name = type(error).__name__
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        status = 'timeout'
    elif name == 'RateLimited' or getattr(error, 'status', None) == 429:
        status = 'rate_limited'
    elif name in ('FailedDecodeJson', 'BadContentType', 'BadResponseStatus'):
        status = 'invalid_response'
    elif name in ('ValueError', 'InvalidAudio', 'DecodeError'):
        status = 'invalid_audio'
    else:
        status = 'network_error'
    return {'matched': False, 'source': 'shazamio', 'status': status,
            'message': REASONS[status], 'error_type': name}


def retry_after_seconds(header, *, wall_time=None):
    if not isinstance(header, str) or not header.strip():
        return 0.0
    try:
        seconds = float(header)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(header).timestamp()-(time.time() if wall_time is None else wall_time)
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


def validate_clip(path):
    with wave.open(str(path), 'rb') as wav:
        rate = wav.getframerate()
        if (wav.getnchannels(), wav.getsampwidth()) != (1, 2) or rate not in (8000, 16000):
            raise ValueError('识别片段需要 8/16kHz 单声道 PCM16 WAV。')
        if wav.getnframes() != 12 * rate:
            raise ValueError('识别片段必须是 12 秒。')
        raw = wav.readframes(12 * rate)
        if len(raw) != 24 * rate:
            raise ValueError('识别片段数据不完整。')
    return bool(any(raw))


async def recognize_async(clip, folder, *, deadline=25):
    from aiohttp_retry import ExponentialRetry
    from shazamio import Shazam
    from shazamio.client import HTTPClient

    calls = []
    class AuditedHTTP(HTTPClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.trace_config.on_request_end.append(self.observed_response)

        async def observed_response(self, session, context, params):
            if calls:
                calls[-1]['http_status'] = params.response.status
                if params.response.headers.get('Retry-After'):
                    calls[-1]['retry_after_s'] = retry_after_seconds(params.response.headers['Retry-After'])
                write_json(folder/'http_requests.json', calls)

        async def request(self, method, url, **kwargs):
            item = {'number': len(calls)+1, 'method': method, 'host': urlsplit(url).hostname,
                    'started_at': now(), 'completed': False}
            calls.append(item)
            write_json(folder/'http_requests.json', calls)
            try:
                value = await super().request(method, url, **kwargs)
                item['completed'] = True
                return value
            finally:
                item['finished_at'] = now()
                write_json(folder/'http_requests.json', calls)

    # One HTTP attempt. The injected client is explicitly closed by its owner.
    async with AuditedHTTP(retry_options=ExponentialRetry(attempts=1)) as http:
        async with Shazam(http_client=http, segment_duration_seconds=12) as client:
            reply = await asyncio.wait_for(client.recognize(Path(clip)), timeout=deadline)
    write_json(folder/'service_response.json', reply)
    return parse_response(reply)


def worker(clip, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        if not validate_clip(clip):
            result = {'matched': False, 'source': 'shazamio', 'status': 'not_found',
                      'message': '片段为静音，没有发起识别请求。', 'silent_input': True}
        else:
            result = asyncio.run(recognize_async(clip, folder))
    except Exception as error:
        result = error_result(error)
    calls_path = folder/'http_requests.json'
    calls = json.loads(calls_path.read_text(encoding='utf8')) if calls_path.exists() else []
    if result.get('status') == 'rate_limited':
        result['retry_after_s'] = max(60.0, max((c.get('retry_after_s', 0) for c in calls), default=0))
    result.update(service_elapsed_s=time.monotonic()-started, recognized_at=now(),
                  http_requests=len(calls), library_versions=versions(),
                  AudioTag_calls=0, key_accesses=0, paid_service_calls=0)
    write_json(folder/'recognition.json', result)
    return result


def worker_command(clip, directory):
    entry = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).with_name('pc_shazam_tester.py'))]
    return [sys.executable, *entry, '--internal-shazam', str(clip), str(directory)]


def terminate_owned_worker(process):
    # A one-file bootloader can own a Python child. Limit termination to this
    # Popen PID and its descendants, never other running tester instances.
    if os.name == 'nt' and getattr(process, 'pid', None) is not None:
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        process.kill()
    except OSError:
        pass


class ShazamClient:
    def __init__(self, *, timeout=30, interval=30, command=worker_command):
        self.timeout, self.interval, self.command = timeout, interval, command
        self.last_started = 0.0
        self.next_allowed, self.on_wait, self.cancel_event = 0.0, None, None

    def recognize(self, clip, directory):
        directory = Path(directory)
        ready = max(self.last_started+self.interval, self.next_allowed)
        pause = ready-time.monotonic()
        if pause > 0:
            if self.on_wait:
                self.on_wait(pause)
            while time.monotonic() < ready:
                if self.cancel_event and self.cancel_event.is_set():
                    result = {'matched': False, 'source': 'shazamio', 'status': 'cancelled', 'http_requests': 0,
                              'message': '识别等待已取消，本次没有发送请求。'}
                    write_json(directory/'recognition.json', result)
                    return result
                time.sleep(min(.1, max(0, ready-time.monotonic())))
        self.last_started = time.monotonic()
        started = time.monotonic()
        process = subprocess.Popen(self.command(clip, directory), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            stdout, stderr = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            terminate_owned_worker(process)
            stdout, stderr = process.communicate()
            result = {'matched': False, 'source': 'shazamio', 'status': 'timeout', 'message': REASONS['timeout']}
        else:
            try:
                result = json.loads((directory/'recognition.json').read_text(encoding='utf8'))
                if not isinstance(result, dict) or 'matched' not in result or 'status' not in result:
                    raise ValueError('invalid result')
                if process.returncode != 0:
                    raise ValueError('worker failed')
            except (OSError, ValueError):
                result = {'matched': False, 'source': 'shazamio', 'status': 'worker_error', 'message': REASONS['worker_error']}
        (directory/'worker.stdout.txt').write_bytes(stdout)
        (directory/'worker.stderr.txt').write_bytes(stderr)
        result.update(elapsed_s=time.monotonic()-started, worker_exit_code=process.returncode,
                      source='shazamio', AudioTag_calls=0, key_accesses=0, paid_service_calls=0)
        if result.get('status') == 'rate_limited':
            self.next_allowed = time.monotonic()+max(60, result.get('retry_after_s', 0))
        write_json(directory/'recognition.json', result)
        return result


class Backend:
    def __init__(self, folder=None, client=None):
        self.root = Path(folder or data_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.client = client or ShazamClient()

    def new_trial(self, source):
        identifier = now().replace(':', '').replace('-', '').replace('+0800', '')+'_'+uuid.uuid4().hex[:8]
        directory = self.root/'trials'/identifier
        directory.mkdir(parents=True)
        job = {'id': identifier, 'source': source, 'started_at': now(), 'app_version': VERSION,
               'directory': str(directory), 'status': 'created'}
        write_json(directory/'trial.json', job)
        return directory, job

    def save(self, directory, job):
        write_json(Path(directory)/'trial.json', job)
        write_json(self.root/'latest.json', job)
        return job

    def recognize(self, directory, job, source, metadata=None):
        directory, source = Path(directory), Path(source)
        original = directory/'original.wav'
        if original.resolve() != source.resolve():
            shutil.copy2(source, original)
        job.update(wav=str(original), original_input=str(source), metadata=metadata, wav_sha256=digest(original))
        if metadata is not None and not metadata.get('complete'):
            job.update(status='cancelled', result={'matched': False, 'status': 'cancelled', 'source': 'shazamio',
                                                  'message': REASONS['cancelled'], 'http_requests': 0})
            return self.save(directory, job)
        clip = directory/'center_12s.wav'
        prep = center_clip(original, clip)
        job.update(status='recognizing', clip=str(clip), preparation=prep)
        self.save(directory, job)
        result = self.client.recognize(clip, directory)
        job.update(status='complete', result=result, finished_at=now())
        return self.save(directory, job)

    def import_wav(self, path, *, source='imported_WAV_reference', metadata=None):
        directory, job = self.new_trial(source)
        return self.recognize(directory, job, path, metadata)


def verified_songrec_session(path):
    from songrec_probe import acceptance
    session = json.loads(Path(path).read_text(encoding='utf8'))
    rows = session.get('rows', [])
    if len(rows) != 6 or acceptance(rows)['status'] != 'passed':
        raise ValueError('SongRec 六项验收尚未通过。')
    for index, row in enumerate(rows):
        if row['index'] != index or row['kind'] != 'formal_microphone':
            raise ValueError('SongRec 验收步骤无效。')
        if digest(row['wav']) != row['source_sha256'] or digest(row['clip']) != row['clip_sha256']:
            raise ValueError('SongRec 原录音或片段校验不一致。')
        capture = json.loads((Path(row['directory'])/'capture.json').read_text(encoding='utf8'))
        if not capture.get('complete') or capture.get('source') != 'computer_microphone' or capture.get('samples') != 320000:
            raise ValueError('SongRec 原录音不是完整的 20 秒电脑麦克风样本。')
        with wave.open(row['wav'], 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) != (1, 2, 16000, 320000):
                raise ValueError('SongRec 原录音格式不一致。')
    return session


def replay_session(backend, session_file):
    session = verified_songrec_session(session_file)
    report = {'time': now(), 'input_type': 'replay_of_six_real_PC_microphone_recordings',
              'songrec_session': session['session'], 'songrec_gate': session['gate'],
              'source_session_file': str(session_file), 'source_session_sha256': digest(session_file),
              'app_version': VERSION, 'rows': [], 'status': 'running'}
    write_json(backend.root/'validation_source_session.json', session)
    for row in session['rows']:
        record = backend.import_wav(row['wav'], source='replay_of_real_PC_microphone')
        if record['preparation']['clip_sha256'] != row['clip_sha256']:
            raise ValueError('ShazamIO 与 SongRec 实际使用的 12 秒片段不同。')
        report['rows'].append({'index': row['index'], 'expected': row['expected'],
                               'result': record['result'], 'grade': grade(record['result'], row['expected']),
                               'trial_directory': record['directory'], 'wav_sha256': record['wav_sha256'],
                               'clip_sha256': record['preparation']['clip_sha256']})
        write_json(backend.root/'validation_result.json', report)
    report.update(correct=sum(r['grade']=='correct' for r in report['rows']),
                  wrong=sum(r['grade']=='wrong' for r in report['rows']), total=6,
                  errors=sum(r['grade']=='error' for r in report['rows']), finished_at=now())
    report['status'] = 'passed' if report['correct'] >= 5 and report['wrong'] == 0 else 'failed'
    report['same_six_clip_hashes_verified'] = True
    write_json(backend.root/'validation_result.json', report)
    return report
