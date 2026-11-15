"""Identity, target refusal and immutable-resource tests; not physical measurements."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from audit import ROOT,Run,write_json,sha256
from device_discovery import candidates,select_board
from portable_program import compatible_id,openocd_config,release

def port(serial='BOARD001B',name='COM20',vid=0x0403,pid=0x6010):
    return NS(serial_number=serial,device=name,vid=vid,pid=pid,description='USB Serial Port',hwid='',location='1-2.1')

class PortableTests(unittest.TestCase):
    def test_serial_and_com_are_dynamic(self):
        for serial,name in [('OTHER123B','COM19'),('TEST999B','COM108')]:
            b=select_board(None,[port(serial,name)]);self.assertEqual(b.serial,serial[:-1]);self.assertEqual(b.port,name)
    def test_only_ft2232_channel_b(self):
        self.assertEqual(candidates([port('BOARD001A'),port('XXB',vid=0x1234),port(None),port()]),candidates([port()]))
    def test_multiple_requires_selection(self):
        ps=[port(),port('BOARD002B','COM21')]
        with self.assertRaises(RuntimeError):select_board(None,ps)
        self.assertEqual(select_board('BOARD002',ps).port,'COM21')
    def test_missing_and_duplicate_rejected(self):
        for ps in ([],[port(),port(name='COM21')]):
            with self.assertRaises(RuntimeError):select_board(None,ps)
    def test_chip_identity_and_extra_target(self):
        self.assertTrue(compatible_id('JTAG chainpos: 0 Device IDCODE = 0x13631093 Desc: XA7A100T'))
        self.assertTrue(compatible_id('JTAG tap: recorder.tap tap/device found: 0x03631093'))
        for text in ('Device IDCODE = 0x1362c093','firmware CRC 13631093',
                     'Device IDCODE = 0x13631093\nDevice IDCODE = 0x1362c093',''):
            self.assertFalse(compatible_id(text))
    def test_target_serial_is_checked(self):
        self.assertIn('ftdi serial OTHER123',openocd_config('OTHER123'))
        for value in ('x;shutdown','x\ninit','a{evil}', 'x'*65):
            with self.assertRaises(ValueError):openocd_config(value)
    def test_release_resources_and_tamper_rejected(self):
        m=release();self.assertRegex(m['firmware']['build_id'],r'^[0-9a-f]{8}$')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'file.bin').write_bytes(b'good')
            write_json(p/'release_manifest.json',{'resources':[{'path':'file.bin','sha256':sha256(p/'file.bin')}]})
            with patch('portable_program.RESOURCE_ROOT',p):
                release();(p/'file.bin').write_bytes(b'bad')
                with self.assertRaises(ValueError):release()
    def test_data_directory_is_separate_in_bundle_mode(self):
        import os,subprocess
        env={**os.environ,'NEXYS_PORTABLE_RUNTIME':'1','NEXYS_MONITOR_DATA':str(ROOT/'.portable_build/用户 数据')}
        result=subprocess.run([sys.executable,'-c','import sys;sys.path.insert(0,"host");from app_paths import DATA_ROOT,SOURCE_ROOT;assert DATA_ROOT!=SOURCE_ROOT;print(DATA_ROOT)'],env=env,cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':
    run=Run('portable_unit_tests');suite=unittest.defaultTestLoader.loadTestsFromTestCase(PortableTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    write_json(run.path/'result.json',{'source':'host_unit_test','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)})
    run.event('portable_unit_tests_finished',tests=result.testsRun,passed=result.wasSuccessful());run.manifest()
    raise SystemExit(0 if result.wasSuccessful() else 1)
