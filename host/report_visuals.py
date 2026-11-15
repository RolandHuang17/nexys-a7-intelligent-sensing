"""Build traceable TikZ illustrations; never invent or modify experimental inputs."""
import json,re
from pathlib import Path
from audit import ROOT,sha256,write_json

D={}
def diagram(name,height,body,caption,sources,note='设计示意；连线表示功能关系，不是实测波形。'):
    D[name]={'tex':r'\begin{tikzpicture}[vbase]'+'\n'+fr'\path[use as bounding box] (0,0) rectangle (14.4,{height});'+'\n'+body+'\n'+r'\end{tikzpicture}'+'\n',
             'caption':caption,'sources':sources,'note':note}

diagram('system-map',5.8,r'''
\node[vcaption] at (.1,5.45) {从桌面上的变化，到电脑里的记录};
\node[vbox,text width=25mm] (s) at (1.6,3.8) {声音、敲击\\倾斜、温度};
\node[vgold,text width=25mm] (g) at (1.6,1.9) {拨码开关\\方向按键};
\node[vdark,text width=32mm,minimum height=27mm] (f) at (6.1,2.9) {Nexys A7-100T\\\footnotesize 持续采集 · 时间标记\\触发判断 · 临时存储};
\node[vteal,text width=30mm,minimum height=27mm] (p) at (11.1,2.9) {电脑中文软件\\\footnotesize 实时曲线 · 状态显示\\事件查看 · 录音播放};
\draw[vline] (s.east)--(f.north west);\draw[vcontrol] (g.east)--(f.south west);
\draw[vflow,<->] (f)--node[vlabel,above]{USB串口}(p);
\node[vnote,text width=125mm] at (7.2,.65) {日常看变化：实时预览\qquad 需要完整数据：保存前0.5秒、后1秒\quad $\rightarrow$\quad WAV + XYZ + 元数据 + 校验};
''','系统用途总览：同一块板既能实时查看，也能保存声振事件。', ['report/monitor_function.tex','host/monitor_gui.py','rtl/event_recorder_top.sv'])

diagram('baseline',4.6,r'''
\node[vcaption] at (.1,4.2) {官方录放演示：先录，再放};
\foreach \x/\n/\t in {1.6/m/板载麦克风,5.0/d/DDR2存储,8.5/a/Audio Out,12.3/l/耳机或音箱}{\node[vbox,text width=22mm] (\n) at (\x,2.55) {\t};}
\draw[vline] (m)--node[vlabel,above]{录音}(d);\draw[vline] (d)--node[vlabel,above]{回放}(a);\draw[vline] (a)--(l);
\node[vgold,text width=37mm] (b) at (3.3,.9) {按一次 BTNU\\开始约五秒录音};
\node[vteal,text width=55mm] at (10,.9) {LED 逐渐亮起：录音进度\\LED 逐渐熄灭：回放进度};
\draw[vcontrol] (b.north)--(d.south);
''','官方 baseline 的录音、存储和回放过程。',['report/design.tex','docs/A0_baseline.md'],
'官方功能示意；本次确认了灯带状态变化，没有耳机试听结果。')

diagram('capability',6.3,r'''
\node[vcaption] at (.1,5.95) {在官方演示之后，本项目做了什么};
\path[vgroup] (.1,.5) rectangle (6.7,5.4);\path[vgroup] (7.1,.5) rectangle (14.3,5.4);
\node[vdark,text width=53mm] at (3.4,4.75) {官方录放演示};
\node[vteal,text width=59mm] at (10.7,4.75) {本项目新增系统};
\node[align=left,text width=52mm] at (3.4,2.7) {声音一路\quad 按 BTNU 录音\\[3mm] DDR2 保存约五秒\\[3mm] Audio Out 回放\\[3mm] LED 显示进度};
\node[align=left,text width=58mm] at (10.7,2.7) {声音 + XYZ 同时记录\\[3mm] 手动、单路、联合触发\\[3mm] 保留触发之前的数据\\[3mm] 温度、电压、开关、按键实时看};
\node[vnote,text width=126mm] at (7.2,.1) {新增程序重新实现采集与记录；没有保留官方演示的全部外设功能，也没有新增自己的耳机口回放。};
''','官方录放与新增功能的对照，帮助区分复现部分和自己实现的部分。',['report/design.tex','report/monitor_function.tex'])

diagram('board-links',7.9,r'''
\node[vcaption] at (.1,7.55) {板载器件\hspace{34mm}FPGA\hspace{35mm}电脑};
\node[vbox,text width=26mm] (m) at (1.7,6.1) {麦克风\\PDM 2 MHz};
\node[vbox,text width=26mm] (a) at (1.7,4.45) {ADXL362\\XYZ / 内部温度};
\node[vteal,text width=26mm] (t) at (1.7,2.8) {ADT7420\\板载温度};
\node[vgold,text width=26mm] (g) at (1.7,1.15) {16开关 / 5按键\\普通数字输入};
\node[vdark,text width=30mm,minimum height=61mm] (f) at (7.0,3.65) {XC7A100T\\[2mm]100 MHz 主时钟\\[2mm]采集与时间标记\\触发与双组存储\\[3mm]内部 XADC\\芯片温度 / 三路电压};
\node[vteal,text width=27mm] (u) at (12.5,4.45) {USB 串口芯片\\PROG/UART};
\node[vbox,text width=27mm] (p) at (12.5,2.5) {电脑实时软件\\与事件文件};
\draw[vline,<->] (m.east)--node[vlabel]{CLK / LR / DATA}([yshift=24mm]f.west);
\draw[vline,<->] (a.east)--node[vlabel]{SPI 2 MHz + INT1}([yshift=8mm]f.west);
\draw[vflow,<->] (t.east)--node[vlabel]{I²C 约100 kHz}([yshift=-8mm]f.west);
\draw[vcontrol] (g.east)--node[vlabel]{同步与去抖}([yshift=-24mm]f.west);
\draw[vline,<->] ([yshift=8mm]f.east)--node[vlabel]{UART 460800\\8N1}(u.west);
\draw[vflow,<->] (u)--node[vlabel,right]{USB}(p);
\node[vnote] at (10.65,.65) {XADC 在 FPGA 内部\\无需外部模拟接线};
''','扩展版板级接口总图。颜色区分声音与振动、慢速监测和普通数字输入。',['constraints/nexys_a7_100t.xdc','rtl/event_recorder_top.sv','report/monitor_hardware.tex'])

