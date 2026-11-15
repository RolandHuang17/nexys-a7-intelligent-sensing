"""Real MusicCore abort simulation plus unchanged full160000-sample CRC golden."""
import os,re,zlib,struct
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO

EXPECTED={'early_record_discard','duplicate_current_id_idempotent','discarded_buffer_unreadable',
 'old_record_and_bad_length_rejected','simultaneous_start_priority','drain_crc_job_cancel',
 'frozen_record_cancel','matching_empty_and_ack_cache_cancel','triple_restart_and_crc'}

def main():
    run=Run('test_music_abort_rtl')
    sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',
             ROOT/'tests/tb_music_abort.sv',ROOT/'tests/tb_music.sv']
    result={'kind':'XSim_digital_injection_not_physical','firmware_programmed':False,'serial_opened':False,'network_requests':0}
    try:
        calls=[('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_music_abort','-s','abort_sim']),
               ('xsim.bat',['abort_sim','-runall']),('xelab.bat',['tb_music','-s','full_music_sim']),
               ('xsim.bat',['full_music_sim','-runall'])]
        for tool,args in calls:
            code,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],
                                 'MUSIC取消/原完整CRC回归：'+tool,cwd=run.path,timeout=240)
            assert code==0,text[-3000:]
            if tool=='xsim.bat' and args[0]=='abort_sim':
                cases=re.findall(r'ABORT_CASE (\w+) PASS',text)
                assert set(cases)==EXPECTED and 'PASS MUSIC ABORT' in text,(cases,text[-2000:])
                actual=int(re.search(r'ABORT_RESTART_CRC ([0-9a-fA-F]+)',text)[1],16)
                expected=zlib.crc32(b''.join(struct.pack('<H',((i*37)^0x9a35)&0xffff) for i in range(32)))
                assert actual==expected,(actual,expected)
                result.update(abort_cases=cases,abort_case_count=len(cases),restart32_crc32=actual)
            elif tool=='xsim.bat':
                assert 'PASS MUSIC' in text,text[-2000:]
                match=re.search(r'MUSIC_CRC ([0-9a-fA-F]+) ([0-9a-fA-F]+)',text);assert match
                raw=b''.join(struct.pack('<H',((i*37)^0x9a35)&0xffff) for i in range(160000))
                actual=[int(match[1],16),int(match[2],16)];expected=[zlib.crc32(raw),zlib.crc32(raw[:256000])]
                assert actual==expected,(actual,expected)
                result.update(existing_full160000_crc32=actual[0],existing_prefix128000_crc32=actual[1],existing_full_regression_passed=True)
        result.update(status='passed',run_id=run.run_id,sources={str(p.relative_to(ROOT)):sha256(p) for p in sources})
        write_json(run.path/'result.json',result);write_json(ROOT/'state/music_abort_rtl.json',result)
        print(str(run.path/'result.json'),flush=True)
    except Exception as error:
        write_json(run.path/'result.json',{**result,'status':'failed','error':str(error),'run_id':run.run_id})
        raise
    finally:run.manifest()

if __name__=='__main__':main()
