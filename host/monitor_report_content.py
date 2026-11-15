"""New report sections and figures, derived only from archived physical monitor runs."""
import json,re,shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from audit import ROOT,sha256,write_json
from report_content import table,code,num,section
from features import load_event
from plot_style import apply,finish

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def load_rows(path,cutoff):
    lines=Path(path).read_text(encoding='utf8').splitlines();rows=[];tails=[]
    for i,line in enumerate(lines):
        try:row=json.loads(line)
        except json.JSONDecodeError:
            if i!=len(lines)-1:raise
            tails.append({'line':i+1,'reason':'外部停止时最后一条未写完，原文件保留'});continue
        if row['tick']<=cutoff:rows.append(row)
    return rows,tails

def generate_monitor(run):
    evidence=read(ROOT/'state/monitor_evidence.json');build=ROOT/'runs'/evidence['build_run_id']
    probe=read(ROOT/'runs'/evidence['probe_run_id']/'result.json')
    physical=ROOT/'runs'/evidence['physical_gui_session'];summary=read(physical/'session_summary.json')
    guide=read(physical/'physical_guide.json');regression=read(ROOT/'runs'/evidence['regression_run_id']/'result.json')
    ui=read(ROOT/'runs'/evidence['ui_review_run_id']/'review.json')
    assert guide['stage']==4 and guide['high']==guide['low']==65535 and guide['press']==guide['release']==31
    for result in (probe,regression):assert result['programming']['bitstream_sha256']==evidence['bitstream_sha256']
    rows,tails=load_rows(physical/'monitor.jsonl',summary['last']['tick']);assert len(rows)>100
    report=ROOT/'report';dest=report/'generated';figs=report/'figures';index=[]
    plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':False,
        'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    apply(plt)
    def save(fig,name,inputs):
        finish(fig)
        fig.savefig(figs/(name+'.pdf'));fig.savefig(figs/(name+'.png'),dpi=150);plt.close(fig)
        index.append({'figure':name,'inputs':[{'path':str(Path(p).relative_to(ROOT)).replace('\\','/'),'sha256':sha256(p)} for p in inputs],
            'script':'host/monitor_report_content.py','script_sha256':sha256(Path(__file__))})
    start=rows[0]['tick'];times=np.array([(r['tick']-start)/1e8 for r in rows])
    fig,axes=plt.subplots(2,1,figsize=(8,5.7),sharex=True,layout='constrained')
    for key,name,color in [('adt_c','板载温度','#168c82'),('die_c','FPGA芯片温度','#bc5356')]:
        axes[0].plot(times,[r[key] for r in rows],label=name,color=color,linewidth=.9)
    axes[0].set_ylabel('温度 / °C');axes[0].legend(ncol=2,frameon=False)
    for key,name,color in [('vccint_v','核心电压','#2868aa'),('vccaux_v','辅助电压','#cc852d'),('vccbram_v','存储电压','#168c82')]:
        axes[1].plot(times,[r[key] for r in rows],label=name,color=color,linewidth=.9)
    axes[1].set_ylabel('电压 / V');axes[1].set_ylim(.8,2.0);axes[1].legend(ncol=3,frameon=False)
    axes[1].set_xlabel('距本次监测开始 / s')
    for ax in axes:ax.grid(alpha=.2)
    save(fig,'monitor_temperature_voltage',[physical/'monitor.jsonl',physical/'session_summary.json'])
    fig,axes=plt.subplots(2,1,figsize=(8,7),sharex=True,gridspec_kw={'height_ratios':[3,1.3]},layout='constrained')
    for bit in range(16):axes[0].step(times,[((r['switches']>>bit)&1)*.75+bit for r in rows],where='post',color='#2868aa',linewidth=.9)
    axes[0].set_yticks(range(16),[f'SW{i}' for i in range(16)]);axes[0].set_ylabel('各行低位=关，高位=开')
    for bit,name in enumerate(('上','下','左','右','中')):axes[1].step(times,[((r['buttons']>>bit)&1)*.75+bit for r in rows],where='post',color='#168c82',linewidth=.9)
    axes[1].set_yticks(range(5),['上','下','左','右','中']);axes[1].set_xlabel('距本次监测开始 / s')
    axes[0].set_xlim(0,min(times[-1],(guide['tap_start_tick']-start)/1e8+15))
    for ax in axes:ax.grid(axis='x',alpha=.2)
    save(fig,'monitor_gpio',[physical/'monitor.jsonl',physical/'physical_guide.json'])
    snapshot=ROOT/'runs'/evidence['regression_run_id']/'tone_snapshot.npz'
    a=np.load(snapshot);fig,axes=plt.subplots(2,1,figsize=(8,5.2),layout='constrained')
    axes[0].plot(np.arange(512)/16,a['pcm'],color='#2868aa',linewidth=.8);axes[0].set_xlabel('快照内时间 / ms');axes[0].set_ylabel('原始PCM计数')
    axes[1].plot(a['hz'],a['dbfs'],color='#168c82');axes[1].set_xlim(0,8000);axes[1].set_ylim(-100,0)
    axes[1].set_xlabel('频率 / Hz');axes[1].set_ylabel('相对数字满量程 / dBFS');axes[1].axvline(1500,color='#bc5356',linestyle='--',label='1500 Hz测试音');axes[1].legend(frameon=False)
    for ax in axes:ax.grid(alpha=.2)
    save(fig,'monitor_tone',[snapshot,ROOT/'runs'/evidence['regression_run_id']/'result.json'])
    event_dirs=[ROOT/e['directory'] for e in summary['exported_events']]
    event_metas=[read(d/'metadata.json') for d in event_dirs]
    event=event_dirs[0];meta,audio,xyz,first=load_event(event);xyz=np.asarray(xyz)
    fig,axes=plt.subplots(2,1,figsize=(8,5.2),sharex=True,layout='constrained')
    axes[0].plot((first+np.arange(len(audio))*6250-50000000)/1e8,audio,color='#2868aa',linewidth=.6);axes[0].set_ylabel('原始声音 / PCM计数')
    for i,name,color in [(1,'X','#2868aa'),(2,'Y','#cc852d'),(3,'Z','#168c82')]:axes[1].plot((xyz[:,0]-50000000)/1e8,xyz[:,i],label=name,color=color,linewidth=.8)
    for ax in axes:ax.axvline(0,color='#60758a',linestyle='--');ax.grid(alpha=.2)
    axes[1].set_ylabel('加速度 / 标称mg');axes[1].legend(ncol=3,frameon=False);axes[1].set_xlabel('距联合自动保存参考时刻 / s')
    save(fig,'monitor_live_event',[event/'payload.bin',event/'metadata.json'])
    screenshot=ROOT/ui['screenshot'];assert sha256(screenshot)==ui['screenshot_sha256']
    shutil.copy2(screenshot,figs/'monitor_dashboard.png')
    index.append({'figure':'monitor_dashboard','inputs':[{'path':ui['screenshot'],'sha256':ui['screenshot_sha256']}],
        'source':'actual_application_screenshot','ui_review_run_id':evidence['ui_review_run_id']})
    timing=(build/'implementation/timing_summary.rpt').read_text(errors='replace')
    m=re.search(r'\n\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+',timing)
    assert m;wns,tns,whs,ths=map(float,m.groups());assert wns>=0 and whs>=0 and tns==ths==0
    util=(build/'implementation/utilization_routed.rpt').read_text(errors='replace');resources={}
    for label in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs'):
        match=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)\s*\|[^\n]+',util);assert match
        resources[label]=float(match[1])
    write_json(dest/'monitor_implementation_values.json',{'build_run_id':build.name,'WNS_ns':wns,'TNS_ns':tns,'WHS_ns':whs,'THS_ns':ths,'resources':resources})
    write_json(dest/'monitor_figure_index.json',index)
    values={'source':'physical_board','bitstream_sha256':evidence['bitstream_sha256'],'build_id':probe['programming']['build_id'],
        'duration_s':float(times[-1]),'rows':len(rows),'summary':summary,'guide':guide,
        'sensor_ranges':{k:{'min':min(r[k] for r in rows if r[k] is not None),'max':max(r[k] for r in rows if r[k] is not None)}
            for k in ('adt_c','die_c','vccint_v','vccaux_v','vccbram_v','adxl_temperature_raw')},
        'incomplete_tail':tails,'events':[{'event_id':e['event_id'],'input_hash':e['input_hash'],'export_s':e['export_s']} for e in event_metas]}
    write_json(dest/'monitor_measured_values.json',values)
    if tails:run.event('jsonl_incomplete_tail_preserved',source=(physical/'monitor.jsonl').relative_to(ROOT).as_posix(),details=tails)
    text=section('电脑界面和实际读到的通道')
    text+='本章是扩展后版本的实板结果，程序编号为 '+code(values['build_id'])+'。声音、XYZ、板载温度、芯片温度、三路电压、16 个开关和 5 个方向按键已经接入同一电脑界面。ADXL362 的内部温度显示原始计数，尚未把它当作已校准的温度计。\n'
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{monitor_dashboard.png}\caption{实际运行的中文界面。曲线和数值来自开发板，事件列表可打开历史录音和原始波形。}\end{figure}'+'\n'
    last=probe['last']
    text+=table('首次实板读回的数值，不是事先填写的示例',['通道','实际读数','检查依据'],[
        ['ADT7420 板载温度',num(last['adt_c'],2)+' °C','身份CB、配置80，均为十六进制'],
        ['FPGA 芯片温度',num(last['die_c'],2)+' °C','XADC有效标记完整'],
        ['核心电压',num(last['vccint_v'])+' V','XADC原始码及换算值均保存'],
        ['辅助电压',num(last['vccaux_v'])+' V','同上'],['存储电压',num(last['vccbram_v'])+' V','同上'],
        ['ADXL362内部温度',str(last['adxl_temperature_raw'])+' 计数','仅作原始值和变化参考']], 'p{3.3cm}p{2.8cm}p{6cm}')
    text+='这些温度来自不同位置，不能互相当作同一个室温。电压和温度已完成数字读回与合理范围检查，尚未用外部标准仪表作精度标定。完整连续记录如下。\n'
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{monitor_temperature_voltage.pdf}\caption{开关、按键和敲击检查期间的真实温度、电压记录。电脑按帧读取最新值，重复读到的数值也保留。}\end{figure}'+'\n'
    text+=section('全部开关、方向按键和倾斜检查')
    text+='操作者按窗口提示完成动作，并回复“完成”。板端记录中，16 个开关都出现过高、低两种状态，最终回到全关；5 个方向按键都记录到了按下和释放。\n'
    text+=table('逐项检查结果',['输入','实际记录','结果'],[
        ['SW0至SW3','四路均出现高、低电平','通过'],['SW4至SW7','四路均出现高、低电平','通过'],
        ['SW8至SW11','四路均出现高、低电平','通过'],['SW12至SW15','四路均出现高、低电平','通过']]+
        [[name,f'按下 {rows[-1]["presses"][i]} 次，释放 {rows[-1]["releases"][i]} 次','通过'] for i,name in enumerate(('上键','下键','左键','右键','中键'))])
    text+='倾斜检查中，XYZ 相对初始位置的变化模长最大为 '+num(guide['max_tilt_change'],1)+' 计数，放回后连续八帧回到设定范围。这个检查说明方向变化能被读到，不代表倾角绝对误差已经标定。\n'
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{monitor_gpio.pdf}\caption{真实开关、按键时序。每行的低位表示关闭或松开，高位表示开启或按下；各行上下错开便于查看。}\end{figure}'+'\n'
    text+=section('声音快照和原事件记录是否仍然可用')
    text+='电脑播放 1500 Hz、1.2 秒测试音，音量设为 30\\%，取一份 512 点原速声音快照。实测频谱主峰为 '+num(regression['snapshot_peak_hz'],1)+' Hz。录音文件、播放参数、端点和恢复音量的记录均保留。频谱表示相对数字满量程，未标定声压。\n'
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{monitor_tone.pdf}\caption{真实短音的512点波形和频谱。主峰来自板上麦克风记录，不是直接拿播放文件作图。}\end{figure}'+'\n'
    text+='扩展后，手动保存仍取得 24000 个声音点和完整 XYZ。集中敲击检查另取得 '+str(len(event_metas))+' 条联合自动事件，逐条通过长度、整事件 CRC 和 WAV 检查。这里只验收功能，没有把提示敲击次数当成新的独立准确率试验。\n'
    text+=table('扩展后真实联合自动事件',['事件','声音点数','XYZ组数','两路候选间隔/ms','导出/s'],[
        [e['event_id'],e['pcm_count'],e['xyz_count'],num(abs(e['t_audio']-e['t_accel'])/1e5,1),num(e['export_s'])] for e in event_metas])
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{monitor_live_event.pdf}\caption{扩展后版本自动保存的事件 '+str(meta['event_id'])+r'，两路原始数据共用一个时间轴。}\end{figure}'+'\n'
    text+='还将一条新短音记录和一条新敲击记录送回 FPGA 重算，共 '+str(regression['board_reference_windows'])+' 个 10 ms 窗，与独立整数参考逐窗一致。512 字节串口回环通过；故意写错校验的一包被拒绝，板端错误计数按预期增加一次。这个故意制造的错误与正常运行中的传输错误分开统计。\n'
    text+=section('实时刷新、存储和实现结果')
    text+='监测会话摘要覆盖约 '+num(times[-1],1)+' 秒、'+str(len(rows))+' 帧。读取周期中位数为 '+num(summary['poll_intervals_s']['median']*1000,1)+' ms，第 99 百分位为 '+num(summary['poll_intervals_s']['p99']*1000,1)+' ms。屏幕独立刷新，采样、读取和绘图不是同一个频率。\n'
    text+='会话摘要记录声音预览缺 '+str(summary['preview_missing_bins'])+' 个 1 ms 包络组，XYZ 预览缺 '+str(summary['xyz_missing_preview_samples'])+' 组。声音预览只保留有限历史，电脑取数稍晚就会出现缺口；界面用断线显示，缺口计数可查。它与前端漏读分开：这段检查中前端漏读计数从 '+str(rows[0]['overruns'])+' 到 '+str(rows[-1]['overruns'])+'，新增 '+str(rows[-1]['overruns']-rows[0]['overruns'])+'。完整事件使用独立存储和校验，不能用预览的完整程度代替事件校验结果。\n'
    text+=table('扩展后实际布局布线结果',['项目','实测程序结果'],[
        ['主时钟/MHz','100'],['建立时间余量 WNS/ns',num(wns)],['建立时间违例 TNS/ns',num(tns)],
        ['保持时间余量 WHS/ns',num(whs)],['保持时间违例 THS/ns',num(ths)],
        ['LUT',num(resources['Slice LUTs'],0)],['寄存器',num(resources['Slice Registers'],0)],
        ['BRAM Tile',num(resources['Block RAM Tile'],1)],['DSP',num(resources['DSPs'],0)]])
    text+='七路慢速串行输出的 20 ns 传播约束实际生效，布局布线没有严重告警。新增 I²C 用例检查了重复起始、ACK/NACK、负温度、时钟等待和超时；数字监测用例检查了地址回卷、快照冻结、长度越界和编号错误。\n'
    text+=section('失败记录和本次验证的范围')
    text+='首次用 0.4 秒短音取得的快照未出现目标频率，原始包和失败快照保留。随后改为 1.2 秒测试音并延后取样，验证通过。重载固件时还出现过串口无应答，独立重新下载后恢复；下载与界面采集改为分进程执行，并保留对应诊断日志。\n'
    text+='本次已验证实际板子的传感器读回、全部普通开关按键和原声振事件记录。未连接的模拟扩展口不作为现有传感器显示。CPU RESET 会使逻辑重启，PROG 属于 FPGA 配置控制，二者不当作五个普通方向按键来统计。新版本没有重新采集独立留出组，下一章的三策略比较仍归属于原来的位流。\n'
    (dest/'monitor_experiments.tex').write_text(text,encoding='utf8')
    conclusion='本项目完成了一个连接电脑使用的开发板监测系统。现在可以同时看声音、三轴加速度、两处温度、三路内部电压和开关按键状态；ADXL362 的内部温度以原始计数单列。界面还能保存声振事件、播放录音和查看历史波形。\n\n'
    conclusion+='新增通道已有实板读回，16 个开关和 5 个方向按键逐项检查通过，倾斜和联合自动敲击也留下了真实记录。原来的事件窗口仍为前 0.5 秒、后 1 秒，24000 点录音和 XYZ 通过完整性校验。\n'
    conclusion+=section('目前的限制')
    conclusion+='实时预览存在少量缺口，不能当成连续无损录音；需要完整数据时应使用事件保存。温度、电压、加速度和倾角还没有外部仪表标定，声音未换算成绝对声压。芯片温度、板载温度和 ADXL362 内部温度来自不同位置。\n\n'
    conclusion+='原联合触发对轻敲的漏检问题仍保留。前期留出组中，联合 F1 为 0.571，振动单路为 0.750；这次增加监测界面和通道，并没有据此宣称触发准确率提高。\n'
    conclusion+=section('交付和日常使用')
    conclusion+='电脑已经配置好依赖时，在工程根目录执行下列命令即可打开界面。普通连接保留板上尚未导出的事件，重新下载会清除板内临时记录。新数据每次另建运行目录，已有实验包作为封存快照保留。\n'
    conclusion+=r'\begin{lstlisting}'+'\n'+'.\\monitor.ps1\n.\\monitor.ps1 -Program\n.\\run.ps1 build\nlatexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Experiment-template.tex\n'+r'\end{lstlisting}'+'\n'
    conclusion+='交付包括最终 PDF、可重新编译的 LaTeX 源码、完整 RTL、电脑程序、原始实验数据、失败记录、离线 Python 依赖和文件校验清单。老师要求的功能可行性、硬件模块与接口、软件框架流程、核心难点分别在第一、三、四、五章说明。\n'
    (dest/'monitor_conclusions.tex').write_text(conclusion,encoding='utf8')
    appendix=section('扩展版本的证据入口')
    appendix+=table('新增测量、界面与验证文件',['内容','相对工程路径'],[
        ['新增引脚来源',code('config/monitor_pin_connections.json')],['首次新增通道实读',code('runs/'+evidence['probe_run_id']+'/result.json')],
        ['集中实体操作',code('runs/'+evidence['physical_gui_session']+'/physical_guide.json')],['连续原始遥测',code('runs/'+evidence['physical_gui_session']+'/monitor.jsonl')],
        ['操作者反馈',code('runs/'+evidence['physical_observation_run_id']+'/physical_result.json')],['短音及300窗回归',code('runs/'+evidence['regression_run_id']+'/result.json')],
        ['界面检查',code('runs/'+evidence['ui_review_run_id']+'/review.json')],['图表输入索引',code('report/generated/monitor_figure_index.json')]],'p{3cm}p{9.3cm}')
    appendix+='扩展位流 SHA-256：'+code(evidence['bitstream_sha256'])+'。约束 SHA-256：'+code(evidence['config_sha256'])+'。\n'
    for d,e in zip(event_dirs,event_metas):appendix+='\n新自动事件 '+str(e['event_id'])+'：'+code(d.relative_to(ROOT).as_posix())+'，输入 SHA-256：'+code(e['input_hash'])+'。\n'
    (dest/'monitor_evidence.tex').write_text(appendix,encoding='utf8')
    write_json(dest/'monitor_claim_index.json',{'evidence':evidence,'figures':index,'measured_values_sha256':sha256(dest/'monitor_measured_values.json'),
        'generator_sha256':sha256(Path(__file__)),'historical_metrics_are_original_bitstream':True})
    return values
