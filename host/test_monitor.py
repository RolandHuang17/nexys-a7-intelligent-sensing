"""Digital checks of new monitors; simulated values are never called board measurements."""
import os,hashlib
from audit import ROOT,Run,write_json
from hardware import VIVADO

def test():
    run=Run('digital_monitor');run.snapshot('实时监测扩展的I2C、GPIO和快照协议数字验证')
    sources=[*sorted((ROOT/'rtl').glob('*.sv')),*[ROOT/'tests'/f'tb_{x}.sv' for x in ('gpio_monitor','i2c_register','monitor_core')]]
    cmd=[os.environ['COMSPEC'],'/d','/c',VIVADO.with_name('xvlog.bat'),'-sv','-i',ROOT/'rtl',*sources]
    rc,_=run.command(cmd,'编译整个新增顶层及三个测试台',cwd=run.path,timeout=90)
    if rc:raise RuntimeError('xvlog')
    checks=[]
    for name in ('gpio_monitor','i2c_register','monitor_core'):
        snapshot=name+'_sim'
        rc,_=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name('xelab.bat'),'tb_'+name,'-s',snapshot],
                         '展开测试台 '+name,cwd=run.path,timeout=90)
        if rc:raise RuntimeError(name+' xelab')
        rc,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name('xsim.bat'),snapshot,'-runall'],
                            '运行数字边界测试 '+name,cwd=run.path,timeout=90)
        if rc or 'PASS ' not in text or 'Fatal:' in text:raise RuntimeError(name+' simulation')
        checks.append(name)
    write_json(run.path/'result.json',{'source':'digital_injection','passed':checks})
    from protocol import Frame,Decoder
    from monitor_protocol import monitor_packet,preview_packet,audio_packet,SequenceCursor
    frames={}
    for filename,command in [('monitor_payload',140),('preview_payload',141),('audio_header',142),('audio_payload',142)]:
        tokens=[]
        for line in (run.path/(filename+'.hex')).read_text().splitlines():
            if not line.startswith('//'):tokens.extend(line.split())
        payload=bytes(int(x,16) for x in tokens);frame=Frame(command,123,1,payload)
        decoded=Decoder().feed(frame.encode());assert len(decoded)==1 and decoded[0].payload==payload
        frames[filename]={'payload_hex':payload.hex(),'wire_hex':frame.encode().hex(),
            'wire_sha256':hashlib.sha256(frame.encode()).hexdigest()}
        if filename=='monitor_payload':
            row=monitor_packet(frame)
            assert row['adt_c']==-1 and row['adxl_temperature_raw']==-2048 and row['switches']==0xa5a5
            assert row['presses']==[1,2,3,4,5] and row['releases']==[5,4,3,2,1]
            assert abs(row['die_c']-(-21.1625))<1e-8 and row['xadc_valid_mask']==15
            assert row['xyz_first_seq']==36 and row['xyz_records'][0]['x']==2880
        elif filename=='preview_payload':assert preview_packet(frame)['points'][0]['low']==2048
        elif filename=='audio_header':assert audio_packet(frame)['first_index']==3584
        else:assert audio_packet(frame)['pcm'][0]==2560 and len(audio_packet(frame)['pcm'])==240
    cursor=SequenceCursor();assert len(cursor.accept([{'seq':0xfffffffe},{'seq':0xffffffff},{'seq':0},{'seq':2}]))==4
    assert cursor.missing==1 and not cursor.accept([{'seq':2},{'seq':1}])
    write_json(ROOT/'config/monitor_golden_frames.json',{'source':'digital_injection_from_xsim_monitor_core','run_id':run.run_id,'frames':frames})
    run.event('host_board_contract_passed',checks=['signed temperature','XADC scaling','GPIO bit and counter ordering','ring payload format','snapshot index/count','CRC framing','sequence wrap and dedup'])
    run.status('M1','passed','I2C、全部GPIO去抖、预览回卷与声音快照边界检查通过',
               [(run.path/'result.json').relative_to(ROOT).as_posix()],'进行完整布局布线与实板读取')
    print('RUN_ID='+run.run_id)

if __name__=='__main__':test()
