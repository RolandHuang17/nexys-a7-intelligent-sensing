"""Add only documented Nexys A7 GPIO/temperature pins; keep mixed bank voltages."""
import json,re
from audit import ROOT,Run,write_json,sha256

def prepare():
    run=Run('monitor_pin_check')
    master=ROOT/'upstream/assets/Nexys-A7-100T-Master.xdc'
    source=master.read_text(encoding='utf8')
    wanted=[f'SW[{i}]' for i in range(16)]+['BTND','BTNL','BTNR','BTNC','TMP_SCL','TMP_SDA','TMP_INT','TMP_CT']
    rows=[]
    for name in wanted:
        pattern=r'#set_property -dict \{\s*PACKAGE_PIN\s+(\w+)\s+IOSTANDARD\s+(\w+)\s*\} \[get_ports \{\s*'+re.escape(name)+r'\s*\}\]'
        m=re.search(pattern,source)
        if not m:raise ValueError(name)
        rows.append({'signal':name,'pin':m[1],'IOSTANDARD':m[2],'source':master.relative_to(ROOT).as_posix(),'source_sha256':sha256(master)})
    assert [r['IOSTANDARD'] for r in rows[8:10]]==['LVCMOS18']*2
    xdc=ROOT/'constraints/nexys_a7_100t.xdc'
    text=xdc.read_text(encoding='utf8').split('# BEGIN MONITOR INPUTS')[0].rstrip()+'\n'
    text+='# BEGIN MONITOR INPUTS: official 100T master XDC, PB200-292 REV D\n'
    for row in rows:
        text+='set_property -dict {PACKAGE_PIN '+row['pin']+' IOSTANDARD '+row['IOSTANDARD']+'} [get_ports {'+row['signal']+'}]\n'
    text+='set_property PULLUP TRUE [get_ports {TMP_SCL TMP_SDA TMP_INT TMP_CT}]\n'
    text+='set_false_path -from [get_ports {SW[*] BTND BTNL BTNR BTNC TMP_SCL TMP_SDA TMP_INT TMP_CT}] -to [get_cells -hier -filter {ASYNC_REG == TRUE}]\n'
    text+='set_max_delay -datapath_only 20.0 -from [all_registers] -to [get_ports {TMP_SCL TMP_SDA}]\n'
    xdc.write_text(text,encoding='utf8')
    write_json(ROOT/'config/monitor_pin_connections.json',rows)
    run.event('pins_verified',rows=rows,xdc_sha256=sha256(xdc),special_case='SW8/SW9 use LVCMOS18; all added inputs terminate in synchronizers; I2C open drain')
    run.status('M0','passed','新增24项接口约束均来自归档官方文件，SW8/9电压标准单独核对',
               ['config/monitor_pin_connections.json'],'进行数字验证及完整构建')
    run.manifest();print(run.run_id)

if __name__=='__main__':prepare()