diagram('core-flow',6.0,r'''
\node[vcaption] at (.1,5.65) {数据一直采集，触发只决定“留下哪一段”};
\node[vbox,text width=25mm] (p) at (1.6,4.25) {PDM 转 PCM\\16 kHz / 16位};
\node[vbox,text width=25mm] (a) at (1.6,2.65) {SPI 读取 XYZ\\带实际采样时间};
\node[vteal,text width=26mm] (w) at (6.3,4.25) {10 ms 特征窗\\声音 / 振动变化量};
\node[vgold,text width=26mm] (t) at (11.7,4.25) {单路 / 联合判断\\给出保存时刻};
\node[vbox,text width=30mm] (b) at (6.3,1.65) {双组 BRAM\\环形历史 + 后段记录};
\node[vteal,text width=26mm] (u) at (11.7,1.65) {分块打包 + CRC\\电脑读取与确认};
\draw[vline] (p)--(w);\draw[vline] (a.east)-|(w.south);\draw[vflow] (w)--(t);
\draw[vline] (p.west)--(.1,4.25)--(.1,1.65)--(b.west);
\draw[vline] (a.south)|-([yshift=2mm]b.west);
\draw[vcontrol] (t.south)--(11.7,2.9)--node[vlabel,above]{保存请求}(6.3,2.9)--(b.north);
\draw[vline,<->] (b)--(u);
\node[vnote] at (7.2,.35) {共同时间基准：100 MHz 计数器\qquad 实时预览另走有限历史缓冲，完整事件独立校验};
''','FPGA 内部数据通路：采样、判断、存储和传输各有分工。',['rtl/event_recorder_top.sv','rtl/record_bank.sv','rtl/trigger_core.sv'])

diagram('host-architecture',7.4,r'''
\node[vcaption] at (.1,7.05) {电脑程序的分工：界面不等待串口，串口只有一个使用者};
\path[vgroup] (.1,1.3) rectangle (4.3,6.5);\path[vgroup] (4.65,1.3) rectangle (9.1,6.5);\path[vgroup] (9.45,1.3) rectangle (14.3,6.5);
\node[vdark,text width=31mm] at (2.2,5.85) {开发板};
\node[vbox,text width=29mm] (board) at (2.2,3.6) {采集 / 触发\\预览 / 冻结事件};
\node[vteal,text width=33mm] at (6.87,5.85) {串口工作线程};
\node[vteal,text width=31mm] (poll) at (6.87,4.25) {轮询、校验、去重\\穿插分块读取事件};
\node[vbox,text width=31mm] (q) at (6.87,2.25) {线程安全队列\\数据快照与消息};
\node[vgold,text width=37mm] at (11.87,5.85) {Tk 界面主线程};
\node[vgold,text width=35mm] (ui) at (11.87,3.6) {曲线 / 数值 / 按钮\\暂停画面、查看事件};
\draw[vline,<->] (board.east)--node[vlabel]{UART}(poll.west);
\draw[vflow] (poll)--(q);\draw[vflow] (q.east)-|(ui.south);
\node[vnote,text width=36mm] at (2.2,1.9) {持续采样与是否暂停画面无关};
\node[vnote,text width=36mm] at (11.87,1.9) {命令经队列交回串口线程};
\node[vbox,text width=40mm] (disk) at (4,.4) {原始包 / 日志 / WAV / XYZ};
\node[vred,text width=46mm] at (11,.4) {初始化：独立编程子进程\\完成后再交回串口};
\draw[vline] (poll.west)--(4.5,4.25)--(4.5,1)--(disk.north);
''','主机模块与线程关系。绘图、串口和编程各自负责一部分工作。',['host/monitor_service.py','host/monitor_gui.py','host/portable_program.py'])

diagram('capture-procedure',6.2,r'''
\node[vcaption] at (.1,5.85) {前期对照实验：先定参数，再用另一批数据检查};
\node[vbox,text width=32mm] (a) at (2,4.5) {01\quad 连接与自检\\核对版本和传感器};
\node[vbox,text width=32mm] (b) at (7.1,4.5) {02\quad 静置校准\\安静采集10秒};
\node[vteal,text width=32mm] (c) at (12.2,4.5) {03\quad 开发组15次\\轻敲 / 纯声 / 安静};
\node[vgold,text width=32mm] (d) at (12.2,2.55) {04\quad 冻结参数\\不看留出结果调参};
\node[vteal,text width=32mm] (e) at (7.1,2.55) {05\quad 留出组15次\\仍保留失败记录};
\node[vbox,text width=32mm] (f) at (2,2.55) {06\quad 在线与安静测试\\三种策略同输入比较};
\draw[vline] (a)--(b);\draw[vline] (b)--(c);\draw[vflow] (c)--(d);\draw[vflow] (d)--(e);\draw[vline] (e)--(f);
\node[vnote,text width=125mm] at (7.2,.7) {每次先 SNAP，板子确认参考时刻后再提示动作。无论是否自动触发，都保存原始输入。\\本图对应扩展前的实验；新增实时监测功能另做实板功能检查。};
''','对照实验的先后关系。开发组用来定参数，留出组用来检查。',['host/collect.py','host/evaluate.py','report/design.tex'])

