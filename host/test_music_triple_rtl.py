"""XSim registered-tap collector tests, not physical knock/accuracy evidence."""
import argparse,os,re
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO
EXPECTED={'one_two_wait_three_start_no_uart_bypass','adjacent_min_max_inclusive','pre_entry_taps_not_carried',
 'quiet_restarts_sequence','cancel_restarts_sequence','configuration_restarts_sequence','wake_required_and_clean_rearm',
 'busy_taps_never_queue_capture','reset_clears_pending','game_has_no_manual_backdoor','same_clock_config_and_quiet_barriers'}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-ms',type=int,choices=(600,1000),default=600);args=parser.parse_args()
    run=Run('test_music_triple_rtl');sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',ROOT/'tests/tb_music_triple.sv']
    if args.max_ms==1000:
        text=sources[-1].read_text(encoding='utf8').replace("16'd600","16'd1000").replace('boundary(600,600,1)','boundary(1000,1000,1)').replace('boundary(601,150,0)','boundary(1001,150,0)').replace('boundary(150,601,0)','boundary(150,1001,0)')
        fixture=run.path/'tb_music_triple1000.sv';fixture.write_text(text,encoding='utf8');sources[-1]=fixture
    try:
        cases=[]
        for tool,tool_args in [('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_music_triple','-s','triple_sim']),('xsim.bat',['triple_sim','-runall'])]:
            code,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*tool_args],'三击独立采集门控：'+tool,cwd=run.path,timeout=120)
            assert code==0,text[-3000:]
            if tool=='xsim.bat':
                cases=re.findall(r'TRIPLE_CASE (\w+) PASS',text)
                assert set(cases)==EXPECTED and 'PASS MUSIC TRIPLE' in text,(cases,text[-3000:])
        result={'status':'passed','kind':'XSim_registered_detector_boundary_not_physical','run_id':run.run_id,'case_count':len(cases),'cases':cases,
                'CLOCK_HZ':1000,'max_adjacent_gap_ms':args.max_ms,'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources},'firmware_programmed':False,'serial_opened':False,'network_requests':0}
        write_json(run.path/'result.json',result);write_json(ROOT/'state/music_triple_rtl.json',result);print(str(run.path/'result.json'),flush=True)
    except Exception as error:
        write_json(run.path/'result.json',{'status':'failed','run_id':run.run_id,'error':str(error)})
        raise
    finally:run.manifest()
if __name__=='__main__':main()
