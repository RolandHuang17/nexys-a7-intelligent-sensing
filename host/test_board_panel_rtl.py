"""Run the real board_panel RTL in XSim with accelerated display clocks only."""
import os
from pathlib import Path
import re
import sys

from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO

EXPECTED={
    'reset_local_fallback','invalid_commands','session_sync','duplicate_heartbeat_no_restart',
    'stale_session_record_sequence','actual_or_unknown_progress','local_record_priority',
    'game_neutral','watchdog_and_new_session','scan_blank_mutual_exclusion','pwm_endpoints',
    'blackout_display_only','builtin_sources_read_only',
    'physical_glyphs_and_decimal','true_progress_bar_and_orange_rgb',
    'favourite_600ms_retrigger_only_new_sequence','miss_two_inward_waves',
    'ready_triplepulse_and_words','calm_center_out_and_actual_speed',
    'manual_ready_never_advertises_wake',
    'no_pc_stage_means_unknown_hold',
}


def main():
    run=Run('test_board_panel_rtl')
    sources=[ROOT/'rtl/board_panel.sv',ROOT/'tests/tb_board_panel.sv']
    passed=[]
    try:
        for tool,args in [('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_board_panel','-s','panel_sim']),
                          ('xsim.bat',['panel_sim','-runall'])]:
            code,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],
                '板载显示隔离数字测试：'+tool,cwd=run.path,timeout=240)
            assert code==0,tool+' failed; '+text[-2000:]
            if tool=='xsim.bat':
                passed=re.findall(r'PANEL_CASE (\w+) PASS',text)
                assert 'PASS BOARD_PANEL' in text,text[-3000:]
                assert set(passed)==EXPECTED,(passed,EXPECTED-set(passed))
        result={'status':'passed','kind':'XSim_real_RTL_digital_injection_not_physical',
            'run_id':run.run_id,'CLOCK_HZ':1000,'cases':passed,'case_count':len(passed),
            'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources},
            'firmware_programmed':False,'serial_opened':False,'network_requests':0,
            'scope':'display-only logic; existing160000PCM/CRC regression remains separately required'}
        write_json(run.path/'result.json',result);write_json(ROOT/'state/board_panel_rtl.json',result)
        print(str(run.path/'result.json'),flush=True)
    except Exception as error:
        write_json(run.path/'result.json',{'status':'failed','run_id':run.run_id,'cases':passed,
            'error':str(error),'physical_evidence':False})
        raise
    finally:run.manifest()


if __name__=='__main__':main()