diagram('double-bank',5.1,r'''
\node[vcaption] at (.1,4.75) {两组空间交替使用，但不是无限容量};
\draw[vline] (1.25,3.8)--(14,3.8) node[above left,font=\footnotesize]{时间向右};
\node at (.55,2.8) {组0};\node at (.55,1.45) {组1};
\foreach \x/\w/\t/\c in {1.4/3/保留历史/vBlue,4.4/3.2/记录后段/vTeal,7.6/3.5/冻结，等待ACK/vAmber,11.1/2.8/重新积累/vBlue}{\path[fill=\c!10,draw=\c!65,rounded corners=1mm] (\x,2.3) rectangle +(\w,1);\node[font=\footnotesize] at (\x+\w/2,2.8) {\t};}
\foreach \x/\w/\t/\c in {1.4/6.2/保留最近历史，等待下一次/vBlue,7.6/3.5/记录后段/vTeal,11.1/2.8/冻结，待导出/vAmber}{\path[fill=\c!10,draw=\c!65,rounded corners=1mm] (\x,.95) rectangle +(\w,1);\node[font=\footnotesize] at (\x+\w/2,1.45) {\t};}
\foreach \x/\t in {4.4/事件1,7.6/事件2}{\draw[dashed,vRed] (\x,.7)--(\x,3.5);\node[font=\footnotesize,text=vRed,above] at (\x,3.5) {\t};}
\node[vnote,text width=126mm] at (7.2,.25) {后段正在采集，或两组都未释放时，新请求可能被抑制；“条件满足”和“成功存下”分别计数。};
''','双组记录存储的工作示例，横向长度仅表示先后关系。',['rtl/record_bank.sv','rtl/event_recorder_top.sv'])

diagram('record-fsm',7.6,r'''
\node[vcaption] at (.1,7.2) {一组记录空间的一生};
\node[vstate] (i) at (1.8,5.5) {IDLE\\环形写入 / 等待};
\node[vstate,fill=vTeal!7,draw=vTeal] (p) at (7.1,5.5) {POST\\收齐后一秒};
\node[vstate] (s) at (12.5,5.5) {SCAN\_REQ\\发出XYZ读请求};
\node[vstate] (w) at (12.5,2.9) {SCAN\_WAIT\\检查有效时间};
\node[vstate] (c) at (7.1,2.9) {CRC\_REQ\\发出数据读请求};
\node[vstate] (v) at (1.8,2.9) {CRC\_WAIT\\更新整事件CRC};
\node[vstate,fill=vAmber!9,draw=vAmber] (f) at (1.8,.75) {FROZEN\\冻结，等待确认};
\draw[vline] (i)--node[vlabel,above]{历史就绪 + 保存请求}(p);
\draw[vline] (p)--node[vlabel,above]{后段与等待时间结束}(s);
\draw[vline] (s)--(w);\draw[vline] (w)--node[vlabel,above]{扫描完成}(c);\draw[vline] (c)--(v);
\draw[vline] (v)--node[vlabel,right]{全部校验完成}(f);
\draw[vflow] (f.west)--(.15,.75)--(.15,5.5)--node[vlabel,left,rotate=90]{ACK编号、长度、CRC均匹配}(i.west);
\draw[vline] (w.east)--(14.1,2.9)--(14.1,5.5)--node[vlabel,right,rotate=90]{还有XYZ}(s.east);
\draw[vline] (v.north)--(1.8,4.05)--node[vlabel,above]{还有数据}(7.1,4.05)--(c.north);
\draw[vcontrol] (p.south)--node[vlabel,right]{无XYZ}(c.north);
\node[vnote,text width=98mm] at (9,.65) {冻结期间只读；错误ACK不释放。\\状态名与 record\_bank.sv 对应；复位统一回到 IDLE。};
''','记录模块的七个实际状态。扫描、校验和确认完成后才能重新使用空间。',['rtl/record_bank.sv'], 'RTL 状态示意；省略停留本状态的条件，数据和确认规则未改动。')

diagram('frame-format',4.8,r'''
\node[vcaption] at (.1,4.45) {串口一帧：先找边界，再检查内容};
\foreach \x/\w/\a/\b/\c in {0/1.7/同步/2 B/vNavy,1.7/1.4/版本/1 B/vBlue,3.1/1.4/命令/1 B/vBlue,4.5/1.5/序号/2 B/vBlue,6/1.8/事件号/4 B/vBlue,7.8/1.6/长度/2 B/vBlue,9.4/3.1/数据/0--512 B/vTeal,12.5/1.9/CRC32/4 B/vAmber}{
\path[fill=\c!10,draw=white,line width=1pt] (\x,2.4) rectangle +(\w,1.25);\node[align=center] at (\x+\w/2,3.02) {\a\\\footnotesize\b};}
\node[vnote] at (.85,2.0) {A5 5A};
\draw[decorate,decoration={brace,amplitude=4pt,mirror},vTeal,line width=.8pt] (1.7,2.1)--(12.5,2.1);
\node[font=\footnotesize,text=vTeal] at (7.1,1.65) {CRC 覆盖10字节头部与数据，不包含同步字};
\node[vnote,text width=125mm] at (7.2,.65) {多字节整数按小端传输；总长度 = 16 + 数据长度。UART 为460800 bit/s、8N1，每字节占10位。};
''','实际串口帧格式。彩色字段按接收顺序排列，图中宽度不按字节数等比例。',['rtl/packet_link.sv','host/protocol.py'])

