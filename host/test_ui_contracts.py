"""Regression fences for the UI migration; no GUI, serial port or network used.

The baseline is an external immutable copy, configurable with NEXYS_UI_BASELINE.
Byte comparisons protect service/algorithm/schema files; AST comparisons protect
business callbacks mixed into the GUI. These fences supplement real-board tests.
"""
import ast
import hashlib
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(os.environ.get('NEXYS_UI_BASELINE', r'D:\projects\2222wuxiaoping_codex\nexys-event-recorder'))
PROTECTED = [
    'monitor_service.py', 'monitor_protocol.py', 'protocol.py', 'device_discovery.py',
    'features.py', 'music_board.py', 'music_protocol.py', 'music_library.py',
    'music_store.py', 'music_worker.py', 'music_shazam.py', 'pc_shazam_backend.py',
    'portable_main.py', 'portable_program.py', 'plot_style.py',
]
BUSINESS_METHODS = [
    'mode_number', 'action', 'arm', 'connect', 'download', 'save_settings',
    'refresh_devices', 'choose_device', 'scan_devices', 'download_when_stopped',
    'clear_live', 'pause', 'export_selected', 'export_diagnostics', 'play',
    'load_history', 'guide_update', 'accept', 'close', 'finish_close',
]


def methods(path, class_name):
    tree = ast.parse(path.read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


class PresentationNeutral(ast.NodeTransformer):
    """Ignore only visual keyword values and optional theme registration calls."""
    def visit_Call(self, node):
        node = self.generic_visit(node)
        node.keywords = [k for k in node.keywords if k.arg not in {
            'bg', 'fg', 'background', 'foreground', 'fill', 'outline',
            'highlightbackground', 'activebackground', 'activeforeground',
        }]
        return node

    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            if isinstance(call.func.value, ast.Attribute) and call.func.value.attr == 'theme_manager':
                return None
        return self.generic_visit(node)

    def visit_Attribute(self, node):
        # Embedding only changes dialog ownership from the old Toplevel to Tk.
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr == 'dialog_owner':
            node.attr = 'win'
        return node


def normalized(node):
    return ast.dump(PresentationNeutral().visit(node), include_attributes=False)


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (BASELINE / 'host/monitor_gui.py').exists():
            raise RuntimeError('Baseline missing: set NEXYS_UI_BASELINE to the unchanged 1.2.0 source')

    def test_backend_bytes_unchanged(self):
        for name in PROTECTED:
            with self.subTest(file=name):
                old, new = BASELINE / 'host' / name, ROOT / 'host' / name
                self.assertTrue(old.exists(), str(old))
                self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),
                                 hashlib.sha256(new.read_bytes()).hexdigest())

    def test_firmware_and_offline_assets_unchanged(self):
        for directory in ['rtl', 'release_assets']:
            old_files = {p.relative_to(BASELINE / directory): p for p in (BASELINE / directory).rglob('*') if p.is_file()}
            for relative, old in old_files.items():
                with self.subTest(file=str(relative)):
                    new = ROOT / directory / relative
                    self.assertEqual(hashlib.sha256(old.read_bytes()).digest(), hashlib.sha256(new.read_bytes()).digest())

    def test_dashboard_business_callbacks_unchanged(self):
        old = methods(BASELINE / 'host/monitor_gui.py', 'Dashboard')
        new = methods(ROOT / 'host/monitor_gui.py', 'Dashboard')
        for name in BUSINESS_METHODS:
            if name not in old:
                continue  # Names differ slightly between maintenance releases.
            with self.subTest(method=name):
                self.assertIn(name, new)
                self.assertEqual(normalized(old[name]), normalized(new[name]))

    def test_display_math_and_matplotlib_unchanged(self):
        old = methods(BASELINE / 'host/monitor_gui.py', 'Dashboard')
        new = methods(ROOT / 'host/monitor_gui.py', 'Dashboard')
        for name in ['draw', 'draw_io', 'view_event']:
            with self.subTest(method=name):
                self.assertEqual(normalized(old[name]), normalized(new[name]))

    def test_audio_business_callbacks_unchanged(self):
        old = methods(BASELINE / 'host/music_gui.py', 'MusicPanel')
        new = methods(ROOT / 'host/music_gui.py', 'MusicPanel')
        for name in old.keys() - {'__init__', 'make_widgets', 'show', 'hide', 'draw_wave'}:
            with self.subTest(method=name):
                self.assertEqual(normalized(old[name]), normalized(new[name]))

    def test_navigation_preserves_explicit_exit(self):
        dashboard = methods(ROOT / 'host/monitor_gui.py', 'Dashboard')
        panel = methods(ROOT / 'host/music_gui.py', 'MusicPanel')
        for name in ['show_page', 'open_music']:
            text = ast.unparse(dashboard[name])
            self.assertNotIn('.hide(', text)
            self.assertNotIn('music_disable', text)
        self.assertNotIn('music_disable', ast.unparse(panel['show']))
        self.assertIn('music_disable', ast.unparse(panel['hide']))
        self.assertNotIn('.withdraw(', ast.unparse(panel['hide']))

    def test_tick_retains_queue_and_timer_contract(self):
        tick = methods(ROOT / 'host/monitor_gui.py', 'Dashboard')['tick']
        calls = [n for n in ast.walk(tick) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == 'range'
                            and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 100 for n in calls))
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == 'after'
                            and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 50 for n in calls))
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == 'get_nowait' for n in calls))

    def test_benchmark_statistics(self):
        from ui_benchmark import percentile, compare
        self.assertEqual(percentile([1, 2, 3, 4], .5), 2.5)
        self.assertIsNone(percentile([], .99))
        record = {'all_connected': True, 'all_live_unpaused': True, 'packet_count': 100, 'cpu_mean_percent': 10,
                  'rss_median_bytes': 100, 'render_fps': 20, 'device': {'serial': 'real'},
                  'epoch_changed': False, 'connection_errors': [], 'board_error_deltas': {'crc': 0},
                  'poll_intervals_s': {'median': .05, 'p99': .08},
                  'missing': {'preview_missing_bins': {'fraction': 0}}}
        self.assertTrue(compare([record, record, record])['passed'])
        worse = {**record, 'cpu_mean_percent': 20}
        self.assertFalse(compare([record, worse, record])['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
