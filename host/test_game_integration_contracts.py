"""Protect the current accepted 1.5 firmware, music logic and tested game rules."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Contracts(unittest.TestCase):
    def test_only_reviewed_existing_runtime_files_change_from_1_5(self):
        state=json.loads((ROOT/'state/game_integration.json').read_text(encoding='utf8'))
        baseline=Path(state['baseline'])
        rows=json.loads((baseline/'baseline.json').read_text(encoding='utf8'))['files']
        allowed={'host/monitor_gui.py','host/monitor_service.py','host/ui/dashboard.py','host/app_paths.py','host/build_shazam_main.py'}
        for row in rows:
            if row['path'].startswith('deliver/') or row['path'] in allowed:
                continue
            with self.subTest(path=row['path']):
                self.assertEqual(hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest(),row['sha256'])

    def test_legacy_service_and_plot_functions_stay_exact(self):
        state=json.loads((ROOT/'state/game_integration.json').read_text(encoding='utf8'))
        baseline=Path(state['baseline'])/'source/host'
        def methods(path,cls):
            node=next(n for n in ast.parse(path.read_text(encoding='utf8')).body if isinstance(n,ast.ClassDef) and n.name==cls)
            return {n.name:ast.dump(n,include_attributes=False) for n in node.body if isinstance(n,ast.FunctionDef)}
        for file,cls,names in (
            ('monitor_service.py','MonitorService',('send','cancel_hook','panel_hook','reset_panel','fft_step','summary')),
            ('monitor_gui.py','Dashboard',('handle_panel_shortcuts','action','arm','connect','download','draw','draw_io','view_event','play'))):
            old=methods(baseline/file,cls);new=methods(ROOT/'host'/file,cls)
            for name in names:
                with self.subTest(file=file,method=name):self.assertEqual(old[name],new[name])


if __name__=='__main__':unittest.main(verbosity=2)
