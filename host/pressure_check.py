"""Extra real READ loss/slow-consumer evidence without reprogramming the FPGA."""
import json,struct,time
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from protocol import Device
from program import find_port
from capture import checked,status,snap,export_event,list_events
from features import arm

run=Run('physical_slow_export');run.snapshot('实板冻结事件：丢弃READ响应、每块限速15ms、重复整事件校验')
with hardware_lock(run),Device(find_port(),run) as device:
    checked(device.request('HELLO'));arm(device,False)
    before=status(device);event=snap(device)
    checked(device.request('READ',struct.pack('<IH',0,480),event['event_id']))
    run.event('read_response_intentionally_discarded',event_id=event['event_id'],offset=0,bytes=480)
    first=export_event(device,event,run.path/'physical/slow',source='board_pressure',ack=False,on_block=lambda offset:time.sleep(.015))
    frozen=next(e for e in list_events(device) if e['event_id']==event['event_id'])
    second=export_event(device,frozen,run.path/'physical/recovered',source='board_pressure')
    after=status(device)
    assert first['input_hash']==second['input_hash'] and frozen['payload_crc32']==event['payload_crc32']
    assert before['overruns']==after['overruns']
    result={'run_id':run.run_id,'source':'physical_board','slow_export_s':first['export_s'],'repeat_export_s':second['export_s'],
            'input_hash':first['input_hash'],'payload_identical':True,'per_block_delay_s':.015,
            'discarded_read_response_recovered':True,'before':before,'after':after,
            'programming':json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))}
    write_json(run.path/'result.json',result);write_json(ROOT/'state/pressure_result.json',result)
run.status('pressure','passed','真实限速导出与丢弃READ后整事件逐字节一致，前端持续计数且无漏读新增',
           [str((run.path/'result.json').relative_to(ROOT))],'纳入报告边界验证')
run.manifest();print(json.dumps({'run_id':run.run_id,'slow_s':first['export_s'],'repeat_s':second['export_s']}))
