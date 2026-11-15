"""Generate plain Chinese report text from the original measured evidence."""
import json,re
from pathlib import Path
import numpy as np
from audit import ROOT,sha256,write_json
from figures import generate
from features import load_event

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def code(s):
    s=str(s).replace('\\','/')
    return (r'\nolinkurl{' if len(s)>40 else r'\code{')+s+'}'
def num(value,digits=3):return '未定义' if value is None else f'{value:.{digits}f}'
def table(caption,headers,rows,columns=None):
    columns=columns or 'l'*len(headers)
    return (r'\begin{table}[H]\centering\caption{'+caption+r'}\small\begin{tabular}{'+columns+r'}\toprule'+'\n'+
            ' & '.join(headers)+r'\\\midrule'+'\n'+'\n'.join(' & '.join(map(str,row))+r'\\' for row in rows)+
            '\n'+r'\bottomrule\end{tabular}\end{table}'+'\n')
def section(title):return '\n'+r'\section{'+title+'}\n'

def generate_content(evaluation):
    evaluation=Path(evaluation);results=read(evaluation/'results.json');collection=ROOT/'runs'/results['collection_run_id']
    session=read(collection/'session.json');config=results['config'];report=ROOT/'report';dest=report/'generated'
    figure_index=generate(collection,evaluation,report)
    program=session['programming'];implementation=ROOT/'runs'/program['build_run_id']/'implementation'
    timing=(implementation/'timing_summary.rpt').read_text(errors='replace')
    match=re.search(r'\n\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+',timing)
    if not match:raise ValueError('Cannot extract routed setup/hold summary')
    wns,tns,whs,ths=map(float,match.groups())
    if min(wns,whs)<0 or tns!=0 or ths!=0:raise ValueError('Report requires actual timing pass')
    util=(implementation/'utilization_routed.rpt').read_text(errors='replace');resources={}
    for label in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs'):
        m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)\s*\|[^\n]+',util)
        if not m:raise ValueError('Missing resource: '+label)
        resources[label]=float(m[1])
    write_json(dest/'implementation_values.json',{'build_run_id':program['build_run_id'],'WNS_ns':wns,'TNS_ns':tns,
        'WHS_ns':whs,'THS_ns':ths,'resources':resources,'timing_input_sha256':sha256(implementation/'timing_summary.rpt')})
    (dest/'values.tex').write_text('\\newcommand{\\BuildId}{'+program['build_id']+'}\n',encoding='utf8')
    metas=[read(ROOT/t['directory']/'metadata.json') for t in session['trials']]
    intervals=np.concatenate([np.diff(np.array([row[0] for row in load_event(ROOT/t['directory'])[2]],dtype=np.int64))/1e5 for t in session['trials']])
    write_json(dest/'xyz_interval_statistics.json',{'source':'all adjacent DATA_READY timestamps within each of 30 physical trial windows',
        'intervals':len(intervals),'unit':'ms','min':float(intervals.min()),'p01':float(np.percentile(intervals,1)),
        'median':float(np.median(intervals)),'p99':float(np.percentile(intervals,99)),'max':float(intervals.max()),
        'input_hashes':[m['input_hash'] for m in metas]})
    modes=read(collection/'single_modes.json');live=read(collection/'live.json');quiet=results['quiet60']
    before=read(collection/'status_before.json');after=read(collection/'status_after.json')
    pressure_path=ROOT/'state/pressure_result.json';pressure=read(pressure_path) if pressure_path.exists() else None
    if pressure and pressure['programming']['bitstream_sha256']!=program['bitstream_sha256']:raise ValueError('压力试验位流不符')
    ma=results['holdout']['audio']['metrics'];mv=results['holdout']['accel']['metrics'];mj=results['holdout']['joint']['metrics']

    text=section('实验怎么安排')
    text+='正式实验共 30 次，分成开发组和留出组。每组都有轻敲桌面、只播放声音、保持安静各五次，顺序事先随机安排，两次之间至少相隔五秒。每次先手动保存原始数据，再用相同数据比较三种判断方式。这样不会因为某个方法漏检，就没有数据可分析。\n\n'
    stimulus=session.get('stimulus',{})
    if stimulus.get('stimulus_kind')=='computer_tone':
        probe=read(ROOT/'runs'/session['stimulus_validation_run_id']/'result.json')
        text+='纯声试验由笔记本内置扬声器外放 '+str(stimulus['frequency_hz'])+' Hz 的短音，每次 '+str(int(stimulus['duration_s']*1000))+' ms，Windows 音量为 '+str(round(stimulus['volume_scalar']*100))+r'\%。'
        text+='采样前先检查板子确实录到了短音，频谱主峰为 '+num(probe['post']['dominant_hz'],1)+' Hz。声音大小和电脑到板子的精确距离没有标定；扬声器也可能通过桌面带来少量振动，这是实验条件的限制。\n\n'
    else:
        text+='纯声试验是在板旁说“测试”，不触碰桌面。声压和人与板的距离没有精确测量。\n\n'
    text+='开始前安静采集十秒。开发组结束后，声音阈值定为 '+str(config['thresholds']['audio'])+'，振动阈值定为 '+str(config['thresholds']['accel'])+'，两路允许的时间差定为 '+str(config['window_ms'])+' ms。留出组使用这些参数，不再调整。弱响应和漏检照常计入结果。\n'
    text+=table('阈值的计算依据（数值为各通道特征的计数）',['通道','静置中位数','MAD','开发组安静P99上取整','最终阈值'],
        [[name,num(config['statistics'][key]['median'],1),num(config['statistics'][key]['MAD'],1),
          config['statistics'][key]['development_quiet_p99_ceiling'],config['thresholds'][key]]
         for key,name in (('audio','声音'),('accel','振动'))])
    text+='开发组中，20、50、80 ms 三种配对间隔均找到三次轻敲、漏掉两次、没有误报，F1 均为 0.750。结果相同，因此按事先规则选择 50 ms。\n'

    text+=section('先看三条真实记录')
    text+='每张图从上到下依次是录到的声音、XYZ 三轴振动、声音变化量和振动变化量。虚线表示阈值，空心圆表示变化量第一次从阈值以下越到阈值以上；紫色竖点线表示联合判断成功的时刻。\n\n'
    text+='第一张是一次真实在线敲击，系统自己判断并保存了事件 38，图中能看到明显变化。它说明自动记录确实运行过。后两张分别取留出组的第一条轻敲记录和第一条纯声记录，没有专挑检测成功的例子。第一条轻敲响应很弱，仍作为漏检保留。\n\n'
    text+='XYZ 在图中减去了各轴平均值，方便看变化，算法仍使用原始数值。两张留出图的原始数据纵轴范围相同；在线敲击幅度更大，单独使用了纵轴范围。手动片段重算声音特征时要重新初始化，前 0.1 秒特征不绘出，原始声音和评分区间没有删改。\n'
    for entry in figure_index:
        caption=('真实在线敲击，事件 '+str(entry['event_id'])+'，由板子自动保存。' if entry['source']=='board_live' else
                 ('留出组第一条轻敲，事件 '+str(entry['event_id'])+'：振动变化较弱，没有形成联合触发。' if entry['figure'].startswith('tap') else
                  '留出组第一条纯声，事件 '+str(entry['event_id'])+'：播放固定短音，不敲桌面。'))
        width=r'.92\linewidth' if entry['source']=='board_live' else r'\linewidth'
        text+=r'\begin{figure}[H]\centering\includegraphics[width='+width+']{'+entry['figure']+r'.pdf}\caption{'+caption+r'}\end{figure}'+'\n'

    text+=r'\clearpage'+section('同一批数据，三种方法各做得怎样')
    text+='留出组有五次轻敲和十次非敲击（五次纯声、五次安静）。一次轻敲中至少报出一次，记为找到；非敲击时也报出，则记为误报。漏掉的轻敲记为漏检。同一试次多报几次另外统计，不重复增加“找到”的次数。\n\n'
    text+='每条 1.5 秒记录的前半秒用于建立计算状态，只对参考时刻之后的一秒评分。三种方法使用同样的输入和初始条件。全部原始记录送回 FPGA 重算，共 '+str(results['board_reference_windows'])+' 个 10 ms 窗，与独立 Python 程序逐窗结果一致。这里只说明两种实现算得一致，真实自动保存另行测试。\n'
    text+=table('留出组结果：五次轻敲、十次非敲击',['方法','找到/5','漏检/5','误报/10','正确不报/10'],
        [[name,m['TP'],m['FN'],m['FP'],m['TN']] for name,m in (('仅声音',ma),('仅振动',mv),('声振联合',mj))])
    text+='声音单路虽然五次轻敲都报了，但十次非敲击也全部报了，所以不能说它已经能可靠区分敲击。振动单路找到了三次轻敲；联合判断只找到两次。两者都没有把这十次非敲击报成敲击。\n\n'
    text+='因此，本次联合判断相对声音单路减少了误报，但相对振动单路没有减少更多误报，反而多漏了一次。原先希望“两路一起看会更好”，这批数据没有支持这个结论。\n'
    text+=table('常用评价指标（越接近1越好）',['方法','精确率 Precision','召回率 Recall','F1'],
        [[name,num(m['Precision']),num(m['Recall']),num(m['F1'])] for name,m in (('仅声音',ma),('仅振动',mv),('声振联合',mj))])
    text+='Precision 表示“报出的试次有多少真的是轻敲”；Recall 表示“五次轻敲找到了多少”；F1 同时考虑前两项。计算式为\n'
    text+=r'\[P=\frac{TP}{TP+FP},\qquad R=\frac{TP}{TP+FN},\qquad F_1=\frac{2TP}{2TP+FP+FN}.\]'+'\n'
    text+='TP 是找到的轻敲，FP 是误报，FN 是漏检，TN 是正确不报；分母为零时记为未定义。\n'
    text+=table('误报出现在哪里，以及一次试次内多报了几次',['方法','纯声误报/5','安静误报/5','额外触发'],
        [[name,*[results['holdout'][key]['metrics'][k] for k in ('sound_false_trials','quiet_false_trials','extra_triggers')]]
         for key,name in (('audio','仅声音'),('accel','仅振动'),('joint','声振联合'))])
    if collection.name=='20261113T232625_950296_collect':
        text+='有一条联合漏检可以直接解释：留出组第 14 次试验（轻敲）的振动候选在参考时刻后约 0.750 秒，附近的声音候选在约 0.680 秒，两者相隔 70 ms，超过设定的 50 ms。第一条和最后一条轻敲则没有形成振动候选，仅凭记录不能确定是敲得太轻，还是动作超出了评分时间。上述试次都保留，没有根据这些结果改参数或补采。\n'

    text+=section('真实自动保存和一分钟安静观察')
    text+='除了对已存数据重算，还分别启用了三种自动模式：声音模式得到事件 36，振动模式得到事件 37，联合模式得到事件 38。这三条均由板子自动保存，没有用手动命令代替触发。\n\n'
    text+='联合事件 38 中，声音和振动的候选时刻相差 10 ms，符合 50 ms 条件，因此保存成功。这个差值是程序判断时刻的差，不是测得的声音传播时间。完整板端计数值见附录。\n'
    text+=table('连续安静观察',['项目','实际结果'],[
        ['观察时长/s',num(quiet['duration_s'])],['10 ms 窗数量',quiet['windows']],['声音候选次数',quiet['audio_candidates']],
        ['振动候选次数',quiet['accel_candidates']],['联合配对次数',quiet['pairs']],['联合确认次数',quiet['confirmations']],
        ['声音采样点',quiet['pcm_samples']],['XYZ 组数',quiet['xyz_samples']],['新增前端漏读',quiet['overrun_delta']]])
    text+='一分钟内仍出现了单路候选，但没有形成联合确认。这是本次环境下的结果，不能据此保证换一张桌子或换一种声音仍然没有误报。\n'

    text+=section('采集、传输和 FPGA 资源检查')
    text+=table('30 条对照记录的实际数据量',['项目','最小','中位数','最大'],[
        [name,*[num(float(v),digits) for v in (np.min(vals),np.median(vals),np.max(vals))]]
        for name,vals,digits in [('声音点数',[m['pcm_count'] for m in metas],0),('XYZ 组数',[m['xyz_count'] for m in metas],0),
            ('数据长度/B',[m['payload_length'] for m in metas],0),('导出时间/s',[m['export_s'] for m in metas],3),('XYZ 相邻间隔/ms',intervals,3)]])
    text+='振动的实际相邻间隔中位数约为 '+num(float(np.median(intervals)))+' ms，因此不能简单认为每秒必有 200 组。图中的 mg 按手册标称比例换算，传感器没有做六面静态标定；早期静置重力模长约为 0.75 g，说明绝对加速度值还不能当作已校准的测量结果。\n\n'
    text+='本轮采集前后，漏读、音频饱和、串口帧错误和数据包校验错误等计数都没有新增。传感器饱和计数开机时已有 3 次，本轮也没有增加；不能把它写成从未发生过。\n'
    text+=table('实际测量程序的布局布线结果',['项目','结果'],[
        ['主时钟/MHz','100'],['最差建立时间余量 WNS/ns',num(wns)],['总建立时间违例 TNS/ns',num(tns)],
        ['最差保持时间余量 WHS/ns',num(whs)],['总保持时间违例 THS/ns',num(ths)],
        ['查找表 LUT',num(resources['Slice LUTs'],0)],['寄存器',num(resources['Slice Registers'],0)],
        ['块存储器 BRAM Tile',num(resources['Block RAM Tile'],1)],['乘法运算单元 DSP',num(resources['DSPs'],0)]])
    text+='建立和保持时间检查均通过，说明在所设约束下能满足 100 MHz 时序。测量使用的程序编号为 '+code(program['build_id'])+'；具体位流校验值、约束和原始工具报告均保留在附录所列文件中。\n'

    text+=section('边界测试，以及遇到的问题')
    text+=table('主要检查内容',['检查对象','检查方法与结果'],[
        ['声音转换','输入已知比特序列，逐点与独立计算结果比较，通过。'],
        ['触发边界','检查等于阈值、50 ms 边界、两路先后次序和 300 ms 去重，通过。'],
        ['存储边界','检查历史不足、地址回卷、计数进位和确认晚到，通过。'],
        ['串口传输','发送坏校验包，丢弃响应后重读，重复操作及断线后恢复，通过。'],
        ['存储占满','导出时另一组仍能记录；两组占满后拒绝第三条，已有数据保持不变。']], 'p{2.1cm}p{10.3cm}')
    if pressure:
        text+='另一次实板压力测试故意丢弃一份读取响应，并在每个 480 B 数据块后多等 15 ms。第一次导出用时 '+num(pressure['slow_export_s'])+' 秒，随后正常重读用时 '+num(pressure['repeat_export_s'])+' 秒；两次数据完全一致，没有提前释放记录，也没有新增前端漏读。\n\n'
    text+='实现中遇到三类问题：既有 USB 驱动导致 Vivado 无法枚举，改用已有 OpenOCD，未更换驱动；短音初次未可靠录到，核对声源、音量和 1500 Hz 频谱后才采样；运算路径不满足时序，分步计算并调整位宽后重建。失败、正式弱响应、误报和漏检均保留原始日志，不充当成功试次；结果只对应本次板子、桌面及声振条件。\n'
    (dest/'experiments.tex').write_text(text,encoding='utf8')

    conclusion='本项目实现了声音和振动的同时记录，支持手动保存及三种自动模式，每次保留前半秒和后一秒。数据传到电脑后，可以听录音、看三轴数据和波形。三种自动模式均取得过真实记录，传输和边界测试已完成。\n\n'
    conclusion+='实验结果没有达到“联合判断一定更好”的预期。留出组五次轻敲中，联合方法找到 '+str(mj['TP'])+' 次、漏掉 '+str(mj['FN'])+' 次，十次非敲击中误报 '+str(mj['FP'])+' 次，F1 为 '+num(mj['F1'])+'；振动单路 F1 为 '+num(mv['F1'])+'，本次表现更好。因此，现有系统可以演示双通道采集和自动事件记录，但轻敲漏检仍是需要改进的问题。\n'
    conclusion+=section('还有哪些没有验证')
    conclusion+='每类留出试验只有五次，不能代表其他桌面、距离和敲击力度。麦克风料号及 D.2/D.3 装配子版本尚未确认；加速度没有绝对标定，声压和准确物理延迟没有测量。官方录放未做耳机试听，串行接口未做示波器电气检查。\n\n'
    conclusion+='后续可先分析漏检原因，再用新的开发数据调整阈值和配对间隔，最后另采一批独立数据检验。不能根据本次留出组反复修改参数后，还把它当作未参与调参的测试结果。\n'
    conclusion+=section('文件交付和重新运行')
    conclusion+='交付目录提供最终 PDF，'+code('报告源码/')+' 可重新编译，'+code('复现实验/')+' 包含工程、原始数据、图表脚本、失败日志和校验清单。报告使用指定 WHUExperiment 模板\\cite{template}。重建需 Vivado 2026.1、TeX Live 2026 和中文字体，Python 依赖随包提供。实板测试需要连接板子，只编译报告不需要重新采样。主要命令如下。\n'
    conclusion+=r'\begin{lstlisting}'+'\n'+'.\\run.ps1 build\n.\\run.ps1 selftest\n.\\run.ps1 evaluate\n.\\run.ps1 report\nlatexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Experiment-template.tex\n'+r'\end{lstlisting}'+'\n'
    (dest/'conclusions.tex').write_text(conclusion,encoding='utf8')

    evidence='正文先说明功能和结果。本附录集中列出文件位置、版本校验值和板端时刻，便于需要时逐项核对。路径均相对工程或复现实验包根目录。\n'
    evidence+=section('从哪里查原始记录')
    evidence+=table('主要文件入口',['内容','相对路径'],[
        ['板型与修订',code('config/board_profile.json')],['引脚核对',code('runs/20261113T200752_110014_pin_compatibility/compatibility.json')],
        ['官方录放观察',code('runs/20261113T201114_597439_baseline/functional_observation.json')],
        ['正式采样',code('runs/'+collection.name+'/session.json')],['定下的参数',code('runs/'+collection.name+'/frozen_config.json')],
        ['逐窗重算比较',code('runs/'+evaluation.name+'/comparisons.json')],['全部评分结果',code('runs/'+evaluation.name+'/results.json')],
        ['布局布线时序',code('runs/'+program['build_run_id']+'/implementation/timing_summary.rpt')],
        ['图表来源',code('report/generated/figure_index.json')],['完整操作日志',code('runs/actions.jsonl')]],'p{2.5cm}p{9.8cm}')
    evidence+=section('版本、配置和校验值')
    evidence+='官方发布版本为 '+code('100T/OOB/2025.1-1')+'。包内位流保留上游名称 '+r'\nolinkurl{Nexys4DdrUserDemo.bit}'+'。\n'
    for label,value in [('官方 ZIP','77672b7708bd676d5dd0c979bafebd70fa1d1b4a09aff34dbe20f464247bca13'),
                        ('官方位流','5a92da8b2852ecac5fe0bc7340f1e9f9c9d94b0f27c3b8187749ef915ba50c69'),
                        ('实际测量位流',program['bitstream_sha256']),('正式参数文件',session['frozen_config_sha256'])]:
        evidence+='\n'+label+' SHA-256：'+code(value)+'。\n'
    evidence+='\nUSB 序列号 '+code('210292B7F4F8')+'，JTAG IDCODE '+code('0x13631093')+'，串口 COM5。FPGA 主时钟约束为 10 ns；五路慢速串行输出有 20 ns 寄存器到引脚传播约束。只对进入明确同步链的异步输入路径作相应处理，LED 无外部采样时钟。同步器、跨时钟检查（CDC）和 '+code('check_timing')+' 结果均随原始实现报告保留；工具对无外部时钟定义端口的检查覆盖有限。\n'
    evidence+='特征结果的标记时刻是窗口末端加 10004 个 10 ns 计数。板端重算计分时扣除了这段计算延迟，每条输入从相同初值开始，前 0.5 秒作预卷，之后 100 个完整窗口计分。数字 CIC 模型的理论中心延迟为 93 微秒，本实现另有两个输入周期即 1 微秒，以及抽取使能到 PCM 有效的五个主时钟周期即 50 ns；不含传感器滤波和输入同步等延迟，未用于声源物理延迟补偿。\n'
    evidence+=section('图表对应哪份输入')
    for e in figure_index:
        evidence+='\n事件 '+str(e['event_id'])+'，试次 '+code(e['trial_id'])+'：'+code(e['input_directory'])+'。输入 SHA-256：'+code(e['input_hash'])+'。\n'
    evidence+=section('自动事件的板端计数')
    online=[]
    for test in modes:
        for e in test['events']:online.append([('声音单路' if test['mode']==1 else '振动单路'),e['event_id'],e['t_audio'] or '无',e['t_accel'] or '无',e['t_confirm']])
    for e in live['events']:online.append(['声振联合',e['event_id'],e['t_audio'],e['t_accel'],e['t_confirm']])
    evidence+=table('单位为10 ns，数值来自对应自动事件记录',['模式','事件','声音候选时刻','振动候选时刻','确认时刻'],online)
    evidence+='传感器身份回读为 '+code(before['sensor_identity'])+'，配置回读为 '+code(before['sensor_config'])+'。\n'
    evidence+=table('正式采集前后的异常计数',['项目','采集前','采集后','新增'],
        [[name,before[key],after[key],after[key]-before[key]] for key,name in (
            ('overruns','前端漏读'),('xyz_rails','振动量程边界'),('audio_clips','音频饱和'),
            ('uart_framing','串口帧错误'),('packet_crc_errors','数据包校验错误'),('length_errors','长度错误'))])
    evidence+=section('每次留出试验的触发次数')
    evidence+='tap 为轻敲，sound 为纯声，quiet 为安静。次数大于零才算本试次报出；轻敲报出是找到，另外两类报出是误报。\n'
    evidence+=table('完整15次留出试验',['试次编号','标签','声音','振动','联合'],[
        [code(t['trial_id']),{'tap':'轻敲','sound':'纯声','quiet':'安静'}[t['label']],*[next(x['count'] for x in results['holdout'][mode]['trials'] if x['trial_id']==t['trial_id']) for mode in ('audio','accel','joint')]]
        for t in session['trials'] if t['session']=='holdout'])
    if pressure:evidence+='\n限速和重读测试运行：'+code('runs/'+pressure['run_id']+'/')+'。\n'
    evidence+='随机顺序种子：开发组 20261113，留出组 20261114。全部原始事件、WAV、XYZ、双向串口包和失败日志均在复现实验包中，逐文件校验清单为 '+code('SHA256.json')+'。\n'
    (dest/'evidence.tex').write_text(evidence,encoding='utf8')
    write_json(dest/'claim_index.json',{'collection_run_id':collection.name,'evaluation_run_id':evaluation.name,
        'result_sha256':sha256(evaluation/'results.json'),'frozen_config_sha256':session['frozen_config_sha256'],
        'bitstream_sha256':program['bitstream_sha256'],'figures':figure_index,'generator_sha256':sha256(Path(__file__))})
    if pressure:write_json(dest/'pressure_evidence.json',pressure)
    if (ROOT/'state/latency_model.json').exists():write_json(dest/'timestamp_delay_metadata.json',read(ROOT/'state/latency_model.json'))
    return report