diagram('packet-fsm',6.4,r'''
\node[vcaption] at (.1,6.05) {接收一包数据，需要经过五步};
\node[vstate] (a) at (1.7,4.55) {0\quad 找 A5\\同步第一字节};
\node[vstate] (b) at (6.85,4.55) {1\quad 找 5A\\同步第二字节};
\node[vstate] (c) at (12.1,4.55) {2\quad 收头部\\10字节};
\node[vstate,fill=vTeal!7,draw=vTeal] (d) at (12.1,2.3) {3\quad 收数据\\0--512字节};
\node[vstate,fill=vAmber!9,draw=vAmber] (e) at (6.85,2.3) {4\quad 收 CRC\\校验后交付请求};
\draw[vline] (a)--(b);\draw[vline] (b)--(c);\draw[vline] (c)--(d);\draw[vline] (d)--(e);
\draw[vflow] (e.west)--(1.7,2.3)--node[vlabel,left]{下一帧}(a.south);
\draw[vcontrol] (c.south west)--node[vlabel,above,sloped]{数据长度为0}(e.north east);
\draw[vcontrol] (c.north)--(12.1,5.65)--node[vlabel,above]{版本或长度错误：计数并丢弃}(1.7,5.65)--(a.north);
\node[vnote,text width=124mm] at (7.2,.6) {CRC 不符：计错，不交付请求。同步字第二字节不匹配时继续寻找；发送侧按字节索引输出同样的帧。};
''',r'packet\_link 接收状态。错误包不进入上层命令处理。',['rtl/packet_link.sv'], 'RTL 状态示意；数字0至4与实际状态编码对应，省略字节未收齐时的自循环。')

diagram('export-sequence',6.9,r'''
\node[vcaption] at (.1,6.55) {完整性确认放在最后，读到一半不会清空板内事件};
\node[vdark,text width=35mm] at (2.5,5.7) {电脑};\node[vteal,text width=35mm] at (11.7,5.7) {开发板：冻结事件};
\draw[dashed,vMuted!65] (2.5,.7)--(2.5,5.1);\draw[dashed,vMuted!65] (11.7,.7)--(11.7,5.1);
\foreach \y/\t in {4.7/读取元数据与事件长度,3.65/READ：偏移 + 长度,1.45/ACK：事件号 + 总长度 + 整事件CRC}{\draw[vline] (2.5,\y)--node[vlabel,above]{\t}(11.7,\y);}
\draw[vflow] (11.7,4.2)--node[vlabel,above]{元数据}(2.5,4.2);
\draw[vflow] (11.7,3.15)--node[vlabel,above]{数据块 + 帧校验}(2.5,3.15);
\node[vgold,text width=62mm,minimum height=9mm] at (6.95,2.2) {块校验失败则重读；收齐后检查整事件CRC};
\draw[vflow] (11.7,.9)--node[vlabel,above]{确认成功，释放该组空间}(2.5,.9);
''','事件导出交互。重复读取不会改写已冻结的数据。',['host/capture.py','rtl/record_bank.sv','rtl/event_recorder_top.sv'])

diagram('cic-pipeline',5.4,r'''
\node[vcaption] at (.1,5.05) {把高速比特流，变成可以保存和播放的声音};
\node[vbox,text width=19mm] (b) at (1.2,3.55) {PDM\\0 / 1};
\node[vbox,text width=20mm] (m) at (4.0,3.55) {映射\\$-1 / +1$};
\node[vbox,text width=22mm] (i) at (7.0,3.55) {三级积分\\24位整数};
\node[vteal,text width=22mm] (r) at (10.1,3.55) {每125点\\抽取一次};
\node[vteal,text width=22mm] (c) at (13.2,3.55) {三级差分\\24位整数};
\draw[vline] (b)--(m);\draw[vline] (m)--(i);\draw[vline] (i)--(r);\draw[vflow] (r)--(c);
\node[vgold,text width=54mm] (s) at (9.4,1.6) {乘281475，再除以$2^{24}$\\对称舍入 + 16位限幅};
\node[vdark,text width=37mm] (o) at (2.8,1.6) {PCM16\quad 16 kHz\\电脑写成 WAV};
\draw[vflow] (c.south)|-(s.east);\draw[vline] (s)--(o);
\node[vnote] at (7.2,.3) {前半段：2 MHz\qquad 后半段：16 kHz\qquad 运算分拍完成，valid 信号随数据逐级传递};
''','三级 CIC 与定点缩放的实现路径。滤波会带来延迟和幅频变化。',['rtl/pdm_cic.sv','rtl/pdm_frontend.sv'])

diagram('time-alignment',5.6,r'''
\node[vcaption] at (.1,5.25) {不同采样速度，用同一把时间尺来对齐};
\foreach \y/\t in {4.15/PCM,2.9/XYZ,1.6/特征窗}{\node[anchor=east] at (1.6,\y) {\t};\draw[vline] (1.9,\y)--(14,\y);}
\foreach \x in {2.1,2.45,...,13.8}{\fill[vBlue] (\x,4.15) circle (1.2pt);}
\foreach \x in {2.35,5.05,7.85,10.55,13.35}{\draw[vTeal,line width=1pt] (\x,2.65)--(\x,3.15);\fill[vTeal] (\x,2.9) circle (2pt);}
\foreach \x/\t in {2/第1窗,7.75/第2窗}{\path[fill=vAmber!12,draw=vAmber!65] (\x,1.2) rectangle +(5.4,.8);\node[font=\footnotesize] at (\x+2.7,1.6) {\t：10 ms};}
\node[vlabel,above] at (8.2,4.3) {PCM 每62.5 $\mu$s一个点};
\node[vlabel,above] at (9.2,3.05) {XYZ 约5 ms一组，使用实测时间戳};
\node[vnote,text width=124mm] at (7.2,.35) {100 MHz 计数器给两路数据记时；读出延迟不当成采样时间。某窗没有有效振动数据，就标为无效。};
''','采样时间与特征窗口的关系。XYZ 时刻是示意，不表示固定等间隔。',['rtl/feature_window.sv','rtl/adxl362_reader.sv','report/design.tex'])

