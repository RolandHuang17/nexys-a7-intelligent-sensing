"""1.5 cancellation/triple-knock additions against the immutable accepted 1.3 source."""
import ast,hashlib,json,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def functions(source,cls,strip_panel_observer=False):
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    if strip_panel_observer:
        class PresentationOnly(ast.NodeTransformer):
            def visit_Expr(self,n):
                call=n.value
                if (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
                    isinstance(call.func.value,ast.Name) and call.func.value.id=='self' and call.func.attr=='project_panel'):
                    return None
                return self.generic_visit(n)
        node=PresentationOnly().visit(node)
    return {n.name:ast.dump(n,include_attributes=False) for n in node.body if isinstance(n,ast.FunctionDef)}

class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=zipfile.ZipFile(ROOT/'state/panel_baseline_1.3.zip')
        cls.baseline=json.loads((ROOT/'state/panel_baseline.json').read_text(encoding='utf8'))
    @classmethod
    def tearDownClass(cls):cls.archive.close()
    def old(self,name):return self.archive.read(name).decode('utf-8-sig')
    def new(self,name):return (ROOT/name).read_text(encoding='utf-8-sig')
    def test_algorithms_schema_worker_and_protocol_parsers_unchanged(self):
        names=['features.py','monitor_protocol.py','music_library.py','music_store.py',
               'music_shazam.py','pc_shazam_backend.py','portable_program.py','device_discovery.py']
        for name in names:
            with self.subTest(name=name):
                expected=self.baseline['files']['host/'+name]
                self.assertEqual(hashlib.sha256((ROOT/'host'/name).read_bytes()).hexdigest(),expected)
    def test_original_music_protocol_and_recognition_functions_unchanged(self):
        # Cancellation extends MusicEngine and adds abort(); audio processing,
        # worker transactions and every existing protocol encoder/parser stay exact.
        def top_functions(source):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        for name in ('host/music_protocol.py','host/music_worker.py'):
            old=top_functions(self.old(name));new=top_functions(self.new(name))
            for function in old:
                with self.subTest(name=name,function=function):self.assertEqual(old[function],new[function])
    def test_existing_rtl_datapaths_unchanged(self):
        for name,digest in self.baseline['files'].items():
            if not name.startswith('rtl/') or name in ('rtl/recorder_top.sv','rtl/music_core.sv','rtl/build_id.svh'):continue
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
    def test_uart_extension_does_not_change_existing_transport(self):
        for cls in ('Frame','Decoder','Device'):
            self.assertEqual(functions(self.old('host/protocol.py'),cls),functions(self.new('host/protocol.py'),cls))
        def commands(source):
            return ast.literal_eval(next(n.value for n in ast.parse(source).body if isinstance(n,ast.Assign) and
                any(isinstance(t,ast.Name) and t.id=='COMMANDS' for t in n.targets)))
        old=commands(self.old('host/protocol.py'));new=commands(self.new('host/protocol.py'))
        self.assertEqual({k:new[k] for k in old},old);self.assertEqual(set(new)-set(old),{'PANEL'});self.assertEqual(new['PANEL'],16)
    def test_plot_math_matplotlib_and_existing_gui_actions_unchanged(self):
        old=functions(self.old('host/monitor_gui.py'),'Dashboard');new=functions(self.new('host/monitor_gui.py'),'Dashboard')
        for name in ['draw','draw_io','view_event','action','arm','pause','export_selected','export_diagnostics','play','load_history']:
            with self.subTest(name=name):self.assertEqual(old[name],new[name])
    def test_audio_business_actions_unchanged(self):
        old=functions(self.old('host/music_gui.py'),'MusicPanel');new=functions(self.new('host/music_gui.py'),'MusicPanel',strip_panel_observer=True)
        for name in old.keys()-{'__init__','make_widgets','receive','enable','record','settings_changed','start_game','retry','save_state'}:
            with self.subTest(name=name):self.assertEqual(old[name],new[name])
    def test_offline_assets_unchanged_in_source(self):
        allowed={'release_assets/firmware/recorder_top.bit','release_assets/release_manifest.json'}
        changed=[]
        for name,digest in self.baseline['files'].items():
            if name.startswith('release_assets/'):
                if name in allowed:
                    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:changed.append(name)
                    continue
                with self.subTest(name=name):self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
        if changed:
            manifest=json.loads((ROOT/'release_assets/release_manifest.json').read_text(encoding='utf8'))
            self.assertEqual(set(changed),allowed)
            self.assertEqual(manifest['app_version'],'1.5.0');self.assertEqual(manifest['panel_protocol_version'],1)
            for item in manifest['resources']:
                self.assertEqual(hashlib.sha256((ROOT/'release_assets'/item['path']).read_bytes()).hexdigest(),item['sha256'])
            self.assertEqual(hashlib.sha256((ROOT/'release_assets/firmware/recorder_top.bit').read_bytes()).hexdigest(),manifest['firmware']['bitstream_sha256'])

if __name__=='__main__':unittest.main()
