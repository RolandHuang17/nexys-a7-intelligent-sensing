"""Real MusicCore quiet integration simulation, including full PCM CRC parity."""
import os,re,zlib
import numpy as np
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO


def main():
    run=Run('test_music_panel_quiet')
    sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',ROOT/'tests/tb_music_panel_quiet.sv']
    try:
        for tool,args in [('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_music_panel_quiet','-s','music_quiet_sim']),
                          ('xsim.bat',['music_quiet_sim','-runall'])]:
            code,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],
                '显示切换静默与音乐核心隔离：'+tool,cwd=run.path,timeout=240)
            assert code==0,tool+' failed; '+text[-2000:]
            if tool=='xsim.bat':
                assert 'PASS MUSIC_PANEL_QUIET' in text,text[-2500:]
                match=re.search(r'MUSIC_PANEL_CRC ([0-9a-fA-F]+) ([0-9a-fA-F]+)',text);assert match
                raw=((np.arange(160000,dtype=np.uint32)*37)^0x9a35).astype('<i2').tobytes()
                assert int(match[1],16)==zlib.crc32(raw)
                assert int(match[2],16)==zlib.crc32(raw[:256000])
                cases=re.findall(r'MUSIC_PANEL_CASE (\w+) PASS',text);assert len(cases)==6
        result={'status':'passed','kind':'XSim_real_MusicCore_digital_injection_not_physical',
            'run_id':run.run_id,'cases':cases,'samples':160000,'pcm_crc32':zlib.crc32(raw),
            'prefix_crc32':zlib.crc32(raw[:256000]),'CLOCK_HZ':1000,
            'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources},
            'firmware_programmed':False,'serial_opened':False}
        write_json(run.path/'result.json',result);write_json(ROOT/'state/music_panel_quiet.json',result)
        print(str(run.path/'result.json'),flush=True)
    except Exception as error:
        write_json(run.path/'result.json',{'status':'failed','error':str(error),'physical_evidence':False});raise
    finally:run.manifest()


if __name__=='__main__':main()