diagram('event-window',4.6,r'''
\node[vcaption] at (.1,4.25) {自动判断晚一点，也能留下动作发生之前的数据};
\path[fill=vBlue!9,draw=vBlue] (1.4,1.7) rectangle (5.3,3.0);\path[fill=vTeal!9,draw=vTeal] (5.3,1.7) rectangle (13.1,3.0);
\node at (3.35,2.35) {前0.5秒\quad 8000点};\node at (9.2,2.35) {后1秒\quad 16000点};
\draw[vline] (1.1,1.25)--(13.5,1.25);\foreach \x/\t in {1.4/-0.5,5.3/0,13.1/1.0}{\draw[vMuted] (\x,1.15)--(\x,1.35);\node[below,font=\footnotesize] at (\x,1.15) {\t\ s};}
\draw[vcontrol] (5.3,3.8)--node[vlabel,right]{保存参考时刻}(5.3,3.0);
\node[vnote,text width=124mm] at (7.2,.35) {完整声音：24000点；XYZ 按各自实际时间保留。图中点数来自16 kHz设计采样率，不是额外采样试次。};
''','1.5 秒事件的时间组成。前段由环形历史提供，后段继续采集。',['rtl/record_bank.sv','host/capture.py'])

diagram('trigger-logic',6.7,r'''
\node[vcaption] at (.1,6.35) {先认出各自的变化，再看两路能不能配成一对};
\node[vbox,text width=26mm] (a) at (1.6,4.8) {声音上穿阈值\\记下声音时刻};
\node[vteal,text width=26mm] (v) at (1.6,2.7) {振动上穿阈值\\记下振动时刻};
\node[vgold,text width=33mm,minimum height=25mm] (p) at (7,3.75) {两路候选配对\\$|t_a-t_v|\leq50$ ms\\允许任一路先到};
\node[vbox,text width=27mm] (d) at (12.5,4.8) {距上次确认\\至少300 ms？};
\node[vteal,text width=27mm] (c) at (12.5,2.7) {确认一次事件\\锚点取后到一路};
\draw[vline] (a.east)--(p.north west);\draw[vflow] (v.east)--(p.south west);\draw[vline] (p.east)--(d.west);\draw[vflow] (d)--node[vlabel,right]{是}(c);
\node[vred,text width=46mm] at (5.6,.75) {候选过期则清除；配对后消耗候选};
\node[vnote,text width=46mm] at (11.6,.7) {在300 ms内再次配对会被抑制；\\确认成功后，还需检查存储是否忙。};
''','联合触发逻辑关系。当前实现仍使用上穿规则，没有加入新的滞回阈值。',['rtl/trigger_core.sv'], '行为示意；RTL 用待配对标志实现，并没有这些名称的枚举状态。')

diagram('spi-timing',5.2,r'''
\node[vcaption] at (.1,4.85) {SPI mode 0：空闲低，上升沿采样，下降沿换下一位};
\node[anchor=east] at (1.5,3.6) {CS\_N};\node[anchor=east] at (1.5,2.5) {SCLK};\node[anchor=east] at (1.5,1.3) {MOSI};
\draw[vBlue,line width=1pt] (1.9,3.85)--(2.5,3.85)--(2.5,3.35)--(12.5,3.35)--(12.5,3.85)--(13.8,3.85);
\draw[vBlue,line width=1pt] (1.9,2.25)--(3,2.25) \foreach \x in {3,4.15,5.3,6.45,7.6,8.75,9.9,11.05}{--(\x,2.25)--(\x,2.8)--(\x+.575,2.8)--(\x+.575,2.25)} --(13.8,2.25);
\foreach \x/\t in {2.425/D7,3.575/D6,4.725/D5,5.875/D4,7.025/D3,8.175/D2,9.325/D1,10.475/D0}{\draw[fill=vTeal!9,draw=vTeal!65] (\x,1.0) rectangle +(1.15,.6);\node[font=\footnotesize] at (\x+.575,1.3) {\t};}
\foreach \x in {3,4.15,5.3,6.45,7.6,8.75,9.9,11.05}{\draw[vcontrol] (\x,3.05)--(\x,2.83);}
\node[vnote,text width=125mm] at (7.2,.35) {SCLK = 2 MHz，周期0.5 $\mu$s；高位先传。MISO 先经过两级同步，再由控制器取样；此图仅画单字节。};
''','SPI 单字节时序示意，箭头标出控制器取样沿。',['rtl/spi_master.sv'], '接口时序示意；不是逻辑分析仪实测截图。')

