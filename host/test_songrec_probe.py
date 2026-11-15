"""Meaningful gate, audio-preservation and malformed-response checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import wave

from songrec_probe import (ProbeSession, SongRecClient, SCHEDULE, acceptance, center_clip,
                           digest, grade, parse_reply)


def fixture(path, seconds=20):
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(bytes(range(256)) * (seconds * 16000 * 2 // 256))


class ProbeTests(unittest.TestCase):
    def test_raw_audio_preserved_and_clip_is_exact_center(self):
        with tempfile.TemporaryDirectory() as folder:
            source, clip = Path(folder)/'source.wav', Path(folder)/'clip.wav'
            fixture(source)
            old = digest(source)
            meta = center_clip(source, clip)
            self.assertEqual(digest(source), old)
            self.assertEqual(meta['clip_start_s'], 4)
            with wave.open(str(source)) as a, wave.open(str(clip)) as b:
                a.setpos(4 * 16000)
                self.assertEqual(a.readframes(12 * 16000), b.readframes(12 * 16000))
                self.assertEqual(b.getnframes(), 12 * 16000)

    def test_candidates_without_match_or_metadata_do_not_become_success(self):
        self.assertFalse(parse_reply({'matches': [], 'track': {'title': 'Fake', 'subtitle': 'Fake'}})['matched'])
        self.assertEqual(parse_reply({'matches': [{}]})['status'], 'invalid_response')
        self.assertEqual(parse_reply({'error': '429'})['status'], 'invalid_response')
        self.assertEqual(grade({'matched': True, 'title': 'Billie Jean (2012 Remaster)', 'artist': 'Michael Jackson'}, SCHEDULE[2]), 'correct')
        self.assertEqual(grade({'matched': True, 'title': 'Billie Jean (Live)', 'artist': 'Michael Jackson'}, SCHEDULE[2]), 'wrong')
        self.assertEqual(grade({'matched': True, 'title': 'Billie Jean (Live Remastered)', 'artist': 'Michael Jackson'}, SCHEDULE[2]), 'wrong')

    def test_gate_requires_six_new_captures_and_no_wrong_song(self):
        rows = [{'index': i, 'kind': 'formal_microphone', 'complete': True, 'grade': 'correct'} for i in range(6)]
        self.assertEqual(acceptance(rows[:5])['status'], 'awaiting_samples')
        rows[5]['grade'] = 'not_found'
        self.assertEqual(acceptance(rows)['status'], 'passed')
        rows[5]['grade'] = 'wrong'
        self.assertEqual(acceptance(rows)['status'], 'failed')
        rows[5].update(kind='auxiliary_not_acceptance')
        self.assertEqual(acceptance(rows)['status'], 'awaiting_samples')
        with self.assertRaises(ValueError):
            acceptance([rows[0], rows[0]])

    def test_cancelled_capture_never_calls_service_and_restart_keeps_gate(self):
        class Fake:
            def recognize(self, *args):
                raise AssertionError('cancelled capture must not call service')
        with tempfile.TemporaryDirectory() as folder:
            session = ProbeSession(folder, Fake())
            index, directory = session.new_capture()
            self.assertIsNone(session.finish_capture(index, directory, {'complete': False}, {}))
            self.assertEqual(session.state['gate']['attempted'], 0)
            restored = ProbeSession(folder, Fake())
            self.assertEqual(restored.folder, session.folder)
            self.assertEqual(restored.state['gate']['status'], 'awaiting_samples')

    def test_network_errors_are_not_misreported_as_missing_songs(self):
        class Process:
            returncode = 1
            def communicate(self, timeout=None):
                return b'', b'HTTP 429 Too Many Requests'
        with tempfile.TemporaryDirectory() as folder, patch('songrec_probe.subprocess.Popen', return_value=Process()):
            result = SongRecClient(Path(folder)/'songrec.exe', interval=0).recognize(Path(folder)/'clip.wav', folder)
            self.assertEqual(result['status'], 'rate_limited')
            self.assertFalse(result['matched'])
            self.assertEqual(result['AudioTag_calls'], 0)

    def test_timeout_kills_only_the_started_process_and_saves_diagnostics(self):
        class Process:
            returncode = None
            killed = False
            def communicate(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired('test fixture', timeout)
                return b'', b'timeout fixture'
            def kill(self):
                self.killed = True
                self.returncode = -9
        process = Process()
        with tempfile.TemporaryDirectory() as folder, patch('songrec_probe.subprocess.Popen', return_value=process):
            result = SongRecClient(Path(folder)/'songrec.exe', interval=0).recognize(Path(folder)/'clip.wav', folder)
            self.assertEqual(result['status'], 'timeout')
            self.assertTrue(process.killed)
            self.assertTrue((Path(folder)/'recognition.json').is_file())

    def test_invalid_audio_is_rejected_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'short.wav'
            fixture(source, seconds=2)
            original = digest(source)
            with self.assertRaises(ValueError):
                center_clip(source, Path(folder)/'clip.wav')
            self.assertEqual(digest(source), original)


if __name__ == '__main__':
    unittest.main()
