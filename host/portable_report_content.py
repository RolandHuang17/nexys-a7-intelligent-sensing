"""Plain Chinese software-delivery chapter from archived EXE and board evidence."""
import json,shutil
from pathlib import Path
from audit import ROOT,sha256,write_json
from report_content import table,section,code,num

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def generate_portable(run):
    a=read(ROOT/'state/portable_acceptance.json');build=a['build'];s=a['summary']
    current=read(ROOT/'state/portable_build.json')
    assert current['exe_sha256']==sha256(ROOT/'deliver/软件/开发板实时监测.exe')
    ui=a['ui_review'];screenshot=ROOT/ui['screenshot'];assert sha256(screenshot)==ui['screenshot_sha256']
    shutil.copy2(screenshot,ROOT/'report/figures/portable_dashboard.png')
    text=section('为什么还要做成独立软件')
    text+='前面的界面原先依赖这台电脑的 Python 环境和工程目录，并且按原实验板的 USB 序列号找设备。直接把脚本交给老师，换电脑或换一块板就可能打不开。因此将电脑端程序、运行依赖、配套位流和下载工具放进同一个 EXE。老师日常只需要这个文件，不需要安装 Python 或 Vivado。\n'
    text+='本版面向 Windows 10/11 的 64 位电脑和 Nexys A7-100T。软件按实际 USB 信息寻找串口，将同一序列号的下载接口与 UART 对应起来，不再固定 COM5 或原板序列号。多块板同时连接时，先在列表选择。USB 芯片和 FPGA 型号不能单独证明整块板型，所以初始化前仍需核对板面。\n'
    if current['exe_sha256']!=build['exe_sha256']:
        text+='本章截图、拔插和实板统计来自独立软件'+build['app_version']+'的历史验收，保留其原始版本和哈希。当前听歌识曲软件为'+current['app_version']+'，新增固件、单文件检查和最终回归另在听歌识曲章节说明，不把旧版测试改记到新版名下。\n'
    text+=section('老师第一次打开时怎么用')
    text+='双击 '+code('开发板实时监测.exe')+'，接好 PROG/UART 并上电。板上已有配套程序时直接连接；没有时勾选板型，点“初始化此板”。初始化先扫描 JTAG、检查 XC7A100T 和内置位流校验值，再临时加载到 SRAM，随后用串口检查程序编号并读取数据。初始化会清除板内尚未导出的临时记录，但不写 Flash，断电后需要重新加载。\n'
    text+='软件兼容两种下载路径：常规 FTDI 驱动走 D2XX，原有 WinUSB 环境走 OpenOCD。缺少驱动时提供 FTDI 原版签名安装器，仅该安装步骤申请管理员权限。已经可用时无需安装。驱动包保留原始许可证和哈希，正式发布时不要求复制整个开发工具。\n'
    text+=r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{portable_dashboard.png}\caption{真正由EXE运行的实板界面，已增加设备选择、初始化、驱动准备和诊断导出。}\end{figure}'+'\n'
    text+=section('软件怎样脱离原工程目录')
    text+='单文件启动后，内置资源由打包器解压到临时目录；传感器记录与设置放到当前用户的 LocalAppData 下的 '+code('NexysMonitor')+' 文件夹。这两个位置分别处理，避免软件退出时把实验记录一起删掉。配置使用发布清单中的构建号和哈希，不再依赖开发机上的构建状态文件。\n'
    text+='下载在独立子进程中执行。打包后的子进程仍调用同一个 EXE 的内部入口，不再寻找开发机的 '+code('python.exe')+' 或脚本路径。每次重新连接、切换设备或重新初始化都建立独立采集会话，记录实际序列号和位流版本；图表另开时间段，历史事件继续保留。\n'
    text+='小窗口的控件自动换行，图表保持可读高度并支持滚动。导出本次诊断包会先停止采集，再将原始串口、数据、版本清单和哈希装入 ZIP，便于在另一台电脑出问题时复查。默认触发阈值仍取原实验起点，没有将它当成所有板子都适用的校准结果。\n'
    text+=section('本机实际检查到了什么')
    text+=table('独立软件本机检查结果',['项目','实际结果'],[
        ['该轮验收软件',build['app_version']+'，单个EXE约 '+num(build['exe_bytes']/1048576,1)+' MiB'],
        ['隔离运行','只复制EXE，空数据目录、中文路径、移除开发工具PATH后启动通过'],
        ['原实验板下载','EXE自带OpenOCD走现有WinUSB，SRAM配置状态正常'],
        ['GUI内初始化','独立下载子进程完成后重新连接'],
        ['实际设备',s['device']['usb_serial']+' / '+s['device']['port']],
        ['新会话读取帧数',str(s['polls'])],
        ['新会话前端漏读',str(s['last']['overruns'])],
        ['新会话板端包校验错误',str(s['last']['packet_crc_errors'])],
        ['原始波形及诊断导出','实际EXE中打开波形；导出ZIP逐文件SHA核对通过'],
        ['逻辑边界检查','更换序列号、COM号、多板、错误芯片和资源损坏拒绝通过']], 'p{3.6cm}p{8.4cm}')
    event_rows=[['常规运行',e['event_id'],e['pcm_count'],e['xyz_count'],'CRC、SHA和WAV一致'] for e in a['events']]
    if a.get('hotplug',{}).get('recovered'):
        event_rows += [['重插恢复',e['event_id'],e['pcm_count'],e['xyz_count'],'CRC和SHA一致'] for e in a['hotplug']['post_events']]
    text+=table('该版EXE验收时保存的实板事件',['会话','事件','声音点数','XYZ组数','完整性'],event_rows)
    last=s['last'];text+='这段新记录末尾实际读回板载温度 '+num(last['adt_c'],2)+' °C、FPGA 芯片温度 '+num(last['die_c'],2)+' °C，核心、辅助和存储电压分别为 '+num(last['vccint_v'])+' V、'+num(last['vccaux_v'])+' V、'+num(last['vccbram_v'])+' V。这些仍是板端数字读数，没有外部仪表精度标定。\n'
    if a.get('hotplug',{}).get('recovered'):
        text+='另做了一次真实USB拔插：监视记录中先观察到设备消失，再观察到同一序列号重新枚举；界面将旧数值标为失效。断电使SRAM程序丢失，点初始化后重新下载并恢复读取，再导出一段完整事件。初始化前后使用不同运行号，旧会话摘要保留，暂停画面时后台时间继续增加也已实际检查。\n'
    text+=section('失败修复和还没有做的验收')
    text+='打包检查时发现，初始化前后的两个连接原先共用一个会话摘要，新连接可能覆盖旧摘要。改为每次重连另建运行目录，原始日志和失败记录保留。1280×720窗口测试还发现图表会被压扁裁切，随后改为保持图表高度、允许滚动，并实际检查到底部电压和按键面板。\n'
    text+='FTDI 官网返回403后，归档了下载失败，再取得设备厂商保存的未修改原版包，核对其公开SHA值及安装器有效厂商签名。这里没有在现有可用电脑上重新安装驱动。\n'
    text+='本机单文件隔离测试不能代替另一台电脑测试。操作者反馈“现在没电脑，搞不了”，因此真正换机验收和常规 FTDI 驱动下的实板下载暂未完成。第二块 Nexys A7-100T 也尚未取得，换序列号的逻辑检查不冒充换板实测。以后只需复制本版 EXE，初始化、检查输入响应、保存事件并带回诊断包，即可补上这两项证据。\n'
    text+='独立软件封装阶段没有修改该轮已验收的 FPGA 逻辑，声音与振动识别的原有限制继续保留，不能因为做成 EXE 就声称准确率提高。后续听歌识曲的固件增加另见下一章。\n'
    (ROOT/'report/generated/portable_experiments.tex').write_text(text,encoding='utf8')
    evidence=section('独立软件版本与实板记录')
    evidence+=table('软件发布与验收入口',['内容','相对工程路径'],[
        ['该轮版本与EXE哈希',code('state/portable_acceptance.json')],['隔离启动检查',code('runs/'+a['isolation_run_id']+'/result.json')],
        ['本机实板归档',code('runs/'+a['run_id']+'/result.json')],['最终EXE采集原件',code(a['archived_session'])],
        ['实际软件截图',code(ui['screenshot'])],['构建与依赖复现',code('scripts/build_portable.ps1')]], 'p{3cm}p{9cm}')
    evidence+='发布 EXE SHA-256：'+code(build['exe_sha256'])+'。发布资源清单 SHA-256：'+code(build['resource_manifest_sha256'])+'。\n'
    (ROOT/'report/generated/portable_evidence.tex').write_text(evidence,encoding='utf8')
    conclusion=ROOT/'report/generated/monitor_conclusions.tex'
    value=conclusion.read_text(encoding='utf8').replace('电脑已经配置好依赖时，在工程根目录执行下列命令即可打开界面。',
        '日常使用直接双击独立EXE，无需安装Python或Vivado。首次驱动准备、板型确认和临时初始化见上一章；真正换机和第二块板尚待实测。下列命令保留给源码调试和重建使用，执行它们需要相应开发环境。')
    conclusion.write_text(value,encoding='utf8')
    write_json(ROOT/'report/generated/portable_claim_index.json',{'acceptance_run_id':a['run_id'],'exe_sha256':build['exe_sha256'],
        'bitstream_sha256':build['firmware']['bitstream_sha256'],'screenshot':ui['screenshot'],'screenshot_sha256':ui['screenshot_sha256'],
        'inputs':[{'path':'state/portable_acceptance.json','sha256':sha256(ROOT/'state/portable_acceptance.json')}],
        'cross_pc_verified':False,'second_board_verified':False,'native_ftdi_physically_verified':False,
        'generator':'host/portable_report_content.py','generator_sha256':sha256(Path(__file__))})
    run.event('portable_report_generated',exe_sha256=build['exe_sha256'],acceptance_run_id=a['run_id'],cross_pc_verified=False)