diagram('i2c-lines',6.0,r'''
\node[vcaption] at (.1,5.65) {I²C 的高电平靠释放线路，控制器只主动拉低};
\node[vbox,text width=30mm,minimum height=23mm] (f) at (2,3.5) {FPGA 控制器\\SCL / SDA\\输出0或高阻Z};
\node[vteal,text width=30mm,minimum height=23mm] (s) at (12.3,3.5) {ADT7420\\地址0x4B\\身份 / 设置 / 温度};
\draw[vline,<->] ([yshift=5mm]f.east)--node[vlabel,below]{SCL：等待实际电平变高}([yshift=5mm]s.west);
\draw[vflow,<->] ([yshift=-5mm]f.east)--node[vlabel,below]{SDA：数据 / ACK}([yshift=-5mm]s.west);
\foreach \x/\y in {6/4,8.4/3}{\draw[vMuted] (\x,\y)--(\x,4.7);\draw[vMuted] (\x-.18,4.7) rectangle (\x+.18,5.15);\draw[vMuted] (\x,5.15)--(\x,5.35);\node[font=\scriptsize,anchor=west] at (\x+.3,4.95) {上拉};\fill[vMuted] (\x,\y) circle (1.5pt);}
\node[vgold,text width=119mm] at (7.2,1.35) {写寄存器地址 $\rightarrow$ 重复起始 $\rightarrow$ 读温度字节 $\rightarrow$ NACK / STOP\\\footnotesize 检查ACK；SCL被拉低则等待，超过超时上限就退出并报错};
\node[vnote] at (7.2,.3) {功能连接示意，未给出PCB布线、上拉阻值或器件电气参数；实际网络以归档官方原理图为准。};
''','I²C 开漏连接与寄存器读取过程。时钟拉伸通过读取线路实际电平判断。',['rtl/i2c_register.sv','rtl/adt7420_reader.sv','report/monitor_hardware.tex'])

diagram('gpio-chain',4.7,r'''
\node[vcaption] at (.1,4.35) {把手按出来的抖动，变成稳定的状态和计数};
\node[vgold,text width=21mm] (a) at (1.45,2.8) {开关 / 按键\\外部输入};
\node[vbox,text width=22mm] (s) at (4.5,2.8) {两级寄存器\\同步到100 MHz};
\node[vbox,text width=22mm] (d) at (7.8,2.8) {约20 ms去抖\\稳定后才更新};
\node[vteal,text width=31mm] (p) at (12,2.8) {状态位 + 边沿计数\\电脑显示按下与释放};
\draw[vcontrol] (a)--(s);\draw[vline] (s)--(d);\draw[vflow] (d)--(p);
\node[vred,text width=56mm] at (3.5,.95) {SW8、SW9：LVCMOS18\\对应1.8 V供电的Bank};
\node[vnote,text width=60mm] at (10.8,.95) {其余普通输入按实际XDC设置；CPU RESET和PROG不是这里统计的五个方向按键。};
''','普通输入的同步、去抖与计数流程。电压标准必须跟随真实引脚约束。',['rtl/gpio_monitor.sv','constraints/nexys_a7_100t.xdc'])

diagram('portable-flow',7.2,r'''
\node[vcaption] at (.1,6.85) {老师拿到EXE以后：从插板到看到曲线};
\foreach \x/\y/\n/\t/\c in {2.1/5.4/a/打开EXE\\枚举USB与串口/vbox,7.2/5.4/b/选择并确认板型\\Nexys A7-100T/vgold,12.3/5.4/c/初始化此板\\检查JTAG目标/vbox,12.3/3.3/d/校验内置位流\\下载到SRAM/vbox,7.2/3.3/e/核对固件版本\\建立串口会话/vteal,2.1/3.3/f/实时监测\\保存与查看事件/vteal}{\node[\c,text width=31mm] (\n) at (\x,\y) {\t};}
\draw[vline] (a)--(b);\draw[vline] (b)--(c);\draw[vline] (c)--(d);\draw[vflow] (d)--(e);\draw[vflow] (e)--(f);
\node[vred,text width=121mm] at (7.2,1.15) {缺驱动或找不到目标：显示诊断与驱动准备入口，处理后重试\\\footnotesize SRAM配置掉电丢失；重新初始化会清除板内临时事件，已导出的电脑文件保留};
\node[vnote] at (7.2,.2) {使用流程示意；本机已验，另一台电脑、第二块同型号板和常规FTDI实板路径仍待验证。};
''','独立软件的使用流程。板子按实际设备信息选择，没有绑定原板的序列号。',['host/portable_main.py','host/portable_program.py','host/device_discovery.py','state/portable_acceptance.json'])

diagram('portable-files',5.7,r'''
\node[vcaption] at (.1,5.35) {一个EXE交付，运行数据另存到用户目录};
\path[vgroup] (.1,.9) rectangle (6.8,4.8);\path[vgroup] (7.2,.9) rectangle (14.3,4.8);
\node[vdark,text width=53mm] at (3.45,4.2) {EXE内置的只读资源};
\node[vteal,text width=57mm] at (10.75,4.2) {电脑上新建的运行记录};
\node[align=left,text width=52mm] at (3.45,2.65) {Python运行环境与界面\\[2mm] 固件位流与哈希清单\\[2mm] 编程工具、库与驱动安装包};
\node[align=left,text width=56mm] at (10.75,2.65) {串口原始包与状态日志\\[2mm] WAV、XYZ、事件元数据\\[2mm] 截图、诊断ZIP与版本记录};
\node[vnote,text width=124mm] at (7.2,.35) {数据目录：\texttt{\%LOCALAPPDATA\%/NexysMonitor}\qquad 每次运行另建目录，旧记录保留。};
''','可执行程序与用户数据的分离，便于拷贝软件和保留实验记录。',['host/app_paths.py','host/portable_main.py','host/monitor_service.py'])

