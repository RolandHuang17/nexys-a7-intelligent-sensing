"""Traceable music chapter: vector designs and figures from actual archived inputs."""
import json,re,wave,math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import freqz,spectrogram
from audit import ROOT,Run,write_json,sha256
from report_content import table,code,num,section
from plot_style import apply,finish

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def archived_path(value):
    parts=str(value).replace('\\','/').split('/')
    for anchor in ('runs','music_demo'):
        if anchor in parts:
            candidate=ROOT/Path(*parts[parts.index(anchor):])
            if candidate.is_file():return candidate
    path=Path(value)
    if path.is_file():return path
    raise FileNotFoundError('归档输入不存在：'+str(value))
def esc(value):
    return str(value).replace('&',r'\&').replace('%',r'\%').replace('_',r'\_').replace('#',r'\#')

DIAGRAMS={
'music-journey':(r'''\begin{tikzpicture}[vbase]
\foreach \x/\n/\t/\s in {0/one/手机或音箱/外放歌曲,3.7/two/轻敲桌面两下/ADXL362检测,7.4/three/开发板听歌/LED显示进度,11.1/four/电脑给出结果/歌名与歌手} {
 \node[vdark,text width=27mm,minimum height=20mm] (\n) at (\x,0){\t\\[2mm]{\vsmall\s}};}
\draw[vflow] (one)--(two);\draw[vflow] (two)--(three);\draw[vflow] (three)--(four);
\node[vteal,text width=37mm] (fav) at (11.1,-2){按中键收藏\\重复按仍只有一份};
\draw[vflow] (four)--(fav);
\node[vnote,text width=88mm] at (4.1,-1.9){使用现有麦克风、加速度计、按键、LED和USB。\\只增加板内逻辑和电脑程序，不接新硬件。};
\node[vnote,anchor=west] at (-1.4,-3.2){设计示意：录音、传输、匹配在界面中分开显示。};
\end{tikzpicture}''','桌面听歌识曲的操作过程'),
'music-architecture':(r'''\begin{tikzpicture}[vbase]
\node[vbox,text width=24mm] (mic) at (0,2){板载麦克风\\PDM 2MHz};
\node[vbox,text width=30mm] (cic) at (3.7,2){三级CIC\\16kHz PCM16};
\node[vteal,text width=31mm] (fir) at (7.9,2){原速旁路 / 低通降采样\\16kHz / 8kHz};
\node[vdark,text width=31mm] (ram) at (12.1,2){独立录音BRAM\\最多160000点};
\draw[vline] (mic)--(cic);\draw[vline] (cic)--(fir);\draw[vflow] (fir)--(ram);
\node[vbox,text width=24mm] (acc) at (0,-.2){ADXL362\\SPI，200Hz};
\node[vgold,text width=30mm] (tap) at (3.7,-.2){双击检测\\滞回、间隔、忙锁};
\draw[vline] (acc)--(tap);\draw[vcontrol] (tap) -| node[vlabel,pos=.74]{开始录音}(ram.south);
\node[vbox,text width=27mm] (key) at (7.9,-.2){BTNC中键\\同步与去抖};
\node[vbox,text width=30mm] (led) at (12.1,-.2){16个LED\\按已采点数显示};\draw[vcontrol] (ram)--(led);
\node[vteal,text width=29mm] (serial) at (12.1,-2.4){唯一串口线程\\460800，8N1};
\draw[vflow] (ram.east) -- ++(.6,0) |- (serial.east);
\node[vbox,text width=29mm] (worker) at (7.9,-2.4){识曲工作进程\\audfprint / AudioTag};
\node[vbox,text width=30mm] (ui) at (3.7,-2.4){Tk中文界面\\录音、结果、历史};
\node[vbox,text width=24mm] (db) at (0,-2.4){本机SQLite\\历史与收藏};
\draw[vflow] (serial)--(worker);\draw[vline] (worker)--(ui);\draw[vline] (ui)--(db);
\draw[vcontrol] (key.south)--(worker.north);
\node[vnote,text width=135mm,anchor=west] at (-1.4,-3.8){FPGA负责确定时序的采集与缓冲；电脑负责建库、匹配、显示和保存。原传感器监测与1.5秒声振事件沿用原接口。};
\end{tikzpicture}''','板端与电脑的功能模块及接口'),
'music-buffer':(r'''\begin{tikzpicture}[vbase]
\node[vstate] (a) at (0,0){EMPTY（0）\\可配置、可启动};
\node[vstate,vteal] (b) at (4.1,0){RECORD（1）\\逐点写入、累积CRC};
\node[vstate,vgold] (c) at (8.2,0){DRAIN（2）\\等待末尾CRC完成};
\node[vstate,vdark] (d) at (12.3,0){FROZEN（3）\\内容不再改写};
\draw[vline] (a)--node[vlabel]{START / 双击}(b);\draw[vflow] (b)--node[vlabel]{点数已满}(c);\draw[vline] (c)--node[vlabel]{CRC完成}(d);
\draw[vline] (d.south)--++(0,-1.3)-|node[vlabel,pos=.5]{完整读回并核对后才ACK}(a.south);
\node[vteal,text width=53mm] (active) at (3,-2.5){任务忙标志 job\_active=1\\录音、传输、匹配时都保持};
\node[vbox,text width=45mm] (end) at (10,-2.5){匹配结束 / 游戏揭晓后FINISH\\清除忙锁和START去重缓存};
\draw[vcontrol] (active)--(end);
\node[vnote,text width=140mm] at (6.1,-3.9){ACK只释放录音存储，FINISH才允许下一次唤醒。两者分开，避免正在匹配时再次敲击启动；新串口会话也能安全复用序号。};
\end{tikzpicture}''','录音缓冲区状态与任务忙锁'),
'music-free-gate':(r'''\begin{tikzpicture}[vbase]
\node[vdark,text width=44mm] (wav) at (5,0){本次完整WAV\\任务开始时固定模式};
\node[vgold,text width=40mm] (stat) at (1.7,-1.9){自动：API优先\\先查Key、账户与真实免费秒数};
\node[vbox,text width=40mm] (off) at (9,-1.9){仅离线\\不查询额度、不上传};
\draw[vflow] (wav)--node[vlabel]{自动}(stat);\draw[vline] (wav)--node[vlabel]{仅离线}(off);
\node[vteal,text width=40mm] (api) at (1.7,-4){确认免费且足够才上传一次\\保存任务编号，查询在线结果};
\node[vbox,text width=40mm] (local) at (9,-4){本地完整WAV匹配\\核对对齐哈希、跨度与差距};
\draw[vflow] (stat)--node[vlabel]{通过}(api);\draw[vline] (off)--(local);
\draw[vcontrol] (stat.east)--++(1.1,0)|-node[vlabel,pos=.65]{缺Key / 额度不明等}(local.west);
\draw[vcontrol] (api)--node[vlabel]{在线未中或不可用}(local);
\node[vdark,text width=40mm] (onlinehit) at (1.7,-6.2){在线成功：显示AudioTag\\直接结束，不运行本地匹配};
\node[vteal,text width=40mm] (localhit) at (9,-6.2){本地命中：显示本地歌单\\否则说明原因，保留原始录音};
\draw[vflow] (api)--node[vlabel]{成功}(onlinehit);\draw[vline] (local)--(localhit);
\node[vnote,text width=132mm] at (5.3,-7.8){上传后再核对费用；无法核对则暂停后续上传。同一任务超时不自动重传。\\模式是本次选择，来源是实际结果：自动模式也可能得到本地备用结果。};
\end{tikzpicture}''','API优先的识别顺序与免费保护'),
'music-rate':(r'''\begin{tikzpicture}[vbase]
\node[vdark,text width=28mm] (front) at (0,0){原16kHz声音前端\\全部原功能共用};
\node[vbox,text width=37mm] (full) at (5,.95){8秒 / 10秒原速录音\\128000 / 160000点};
\node[vteal,text width=37mm] (half) at (5,-1.1){31抽头低通，再隔点保留\\20秒，8kHz，160000点};
\node[vdark,text width=32mm] (ram) at (10.5,0){同一个独立缓冲区\\最多320000字节PCM};
\draw[vline] (front.east)--++(.7,0)|-(full.west);\draw[vflow] (front.east)--++(.7,0)|-(half.west);
\draw[vline] (full.east)--++(.6,0)|-(ram.west);\draw[vflow] (half.east)--++(.6,0)|-(ram.west);
\node[vgold,text width=120mm] at (5.2,-3){降采样前先低通，防止高频折叠。20秒选项是真实连续采集，未把片段重复或补静音来凑长度。};
\end{tikzpicture}''','在既有存储容量内增加真实20秒录音'),
'music-history-game':(r'''\begin{tikzpicture}[vbase]
\node[vdark,text width=32mm] (begin) at (0,0){同一次开局\\保存板端与主机计时对应};
\node[vteal,text width=35mm] (human) at (4.7,1){人拍桌锁时\\保存传感器真实时刻};
\node[vbox,text width=35mm] (machine) at (4.7,-1){机器继续录音与匹配\\取得结果时才停止计时};
\node[vgold,text width=35mm] (reveal) at (10,0){填写人的答案，再揭晓\\揭晓前界面不显示机器歌名};
\draw[vflow] (begin)--(human);\draw[vline] (begin)--(machine);\draw[vflow] (human)--(reveal);\draw[vline] (machine)--(reveal);
\node[vbox,text width=121mm] at (5,-3){历史按任务保存：同曲两次识别有两条真实时间记录。\\收藏按歌曲保存：标题、歌手归一化后使用唯一键，重复收藏只保留一份。};
\end{tikzpicture}''','抢歌名计时与本机数据保存方式')}

