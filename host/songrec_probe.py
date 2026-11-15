"""Independent SongRec evidence and six-recording acceptance; no board/API keys."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
import uuid
import wave

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf8', errors='replace')

VERSION = '1.0.0'
SONGREC_VERSION = '0.8.2'
TZ = dt.timezone(dt.timedelta(hours=8))
PLAYLIST = (
    ('Hotel California', 'Eagles', 70),
    ('Billie Jean', 'Michael Jackson', 60),
    ('We Will Rock You', 'Queen', 30),
)
SCHEDULE = tuple({'title': title, 'artist': artist, 'position_s': pos, 'repeat': repeat}
                 for title, artist, pos in PLAYLIST for repeat in (1, 2))


def now():
    return dt.datetime.now(TZ).isoformat(timespec='milliseconds')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    for attempt in range(6):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.03 * (attempt + 1))


def default_data():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'SongRecMicTest'


def default_executable():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'SongRec/songrec.exe'
    return Path(__file__).resolve().parent.parent / 'upstream/songrec/0.8.2/app/songrec.exe'


def center_clip(source, target):
    source, target = Path(source), Path(target)
    with wave.open(str(source), 'rb') as wav:
        rate, frames = wav.getframerate(), wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE':
            raise ValueError('需要单声道 PCM16 WAV 文件。')
        if rate not in (8000, 16000) or not 12 * rate <= frames <= 60 * rate:
            raise ValueError('需要 12 至 60 秒、8 或 16kHz WAV 文件。')
        count = rate * 12
        start = (frames - count) // 2
        wav.setpos(start)
        raw = wav.readframes(count)
        if len(raw) != count * 2:
            raise ValueError('WAV 文件数据不完整。')
    if source.resolve() == target.resolve():
        raise ValueError('原始录音必须单独保留。')
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(raw)
    return {'source_sha256': digest(source), 'clip_sha256': digest(target),
            'source_duration_s': frames / rate, 'clip_start_s': start / rate,
            'clip_duration_s': 12, 'sample_rate': rate, 'samples': count,
            'processing': 'center_12s_only_no_gain_no_resample_no_AudioTag'}


def parse_reply(reply):
    if not isinstance(reply, dict) or not isinstance(reply.get('matches'), list):
        return {'status': 'invalid_response', 'matched': False, 'message': '服务响应格式不完整。'}
    if not reply['matches']:
        return {'status': 'not_found', 'matched': False, 'message': 'Shazam 未匹配到歌曲。'}
    track = reply.get('track')
    if not isinstance(track, dict) or not all(isinstance(track.get(k), str) and track[k].strip()
                                              for k in ('title', 'subtitle')):
        return {'status': 'invalid_response', 'matched': False, 'message': '有匹配标记，但缺少歌名或歌手。'}
    return {'status': 'matched', 'matched': True, 'title': track['title'].strip()[:400],
            'artist': track['subtitle'].strip()[:400], 'track_key': str(track.get('key', ''))[:100],
            'source': 'shazam_via_songrec', 'message': 'Shazam 返回歌曲匹配。'}


def song_identity(title, artist):
    # This is only the acceptance grader, never an input to recognition.
    def clean(value):
        value = unicodedata.normalize('NFKC', value).casefold().strip()
        def version_label(match):
            label = match.group(1).strip()
            allowed = r'(?:(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|album version|single version)'
            return '' if re.fullmatch(allowed, label) else match.group(0)
        value = re.sub(r'\s*[\[(]([^\])]+)[\])]', version_label, value)
        value = re.sub(r'\s*[-–—]\s*(?:\d{4}\s*)?remaster(?:ed)?(?:\s+\d{4})?\s*$', '', value)
        return ' '.join(value.split())
    return clean(title), clean(artist)


def grade(result, expected):
    if not result.get('matched'):
        return 'not_found' if result.get('status') == 'not_found' else 'error'
    return 'correct' if song_identity(result['title'], result['artist']) == song_identity(
        expected['title'], expected['artist']) else 'wrong'


def acceptance(rows):
    # A row is an independent finished microphone capture, not a re-query or imported file.
    valid = [r for r in rows if r.get('kind') == 'formal_microphone' and r.get('complete') is True]
    indexes = [r.get('index') for r in valid]
    if len(indexes) != len(set(indexes)) or any(i not in range(6) for i in indexes):
        raise ValueError('验收记录包含重复或无效步骤。')
    correct = sum(r['grade'] == 'correct' for r in valid)
    wrong = sum(r['grade'] == 'wrong' for r in valid)
    finished = len(valid) == 6
    return {'status': ('passed' if correct >= 5 and wrong == 0 else 'failed') if finished else 'awaiting_samples',
            'attempted': len(valid), 'total': 6, 'correct': correct, 'wrong': wrong,
            'not_found': sum(r['grade'] == 'not_found' for r in valid),
            'errors': sum(r['grade'] == 'error' for r in valid),
            'required_correct': 5, 'maximum_wrong': 0,
            'six_new_microphone_recordings_required': True}


class SongRecClient:
    def __init__(self, executable=None, timeout=30, interval=10):
        self.executable = Path(executable or default_executable()).resolve()
        self.timeout, self.interval, self.last_started = timeout, interval, 0.0

    def version(self):
        p = subprocess.run([str(self.executable), '--version'], cwd=self.executable.parent,
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        version = p.stdout.decode('utf8', 'replace').strip()
        if p.returncode != 0 or version != 'songrec ' + SONGREC_VERSION:
            raise RuntimeError('SongRec 版本或运行环境不符合预期。')
        return version

    def recognize(self, clip, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        wait = self.interval - (time.monotonic() - self.last_started)
        if wait > 0:
            time.sleep(wait)
        self.last_started = time.monotonic()
        started = time.monotonic()
        argv = [str(self.executable), 'audio-file-to-recognized-song', str(Path(clip).resolve())]
        p = subprocess.Popen(argv, cwd=self.executable.parent, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            stdout, stderr = p.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            result = {'status': 'timeout', 'matched': False, 'message': '等待超过 30 秒，请稍后手动重试。'}
        else:
            text = stdout.decode('utf8', 'replace').strip()
            try:
                raw = json.loads(text)
            except (ValueError, UnicodeError):
                info = stderr.decode('utf8', 'replace')
                limited = '429' in info or 'too many requests' in info.casefold()
                result = {'status': 'rate_limited' if limited else 'service_error', 'matched': False,
                          'message': '服务限流，请稍后手动重试。' if limited else '网络或识别服务未返回有效结果。'}
            else:
                write_json(folder / 'service_response.json', raw)
                result = parse_reply(raw) if p.returncode == 0 else {
                    'status': 'service_error', 'matched': False, 'message': '识别进程未正常结束。'}
        (folder / 'songrec.stdout.txt').write_bytes(stdout)
        (folder / 'songrec.stderr.txt').write_bytes(stderr)
        result.update(elapsed_s=time.monotonic() - started, exit_code=p.returncode,
                      source='shazam_via_songrec', songrec_version=SONGREC_VERSION,
                      AudioTag_calls=0, key_accesses=0, paid_service_calls=0)
        write_json(folder / 'recognition.json', result)
        return result


class ProbeSession:
    def __init__(self, folder=None, client=None):
        self.root = Path(folder or default_data()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.client = client or SongRecClient()
        pointer = self.root / 'current_session.json'
        self.folder = None
        if pointer.exists():
            name = json.loads(pointer.read_text(encoding='utf8')).get('session', '')
            if name and Path(name).name == name and (self.root / 'sessions' / name / 'session.json').exists():
                self.folder = self.root / 'sessions' / name
        if self.folder is None:
            self.new()
        else:
            self.state = json.loads((self.folder / 'session.json').read_text(encoding='utf8'))
            self.save()

    def new(self):
        identifier = dt.datetime.now(TZ).strftime('%Y%m%dT%H%M%S_') + uuid.uuid4().hex[:8]
        self.folder = self.root / 'sessions' / identifier
        self.state = {'schema': 'songrec_six_microphone_v1', 'version': VERSION, 'started_at': now(),
                      'session': identifier, 'schedule': SCHEDULE, 'rows': []}
        self.save()
        write_json(self.root / 'current_session.json', {'session': identifier})

    def save(self):
        gate = acceptance(self.state['rows'])
        self.state['gate'] = gate
        write_json(self.folder / 'session.json', self.state)
        write_json(self.root / 'gate.json', {**gate, 'session': self.state['session'],
                   'session_file': str(self.folder / 'session.json'), 'updated_at': now()})

    def new_capture(self):
        index = len(self.state['rows'])
        if index >= 6:
            raise ValueError('本轮六项已经完成。')
        directory = self.folder / f'{index+1:02d}_{uuid.uuid4().hex[:8]}'
        directory.mkdir(parents=True)
        return index, directory

    def finish_capture(self, index, directory, metadata, device):
        directory = Path(directory)
        write_json(directory / 'capture.json', {**metadata, 'device': device})
        if not metadata.get('complete'):
            return None
        if index != len(self.state['rows']) or metadata.get('samples') != 320000 or metadata.get('sample_rate') != 16000:
            raise ValueError('本项需要完整的 20 秒电脑麦克风录音。')
        source, clip = directory / 'original.wav', directory / 'center_12s.wav'
        preparation = center_clip(source, clip)
        write_json(directory / 'clip.json', preparation)
        try:
            result = self.client.recognize(clip, directory)
        except Exception as error:
            result = {'matched': False, 'status': 'service_error', 'message': '识别未完成，录音已保留。',
                      'error_type': type(error).__name__}
            write_json(directory / 'recognition.json', result)
        row = {'index': index, 'kind': 'formal_microphone', 'complete': True,
               'expected': SCHEDULE[index], 'result': result, 'grade': grade(result, SCHEDULE[index]),
               'wav': str(source), 'clip': str(clip), 'directory': str(directory),
               'finished_at': now(), **preparation}
        write_json(directory / 'trial.json', row)
        self.state['rows'].append(row)
        self.save()
        return row

    def auxiliary(self, path, *, expected=None, label='文件对照'):
        directory = self.root / 'auxiliary' / (dt.datetime.now(TZ).strftime('%Y%m%dT%H%M%S_') + uuid.uuid4().hex[:8])
        directory.mkdir(parents=True)
        clip = directory / 'center_12s.wav'
        preparation = center_clip(path, clip)
        result = self.client.recognize(clip, directory)
        row = {'kind': 'auxiliary_not_acceptance', 'label': label, 'original': str(path),
               'clip': str(clip), 'expected': expected, 'result': result,
               'grade': grade(result, expected) if expected else 'unlabelled', **preparation}
        write_json(directory / 'trial.json', row)
        return row


def auxiliary_existing(project, session):
    rows = []
    state = json.loads((project / 'state/music_api_phone_round.json').read_text(encoding='utf8'))
    for item in state['results']:
        path = Path(item['job']['metadata']['wav'])
        if path.exists():
            rows.append(session.auxiliary(path, expected={'title': item['title'], 'artist': item['artist']},
                                          label='旧板端录音：' + item['title']))
    local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'AudioTagMicTest/runs'
    for trial in sorted(local.glob('*_pc_mic_api_trial/result.json')):
        record = json.loads(trial.read_text(encoding='utf8'))
        path = Path(record.get('wav', ''))
        if record.get('source') == 'computer_microphone' and path.is_file():
            rows.append(session.auxiliary(path, label='旧电脑录音（未标歌名）：' + trial.parent.name))
    summary = {'time': now(), 'songrec_version': SONGREC_VERSION, 'rows': rows,
               'not_part_of_six_microphone_acceptance': True}
    write_json(session.root / 'existing_recordings.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--songrec', type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--auxiliary-existing', type=Path)
    parser.add_argument('--probe-seconds', type=float)
    parser.add_argument('--device', type=int, default=0)
    args = parser.parse_args()
    folder = (args.data_dir or default_data()).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = None
    gui = not (args.self_check or args.auxiliary_existing or args.probe_seconds)
    if gui:
        import msvcrt
        lock = (folder/'application.lock').open('a+b')
        if lock.seek(0, 2) == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            from tkinter import messagebox
            messagebox.showinfo('测试程序已运行', '请切换到已打开的 SongRec 六项对照窗口。')
            lock.close()
            return
    session = ProbeSession(folder, SongRecClient(args.songrec))
    if args.self_check:
        from pc_mic_capture import input_devices
        result = {'version': VERSION, 'songrec': session.client.version(), 'devices': input_devices(),
                  'frozen': bool(getattr(sys, 'frozen', False)), 'data_directory': str(session.root),
                  'forbidden_imports': [x for x in ('serial', 'music_board', 'music_online', 'music_credentials') if x in sys.modules]}
        assert not result['forbidden_imports']
        write_json(session.root / 'self_check.json', result)
        print(json.dumps(result, ensure_ascii=False))
    elif args.auxiliary_existing:
        result = auxiliary_existing(args.auxiliary_existing, session)
        print(json.dumps({'report': str(session.root / 'existing_recordings.json'),
                          'results': [{'label': r['label'], 'result': r['result'], 'grade': r['grade']} for r in result['rows']]}, ensure_ascii=False))
    elif args.probe_seconds:
        from pc_mic_capture import record
        result = record(args.device, args.probe_seconds, session.root / 'capture_probe.wav')
        write_json(session.root / 'capture_probe.json', result)
        print(json.dumps(result, ensure_ascii=False))
    else:
        from songrec_probe_gui import App
        try:
            session.client.version()
            App(session).root.mainloop()
        finally:
            lock.close()


if __name__ == '__main__':
    main()