diagram('evidence-chain',5.9,r'''
\node[vcaption] at (.1,5.55) {报告里的每条实测结论，都能往回找到原记录};
\node[vbox,text width=28mm] (b) at (1.7,4.1) {实际位流与参数\\设备身份 / SHA-256};
\node[vbox,text width=28mm] (r) at (7.2,4.1) {板端原始串口包\\时间戳 / 事件编号};
\node[vteal,text width=28mm] (p) at (12.7,4.1) {整事件数据\\长度 + CRC核验};
\node[vteal,text width=28mm] (w) at (12.7,1.9) {WAV / XYZ\\元数据 / 输入哈希};
\node[vgold,text width=28mm] (f) at (7.2,1.9) {参考计算与绘图\\脚本版本 / 图表索引};
\node[vdark,text width=28mm] (d) at (1.7,1.9) {报告与复现实验包\\结论 / 图表 / 清单};
\draw[vline] (b)--(r);\draw[vline] (r)--(p);\draw[vflow] (p)--(w);\draw[vflow] (w)--(f);\draw[vline] (f)--(d);
\node[vnote,text width=125mm] at (7.2,.4) {失败试次另留目录，修复后另建运行号。本次新增的设计图也记录对应RTL、宿主程序和TikZ源文件哈希。};
''','实测图表的证据链。设计示意图和真实波形、实物照片分别标注来源。',['host/audit.py','host/capture.py','host/report_content.py','host/monitor_report_content.py'])

diagram('pdm-timing',4.8,r'''
\node[vcaption] at (.1,4.45) {PDM 不是一个个音量值，而是连续的0和1};
\node[anchor=east] at (1.6,3.3) {M\_CLK};\node[anchor=east] at (1.6,2.1) {DATA};
\draw[vBlue,line width=1pt] (2,3.05) \foreach \x in {2.5,4,5.5,7,8.5,10,11.5}{--(\x,3.05)--(\x,3.6)--(\x+.75,3.6)--(\x+.75,3.05)} --(13.5,3.05);
\foreach \x/\t in {2/1,3.5/0,5/1,6.5/1,8/0,9.5/1,11/0}{\draw[fill=vTeal!8,draw=vTeal!60] (\x,1.8) rectangle +(1.5,.6);\node[font=\footnotesize] at (\x+.75,2.1) {\t};}
\foreach \x in {2.5,4,5.5,7,8.5,10,11.5}{\draw[vcontrol] (\x,3.95)--(\x,3.65);}
\node[vnote,text width=124mm] at (7.2,.7) {100 MHz主时钟每25拍翻转M\_CLK，得到2 MHz；LR固定为0。DATA经两级同步，在上升相位使能采样，随后进入CIC。};
''','PDM 接口与采样使能示意。示例比特只用于解释接口，不代表真实录音。',
['rtl/recorder_top.sv','rtl/pdm_cic.sv'], '接口逻辑示意；未测量麦克风引脚的模拟延迟与建立保持时间。')

diagram('board-photo',8.9,r'''
\node[anchor=south west,inner sep=0] at (0,.45) {\includegraphics[width=10.4cm]{board_original.jpg}};
\foreach \x/\y/\n in {1.15/6.15/1,5.15/4.05/2,2.0/3.35/3,7.2/2.8/4,5.4/.9/5}{\node[circle,fill=vNavy,draw=white,line width=1.3pt,text=white,font=\bfseries\footnotesize,minimum size=6mm,inner sep=0] at (\x,\y) {\n};}
\node[vcaption] at (10.7,8) {实物位置导览};
\foreach \y/\n/\a/\b in {7.1/1/PROG-UART/编程与串口USB,5.75/2/FPGA/Artix-7 100T,4.4/3/MIC/板载麦克风区域,3.05/4/方向按键/上、下、左、右、中,1.7/5/拨码开关/底部16个开关}{
\node[circle,fill=vNavy,text=white,font=\bfseries\footnotesize,minimum size=5mm,inner sep=0] at (10.95,\y) {\n};
\node[anchor=west,align=left,font=\footnotesize] at (11.4,\y) {\a\\\scriptsize\b};}
''','原实验板照片的位置导览。编号覆盖在原照片上，照片内容和文件保持原样。',
['report/figures/board_original.jpg','report/design.tex'], '操作者提供的真实照片；亚克力、反光和遮挡保留。编号表示区域位置。')

def command(name):
    d=D[name]
    note='' if d['note']=='设计示意；连线表示功能关系，不是实测波形。' else d['note']
    return '\\vdiagram{'+name+'}{'+d['caption']+'}{'+note+'}\n'