def generate(run=None):
    run=run or Run('music_report_content');dest=ROOT/'report/generated';figs=ROOT/'report/figures';vectors=ROOT/'report/visuals';index=[]
    for name,(body,caption) in DIAGRAMS.items():
        path=vectors/(name+'.tex');path.write_text(body+'\n',encoding='utf8')
        index.append({'kind':'design_vector_not_measurement','file':str(path.relative_to(ROOT)),'caption':caption,'sha256':sha256(path)})
    apply(plt)
    def save(fig,name,inputs,caption):
        finish(fig);fig.tight_layout();path=figs/(name+'.pdf');fig.savefig(path,bbox_inches='tight');plt.close(fig)
        index.append({'kind':'measured_or_calculated_as_caption','file':str(path.relative_to(ROOT)),'caption':caption,'sha256':sha256(path),
            'inputs':[{'path':str(Path(p).relative_to(ROOT)),'sha256':sha256(p)} for p in inputs]})
    def image(name,caption):return '\\begin{figure}[H]\\centering\\includegraphics[width=\\linewidth]{figures/'+name+'}\\caption{'+caption+'}\\end{figure}\n'
    def diagram(name):return '\\vdiagram{'+name+'}{'+DIAGRAMS[name][1]+'}{设计图，连接关系对应本项目RTL和上位机源码。}\n'
    build=read(ROOT/'state/build/status.json');inputs=read(ROOT/'runs'/build['run_id']/'build_inputs.json');impl=ROOT/'runs'/build['run_id']/'implementation'
    timing=(impl/'timing_summary.rpt').read_text(errors='replace');m=re.search(r'\n\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\d+\s+\d+',timing);wns,tns,whs,ths=map(float,m.groups())
    resources={}
    for label in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs'):
        resources[label]=float(re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)\s*\|',(impl/'utilization_routed.rpt').read_text())[1])
    text=section('先说明这次增加了什么')
    text+='以前的系统保存1.5秒声振事件，也能看实时传感器曲线。这次再加一台桌面听歌识曲器：手机外放，轻敲桌面两下，板载麦克风录音，电脑给出歌名和歌手，按中键收藏。没有增加传感器或接线。\n'
    text+=diagram('music-journey')
    text+='本章新增实测使用构建 '+code(inputs['build_id'])+'，位流SHA-256为 '+code(build['bitstream_sha256'])+'。前文的声振对照实验和监测扩展各有自己的版本，不把它们混写成新识曲版本的结果。\n'
    software=read(ROOT/'state/portable_build.json')
    text+='当前软件为'+software['app_version']+'，EXE的SHA-256为 '+code(software['exe_sha256'])+'。用户后续要求将开发重点全部放在线上API，已有离线功能按现状收尾，不再进行离线调参、正式留出、打字或抢答补测。\n'
    text+=section('硬件连接、采样和存储为什么够用')+diagram('music-architecture')
    text+='声音仍先由原PDM与CIC前端产生16kHz、16位单声道数据。8秒和10秒原速录音分别保存128000点和160000点。实际接口把多段10秒录音判为“audio is too short”，因此补了20秒选项：先低通，再降为8kHz，仍只需160000点。原实时预览和1.5秒声振事件保持16kHz。\n'+diagram('music-rate')
    filt=ROOT/'config/music_decimator.json';c=read(filt);hz,response=freqz(np.array(c['coefficients_q15'])/32768,worN=4096,fs=16000)
    fig,ax=plt.subplots(figsize=(8.5,3));ax.plot(hz/1000,20*np.log10(np.maximum(np.abs(response),1e-5)),lw=1.7);ax.axvline(4,color='#B47720',ls='--',label='8kHz保存时的奈奎斯特频率');ax.set(xlabel='输入频率 / kHz',ylabel='幅度响应 / dB',ylim=(-100,5));ax.grid(alpha=.35);ax.legend(loc='lower left',fontsize=8)
    save(fig,'music_filter_response',[filt],'31抽头定点系数的计算频响，并非外部仪器实测')
    text+=image('music_filter_response.pdf','31抽头定点系数的计算频响；1kHz约为'+num(c['gain_1k_dB'])+'dB，6kHz约为'+num(c['gain_6k_dB'])+'dB')
    text+='滤波器用一个乘法器轮流算31项，并在每个8kHz输出前累加完毕。1024个数字输出与Python定点参考逐点一致；这些是数字验证，不计作歌曲实板识别成绩。\n'
    text+=table('识曲版本布线后的实际资源与时序',['项目','已用 / 总量','占用或余量'],[
        ['LUT',f'{int(resources["Slice LUTs"])} / 63400',num(resources['Slice LUTs']/63400*100,1)+r'\%'],
        ['FF',f'{int(resources["Slice Registers"])} / 126800',num(resources['Slice Registers']/126800*100,1)+r'\%'],
        ['BRAM',f'{resources["Block RAM Tile"]} / 135',num(resources['Block RAM Tile']/135*100,1)+r'\%'],
        ['DSP',f'{int(resources["DSPs"])} / 240',num(resources['DSPs']/240*100,1)+r'\%'],
        ['100MHz建立时间',num(wns)+'ns',num(wns/10*100,2)+r'\%周期余量'],['保持时间',num(whs)+'ns','TNS / THS均为0']])
    text+='最大的开销是录音存储。实际使用完整160000点版本时，选择8秒不会让已经分配的BRAM变少；另编译128000点容量版本，只用于比较存储规模。时序数字来自对应布线报告，未用外部温箱或电压仪器重复测量。\n'
    capacity8=ROOT/'state/MUSIC1_resource8/status.json'
    if capacity8.exists():
        st8=read(capacity8);dir8=ROOT/'runs'/st8['run_id']/'implementation';rpt8=(dir8/'utilization_routed.rpt').read_text()
        bram8=float(re.search(r'\|\s*Block RAM Tile\s*\|\s*([\d.]+)\s*\|',rpt8)[1])
        text+=table('独立录音容量的另行编译对比',['容量版本','PCM字节数','布线后BRAM'],[
            ['128000点（8秒16kHz）','256000',str(bram8)+' / 135'],
            ['160000点（10秒16kHz或20秒8kHz）','320000',str(resources['Block RAM Tile'])+' / 135']])
        text+='两者由同一RTL改变容量参数编译，8秒容量版没有下载参与歌曲实测。最终采用160000点，剩余BRAM为'+num(135-resources['Block RAM Tile'],1)+'块，继续加长录音应改用外部DDR而不能只增大数组。\n'
    text+=section('板端状态和电脑程序怎样配合')+diagram('music-buffer')
    text+='串口始终只有一个线程操作，避免监测和识曲同时抢端口。界面负责提示和绘图；独立工作进程做指纹与网络请求。录音采满后冻结，按录音编号、偏移和点数分块读取，核对整段CRC、采样时刻和SHA-256，再释放存储。读取失败留下原始串口包，重试另建读回目录。\n'
    text+='前期测试发现，新串口会话复用START序号时会被旧缓存误认为重发。先用数字测试重现失败，再在FINISH后清除缓存；同一活动任务的重发仍保持幂等。另发现中键重复按下可能带来桌面振动，验收收藏时关闭唤醒，普通收藏后也有短暂屏蔽。\n'
    text+=section('本地匹配、免费在线与数据保护')+diagram('music-free-gate')
    text+='按用户最后确定的用途，正常使用以在线识曲为主。自动模式先检查免费账户和剩余秒数，再请求AudioTag；即使本地已有这首歌，也保持这个顺序。在线成功直接显示结果，只有未命中或接口不可用时才尝试本地歌单。仅离线模式不发起任何AudioTag请求。本地功能用于备用和介绍指纹方法，不再继续原先的离线留出采样轮。\n'
    text+='本地歌单用固定版本audfprint建库。不是看到第一名就报答案，还要满足对齐哈希数、匹配时间跨度和相对第二名的差距。保留原始WAV，另对整段去直流和等比例调整电平后再匹配；在线发送前转成服务建议的8kHz格式，没有把短片段重复或补静音来凑时长。\n'
    text+='演示歌单为Carefree、Sneaky Snitch、Cipher（Kevin MacLeod），以及用户指定的Take It Easy、Tequila Sunrise（Eagles）。Eagles来自官方原版音源，只交付指纹与元数据，不把完整原曲放进EXE。其他已有音乐可继续导入，重复内容不建重复项。\n'
    text+='密钥由本人在遮挡输入窗口填写，保存到Windows凭据管理器。源码、日志、截图与交付包均不包含密钥。免费秒数每次用真实stat结果判断，不写死每天或每月次数；余额、费用或网络状态不明时停止上传。\n'
    text+=section('实板记录、同输入比较与当前验收')
    bench=read(ROOT/'state/MUSIC3_recording/status.json');benchfile=ROOT/'runs'/bench['run_id']/'result.json';b=read(benchfile);valid=b['trials']
    text+='前期开发组已完成'+str(len(valid))+'段10秒实板录音，每段160000点，整段校验及重复读回一致。它们的音源为笔记本外放，不替代手机正式验收。播放静音、USB瞬时访问失败和低信噪比未匹配都保留在各自运行目录中。\n'
    text+=table('同一段实板录音的8秒前缀和10秒原件',['项目','8秒','10秒'],[['样本数','128000','160000'],
        ['平均实测导出时间 / s',num(np.mean([t['transfer8_s'] for t in valid])),num(np.mean([t['metadata']['export_s'] for t in valid]))],
        ['比较输入','同一10秒原件的前8秒','同一原件全部内容']])
    profile=ROOT/'runs/20261114T214931_411516_music_profile_selection/result.json'
    density=profile.with_name('density_evidence.json');development=ROOT/'runs/20261114T213849_647777_music_physical_acceptance/checkpoint.json'
    if profile.exists() and density.exists():
        prof=read(profile);dev=read(development);evidence=read(density);rows=[x for x in dev['dev_results'] if x['track'].get('expected')]
        trial_ids=[x['trial'] for x in rows];labels=[x['track']['title'] for x in rows]
        values=[]
        for seconds in (8,10):
            selected={x['trial']:x['evidence'] for x in evidence if x['query_density']==40 and x['seconds']==seconds}
            values.append([max([c.get('matched_hashes',c.get('hashes',0)) for c in selected[t].get('candidates',[])]+[0]) for t in trial_ids])
        # Candidate field names are those retained by LocalMatcher/audfprint.
        if not any(values[0]+values[1]):
            for seconds,vs in zip((8,10),values):
                selected={x['trial']:x['evidence'] for x in evidence if x['query_density']==40 and x['seconds']==seconds}
                vs[:]=[max([c.get('aligned_hashes',0) for c in selected[t].get('candidates',[])]+[0]) for t in trial_ids]
        fig,ax=plt.subplots(figsize=(8.5,3.4));xx=np.arange(len(labels));ax.bar(xx-.18,values[0],.34,label='同一录音前8秒',color='#7BACC9');ax.bar(xx+.18,values[1],.34,label='完整10秒',color='#168C82')
        ax.set_xticks(xx,labels);ax.set(ylabel='第一候选的对齐哈希数',title='离线开发组：同一输入长度对比');ax.tick_params(axis='x',labelsize=8);ax.legend(fontsize=8);ax.grid(axis='y',alpha=.3)
        save(fig,'music_development_hashes',[profile,density,development],'已保存手机开发录音的离线指纹对齐量；不是独立留出准确率')
        text+=image('music_development_hashes.pdf','手机开发组的离线指纹对齐量：用这些录音选参数，因此不作为独立准确率')
        p=prof['profile'];text+='本地最终门槛为：对齐哈希至少'+str(p['min_hashes'])+'，覆盖至少'+num(p['min_span_s'],1)+'秒，相对第二名比例至少'+num(p['min_ratio'],1)+'。开发组五首入库曲目均能匹配，三条库外和两条环境输入未报歌名；这些是同组调参结果，未据此声称未知片段也有同样准确率。8秒与10秒同组结果相同，原速离线默认保留10秒；在线因真实服务拒绝短录音，另用20秒。\n'
    tap=ROOT/'runs/20261114T213849_647777_music_physical_acceptance/tap_selection.json'
    if tap.exists():
        tp=read(tap)['chosen'];cal=read(development)['calibration_windows'];window=next(x for x in cal if x['kind']=='double');arr=window['rows']
        from music_wizard import tap_counts
        ticks=np.array([r['tick'] for r in arr]);xyz=np.array([[r[k] for k in ('x','y','z')] for r in arr]);delta=np.sum(np.abs(np.diff(xyz,axis=0)),axis=1)
        fig,ax=plt.subplots(figsize=(8.5,2.7));relative=(ticks-ticks[0])/1e8;ax.plot(relative[1:],delta,lw=1.2,color='#2868AA',label='相邻XYZ变化量');ax.axhline(tp['high'],ls='--',color='#B47720',label='上阈值 '+str(tp['high']));ax.axhline(tp['low'],ls=':',color='#168C82',label='重置阈值 '+str(tp['low']))
        taps,pairs=tap_counts(arr,tp['high'],tp['low'],tp['min_ms'],tp['max_ms'])
        for tick in pairs:ax.axvline((tick-ticks[0])/1e8,color='#B54747',alpha=.8,label='双击判定' if tick==pairs[0] else None)
        ax.set(xlabel='校准窗内时间 / s',ylabel='加速度原始计数变化',title='一次真实敲桌校准窗');ax.grid(alpha=.3);ax.legend(fontsize=8,loc='upper right')
        save(fig,'music_tap_calibration',[tap,development],'双击参数选择所用的真实XYZ开发窗；虚线为数字判定阈值')
        text+=image('music_tap_calibration.pdf','双击校准中的真实传感器变化；这张图展示选参依据，不代替十次正式唤醒检查')
        text+='双击使用相邻XYZ差的绝对值之和，阈值'+str(tp['high'])+'/'+str(tp['low'])+'，间隔'+str(tp['min_ms'])+'至'+str(tp['max_ms'])+'毫秒，单次脉冲不应期100毫秒。原600毫秒上限对操作者较慢的双击只找到1/5；保留原始11个校准窗后扩大候选上限，重算同一组得到5/5，未使用后续正式试次调参。\n'
    pilots=sorted((ROOT/'runs').glob('*music_exe_gui_pilot/result.json'))
    if pilots:
        pp=pilots[-1];pilot=read(pp);meta=pilot['metadata'];wav=archived_path(meta['wav'])
        with wave.open(str(wav),'rb') as w:a=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float);rate=w.getframerate()
        x=np.arange(len(a))/rate;fig,ax=plt.subplots(2,1,figsize=(8.5,4.6),sharex=True)
        ax[0].plot(x[::8],a[::8],lw=.55);ax[0].set(ylabel='原始PCM计数',title='真实板载麦克风录音：Take It Easy');ax[0].grid(alpha=.3)
        f,t,z=spectrogram(a-np.mean(a),rate,nperseg=512,noverlap=384);ax[1].pcolormesh(t,f/1000,10*np.log10(np.maximum(z,1e-8)),shading='auto',cmap='cividis',rasterized=True);ax[1].set(xlabel='录音内时间 / s',ylabel='频率 / kHz',ylim=(0,4))
        save(fig,'music_real_wave',[pp,wav],'实际EXE按钮采集的板载麦克风波形与频谱')
        text+=image('music_real_wave.pdf','实际EXE按钮采集的20秒板载麦克风波形与频谱；该次离线识出Take It Easy，未访问AudioTag')
        text+='这次实板按钮链路保存'+str(meta['samples'])+'点、'+str(meta['sample_rate'])+'Hz声音，导出耗时'+num(meta['export_s'])+'秒，匹配结果和原始文件分别见 '+code(str(pp.relative_to(ROOT)))+'。\n'
    formal=None
    from music_evidence import load_round,online_rows
    if (ROOT/'state/music_wizard.json').exists():
        ws=read(ROOT/'state/music_wizard.json');fp=ROOT/'runs'/ws['run_id']/'result.json'
        if fp.exists():formal=read(fp)
    formal=load_round() or formal
    if formal and formal.get('schema')=='online_priority_v1':
        text+=table('在线优先手机实板检查',['检查项','实际结果'],[
            ['在线识别正确',str(formal['online_correct'])+'/'+str(formal['online_total'])],
            ['其中未导入本地歌单的歌曲',str(formal['outside_online_correct'])+'/'+str(formal['outside_online_total'])],
            ['本轮双击唤醒',str(formal['double_wake_success'])+'/'+str(formal['double_wake_total']) if formal['double_wake_total'] else '使用按钮录音，本轮不再补测'],
            ['单敲 / 打字 / 只放歌误唤醒',' / '.join(str(formal['false_wakes'][k]) if formal['false_wake_exposure'][k]['trials'] else '未安排' for k in ('single','typing','music_only'))]])
        text+=('本轮已完成。' if formal.get('complete') else '本轮仍在继续，下表只列已经完成的试次；中断项和未做项不计成功，也不按零误唤醒处理。')
        text+='这些任务均来自手机外放和板载麦克风。在线正确要求最终来源确为AudioTag；本地回退命中不算在线成功。没有要求操作者断开电脑网络，实际断网项目按用户要求未做。\n'
        measured=online_rows(formal)
        source_labels={'audiotag':'在线','local':'本地回退','none':'未匹配'}
        text+=table('每首歌曲的真实结果与耗时',['输入歌曲','最终来源','在线正确','导出 / s','录音至结果 / s'],[
            [esc(r['expected_title']),'在线候选未定' if r['online_reason']=='ambiguous_online' else source_labels.get(r['source'],esc(r['source'])),'是' if r['online_correct'] else '否',
             num(r['export_s'],2),num(r['record_to_result_s'],2)] for r in measured])
        text+='“录音至结果”从实际板端录音开始计时，包含连续录音、串口导出、线上查询及必要的本地回退；等待操作者准备和手动补录前的等待不包含在内。\n'
        text+=table('每次在线请求的免费额度和费用核验',['试次','免费秒数：前 → 后','付费积分：前 / 后','费用核验'],[
            [r['trial'],str(r['free_seconds_before'])+' → '+str(r['free_seconds_after']),
             str(r['paid_balance_before'])+' / '+str(r['paid_balance_after']),
             '0元' if r['zero_cost_verified'] and r['cost_yuan']==0 else '未完成'] for r in measured])
        text+='本轮库外在线正确 '+str(formal['outside_online_correct'])+'/'+str(formal['outside_online_total'])+'。'
        if formal['outside_online_total']>=3 and formal['outside_online_correct']<2:
            text+='尚未达到原定至少识出两首库外歌曲的目标。已证明请求链路可工作，但当前声源、位置和录音条件下的识别效果有限；未通过反复挑选成功试次来替换这些未命中。'
        text+='各条原始结果与输入哈希见 '+code(formal['evidence']['path'])+'。\n'
        exposures=formal['false_wake_exposure']
        text+='干扰项目的采集量：单敲'+str(exposures['single']['trials'])+'次，打字'+str(exposures['typing']['seconds'])+'秒，只放歌'+str(exposures['music_only']['seconds'])+'秒。未完成时仅报告已观察到的次数，不宣称误唤醒验收通过。\n'
        fav=formal.get('favourite_check');game=formal.get('game')
        if fav:text+='板上中键已记录'+str(fav['presses'])+'次按下，同一歌曲收藏表为'+str(fav['favourite_rows'])+'行。重启持久化另以最后的回归记录核对。\n'
        if game:text+='实板抢答中，人拍桌时间为'+num(game.get('human_s'),2)+'秒，机器实际取得结果为'+num(game.get('machine_s'),2)+'秒，计时映射不确定度为'+num(game.get('clock_uncertainty_s'),3)+'秒。\n'
    elif formal:
        text+=table('手机正式验收实测',['检查项','实际结果'],[['库内歌名与歌手正确',str(formal['positive_correct'])+'/'+str(formal['positive_total'])],
            ['双击唤醒成功',str(formal['double_wake_success'])+'/'+str(formal['double_wake_total'])],['库外及噪声误报',str(formal['negative_false_matches'])+'/'+str(formal['negative_total'])],
            ['单敲 / 打字 / 只放歌误唤醒', ' / '.join(str(formal['false_wakes'][k]) for k in ('single','typing','music_only'))]])
        text+='本地门槛只使用开发数据确定，随后封存。每条结果保留完整WAV、CRC、输入哈希和任务编号；实际断网测试按用户要求未做。\n'
    else:text+='当前手机实板记录已保存开发采样。在线优先的新一轮结果另行记录，未把开发组或数字参考写成正式成功率；用户已取消实际断网测试，并将离线识曲改为辅助功能。\n'
    focus_file=ROOT/'state/music_api_focus.json'
    if focus_file.exists():
        previous=read(ROOT/'runs'/read(focus_file)['prior_round_run_id']/'checkpoint.json')
        old=[r for r in previous['results'] if r.get('kind')=='online']
        text+=table('改进前手机实录保留原始结果',['歌曲','最终来源','在线正确'],[
            [esc(r['title']),{'audiotag':'AudioTag','local':'本地回退','none':'未匹配'}.get(r['result']['source'],'未匹配'),'是' if r.get('online_correct') else '否'] for r in old])
        text+='上述五条在线正确1/5，其中三首库外正确1/3；这些未命中不因后续改进而删除或改记成功。后来完成的一条补充双击也保留，但用户取消剩余离线检查，不再把缺少的项目写成待操作者补做。\n'
    development_file=ROOT/'state/music_api_capture_development.json'
    if development_file.exists():
        dev_api=read(development_file)
        text+=table('新版上传处理的实板开发检查：笔记本外放',['输入','AudioTag正确','费用核验'],[
            [esc(r['expected']['title']),'是' if r['correct'] else '否','0元' if r['result'].get('zero_cost_verified') else '未完成'] for r in dev_api['trials']])
        text+='这三条为笔记本自动外放、板载麦克风重新录到的连续20秒声音，在线正确'+str(dev_api['correct'])+'/'+str(dev_api['total'])+'。它们单独作为开发检查，不并入手机正式轮，也没有证明音量处理后识别率已经提高。原始录音、上传输入和各次免费额度均保存。\n'
    text+=section('本次API链路修复及其限度')
    text+='原来的上传音量取整段最高峰，双击产生的短时大峰值可能压低其余歌声。新版只对上传副本去直流，再以整段均方根目标−18 dBFS和99.5百分位峰值共同确定增益；超限点作PCM16限幅，限幅点数、比例和输入输出哈希一同记录。完整时长不变，原始WAV不改，也不拼接或重复声音。音量正常不等于一定识别成功，仍以每条实际API结果为准。\n'
    text+='网络超时后保留已取得的任务编号，重启后“继续查询在线任务”只查询原编号，不再次上传。查询取得最终结果后更新同一次历史，不制造重复成功记录；上传状态不明时暂停新的自动提交。模拟服务已覆盖响应丢失、进程重启、费用后置核验和同一次录音仅上传一次。\n'
    text+='另一次数字参考诊断发现，服务会把同一首歌的普通版、单曲版和重制版作为同分条目返回。新版只合并明确的单曲版、专辑版和重制版后缀，保留全部原候选；不同歌名、现场版和混音版仍按歧义处理。该修复来自真实服务候选，但数字参考和缓存响应重放不计入实板识曲正确数。\n'
    if formal and formal.get('complete') and formal.get('offline_development_closed_by_user'):
        text+=r'本次三条手机轮使用软件1.1.4，确定命中0/3：Hotel California与We Will Rock You未命中；Billie Jean返回最高9\%的候选，还含同分的不完整曲目信息，因此没有自动确定歌名。随后1.1.5只增加候选与置信度的界面展示，不改录音、上传或判定，也不将本轮结果改成成功。'+'\n'
    regression_file=ROOT/'state/music_final_regression.json'
    if regression_file.exists():
        reg=read(regression_file)
        text+='当前识曲固件退出音乐模式后，已重新完成'+str(reg['full_event_samples'])+'点1.5秒事件、声音快照、回环和坏CRC拒绝检查；两条真实输入合计'+str(reg['board_reference_windows'])+'窗板端REPLAY与独立参考一致。WAV播放调用正常，不据此声称操作者完成主观试听。证据见 '+code('state/music_final_regression.json')+'。\n'
    priority_file=ROOT/'state/music_api_priority.json'
    if priority_file.exists():
        pr=read(priority_file);res=pr['result'];online_attempt=res.get('online_attempt',res)
        text+=table('API优先真实请求检查：复用一段20秒实板原件',['项目','结果'],[
            ['输入','已校验板载MIC录音，Take It Easy'],['顺序',r'stat → identify一次 → get\_result → stat'],
            ['在线结果',esc(online_attempt.get('reason',''))],['最终来源','AudioTag' if res.get('source')=='audiotag' else '本地歌单'],
            ['免费秒数',str(res.get('before',{}).get('identification_free_sec_remainder'))+' → '+str(res.get('after',{}).get('identification_free_sec_remainder'))],
            ['费用核对','0元；付费积分和付费使用量均为0' if res.get('zero_cost_verified') else '尚未核对']])
        text+='该次运行是 '+code(pr['run_id'])+'。录音只上传一次，线上未命中时本地回退仍能给出结果；这属于识别顺序和备用路径检查，不作为重新采集的歌曲试次。\n'
    online_file=ROOT/'state/music_online_acceptance.json'
    if online_file.exists():
        online=read(online_file);text+='真实在线验收的当前记录为 '+code(online['run_id'])+'。服务拒绝、正常未命中与正确识别分别保留，不将模拟故障计入命中数。\n'
    text+=section('收藏、玩法与使用边界')+diagram('music-history-game')
    (dest/'music_experiments.tex').write_text(text,encoding='utf8')
    if formal and formal.get('complete'):
        conclusion=dest/'monitor_conclusions.tex'
        value='本项目完成了基于Nexys A7的多传感器监测、声振事件保存和桌面听歌识曲扩展。16个开关、5个方向按键、温度电压读回及原1.5秒事件取得过实板记录，完整声音与XYZ可导出、播放和复查。\n'
        value+=section('目前的限制')
        value+='实时预览存在缺口，完整记录应使用事件保存；温度、电压、声压、加速度和倾角没有外部仪表标定。原联合触发对轻敲的漏检仍保留：留出组联合F1为0.571，振动单路为0.750，未因增加界面而宣称识别率提高。\n\n'
        value+='AudioTag免费额度守卫、单次上传、异步查询和断点续查已实现，原始录音和账户余额可追溯。最新手机实板轮确定命中'+str(formal['online_correct'])+'/'+str(formal['online_total'])+'，Billie Jean只有低置信度候选，未达到至少识出两首的目标；费用均核验0元。链路可工作不代表识曲效果达标。离线功能按用户决定保留现状，不再开发。\n'
        value+=section('交付和日常使用')
        value+='日常双击独立EXE，无需安装Python或Vivado；首次核对板型，必要时初始化到SRAM。普通连接保留未导出事件，重新下载会清空板内临时内容，电脑原始记录继续保留。源码调试和报告重编可使用下列命令。\n'
        value+='\\begin{lstlisting}\n.\\monitor.ps1\n.\\monitor.ps1 -Program\n.\\run.ps1 build\nlatexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Experiment-template.tex\n\\end{lstlisting}\n'
        value+='交付包括PDF、可重编LaTeX与TikZ、RTL、电脑程序、原始试次、失败日志、离线依赖和校验清单。换电脑、第二块板与原生FTDI仍待实测。功能、硬件接口、软件框架和核心难点分别在第一、三、四、五章说明，API结果及其限制见第九章。\n'
        conclusion.write_text(value,encoding='utf8')
    write_json(dest/'music_figure_index.json',{'generator':'host/music_report_content.py','generator_sha256':sha256(__file__),'figures':index})
    write_json(dest/'music_claim_index.json',{'build':build,'build_id':inputs['build_id'],'resources':resources,'WNS_ns':wns,'WHS_ns':whs,
        'benchmark_run_id':bench['run_id'],'formal_run_id':formal['run_id'] if formal else None,
        'formal_complete':formal.get('complete',False) if formal else False,'formal_evidence':formal.get('evidence') if formal else None,'budget_yuan':0,'figures':index})
    run.event('music_report_generated',figures=len(index),formal_collected=formal is not None);run.manifest();print(run.run_id)

if __name__=='__main__':generate()