def generate_visuals(run):
    folder=ROOT/'report/visuals';folder.mkdir(exist_ok=True)
    # Use routed-report values already parsed and checked by generate_monitor.
    values=json.loads((ROOT/'report/generated/monitor_implementation_values.json').read_text(encoding='utf8'))
    body=r'\node[vcaption] at (.1,5.75) {当前扩展版的实际资源用量};'+'\n'
    resources=[('LUT','Slice LUTs',63400,'vBlue'),('FF','Slice Registers',126800,'vTeal'),('BRAM','Block RAM Tile',135,'vAmber'),('DSP','DSPs',240,'vRed')]
    for i,(label,key,total,color) in enumerate(resources):
        used=values['resources'][key];percent=used/total*100;y=4.65-i*1.05
        body+=fr'\node[anchor=east] at (1.6,{y}) {{{label}}};\path[fill=vPaper,rounded corners=1mm] (1.9,{y-.23}) rectangle +(8.1,.46);\path[fill={color},rounded corners=1mm] (1.9,{y-.23}) rectangle +({8.1*used/total:.5f},.46);\node[anchor=west,font=\footnotesize] at (10.3,{y}) {{{used:g} / {total}\quad {percent:.1f}\%}};'+'\n'
    body+=r'\node[vnote,text width=124mm] at (7.2,.4) {资源有空余，不等于时序余量充足。100 MHz布局布线结果：WNS 0.045 ns，TNS 0；具体数值仍以原报告为准。};'
    diagram('resource-use',6.1,body,'当前位流的实际资源占用。百分比由布局布线报告中的用量计算。',
            ['report/generated/monitor_implementation_values.json','runs/'+values['build_run_id']+'/implementation/utilization_routed.rpt'],
            '工具报告统计；不是新采样实验，资源余量不能代替时序或跨板验证。')
    result_path=ROOT/'runs/20261113T233134_202541_evaluate/results.json'
    result=json.loads(result_path.read_text(encoding='utf8'))
    body=r'\node[vcaption] at (.1,6.5) {同一批留出数据：五次轻敲，十次非敲击};'+'\n'
    for i,(key,label) in enumerate([('audio','仅声音'),('accel','仅振动'),('joint','声振联合')]):
        m=result['holdout'][key]['metrics'];x=.1+i*4.85
        assert m['TP']+m['FN']==5 and m['FP']+m['TN']==10
        body+=fr'\path[vgroup] ({x},.95) rectangle + (4.65,5.0);\node[vdark,text width=33mm] at ({x+2.325},5.35) {{{label}}};'+'\n'
        body+=fr'\node[anchor=west,font=\footnotesize] at ({x+.3},4.35) {{轻敲：找到{m["TP"]}，漏检{m["FN"]}}};'+'\n'
        for j in range(5):
            color='vTeal' if j<m['TP'] else 'vRed'
            body+=fr'\path[fill={color}!75,rounded corners=.5mm] ({x+.3+j*.8},3.6) rectangle +(.65,.43);'+'\n'
        body+=fr'\node[anchor=west,font=\footnotesize] at ({x+.3},3.0) {{非敲击：不报{m["TN"]}，误报{m["FP"]}}};'+'\n'
        for j in range(10):
            color='vTeal' if j<m['TN'] else 'vRed'
            body+=fr'\path[fill={color}!75,rounded corners=.4mm] ({x+.3+j*.4},2.25) rectangle +(.32,.43);'+'\n'
        body+=fr'\node[font=\bfseries] at ({x+2.325},1.5) {{F1 = {m["F1"]:.3f}}};'+'\n'
    body+=r'\node[vnote,text width=124mm] at (7.2,.3) {每格表示一次试次，按结果数量排列；绿色为判断正确，红色为错误。小样本只描述本批表现，不推断普遍优劣。};'
    diagram('holdout-outcomes',6.9,body,'三种触发方法的留出结果图解。声音额外触发次数仍按原表单列。',
        [result_path.relative_to(ROOT).as_posix(),'report/generated/claim_index.json'],'原实板数据重绘；对应扩展前的位流，不是新增传感器后的重新采样。')
    # Make each drawing independently inspectable and include the same sources in delivery.
    index=[]
    for name,d in D.items():
        path=folder/(name+'.tex');path.write_text(d['tex'].replace('\\footnotesize','\\vsmall').replace('\\scriptsize','\\vtiny'),encoding='utf8')
        known=[]
        for source in d['sources']:
            p=ROOT/source
            if not p.is_file():
                # Resolve renamed source modules explicitly, never silently cite missing files.
                alternatives={'rtl/event_recorder_top.sv':'rtl/recorder_top.sv','rtl/pdm_frontend.sv':'rtl/recorder_top.sv','rtl/feature_window.sv':'rtl/feature_core.sv',
                              'rtl/adxl362_reader.sv':'rtl/adxl362.sv','rtl/adt7420_reader.sv':'rtl/adt7420.sv',
                              'rtl/gpio_monitor.sv':'rtl/gpio.sv','docs/A0_baseline.md':'report/design.tex'}
                p=ROOT/alternatives.get(source,source)
            if not p.is_file():raise FileNotFoundError(source)
            known.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p)})
        index.append({'figure':name,'kind':'tool_report_statistics' if name=='resource-use' else 'source_based_design_illustration',
            'caption':d['caption'],'note':d['note'],'tikz_source':path.relative_to(ROOT).as_posix(),'tikz_sha256':sha256(path),'inputs':known})
    # Generated chapters are rebuilt on every report run, so insert their hooks here.
    inserts={'monitor_experiments.tex':('\\section{失败记录和本次验证的范围}',command('resource-use')),
             'portable_experiments.tex':('\\section',command('portable-flow')+command('portable-files')),
             'monitor_evidence.tex':('\\section',command('evidence-chain')),
             'experiments.tex':('\\section{真实自动保存和一分钟安静观察}',command('holdout-outcomes'))}
    for name,(anchor,addition) in inserts.items():
        path=ROOT/'report/generated'/name;text=path.read_text(encoding='utf8')
        if addition.strip() not in text:
            pos=text.find(anchor)
            text=text[:pos]+addition+'\n'+text[pos:] if pos>=0 else text+'\n'+addition
            path.write_text(text,encoding='utf8')
    write_json(ROOT/'report/generated/visual_figure_index.json',{'generator':'host/report_visuals.py','generator_sha256':sha256(Path(__file__)),
        'shared_style':'report/visuals/style.tex','shared_style_sha256':sha256(folder/'style.tex'),'figures':index})
    (folder/'README.md').write_text('# 报告矢量插图\n\n共'+str(len(D))+'幅TikZ图，样式集中在style.tex；在Experiment-template.tex中编译，不依赖图片生成服务。\n\n'
        '设计图按源码解释功能，接口时序不是仪器实测。resource-use由真实布局布线报告计算。实物照片、软件截图和原始采样输入均保留。\n'
        '来源及SHA-256：generated/visual_figure_index.json。\n',encoding='utf8')
    run.event('visual_figures_generated',count=len(D),index='report/generated/visual_figure_index.json',purpose='加强工程图示，不改动原始记录和测量结论')
    return len(D)
