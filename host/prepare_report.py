"""Copy immutable template assets; keep author fields explicitly unfilled."""
import shutil,json,csv
from pathlib import Path
from audit import ROOT,Run,write_json,sha256

def prepare():
    run=Run('report_template');source=Path(r'D:/projects/wuxiaoping2/_ref/WHUExperiment');dest=ROOT/'report'
    dest.mkdir(exist_ok=True);(dest/'figures').mkdir(exist_ok=True);(dest/'generated').mkdir(exist_ok=True)
    for relative in ('WHUBachelor.cls','figures/whulogo.pdf','figures/whu.eps','figures/whulogo.eps'):
        shutil.copy2(source/relative,dest/relative)
    for name in ('LICENSE','LICENSE.md','README.md'):
        if (source/name).exists():shutil.copy2(source/name,dest/('template_'+name))
    cover=dest/'cover.tex'
    if not cover.exists():cover.write_text('\\Ccoursename{嵌入式}\n\\Cmajor{待补充}\n\\author{待补充}\n\\CstudentNum{待补充}\n\\Csupervisor{待补充}\n\\CsupervisorAnother{无}\n\\date{二〇二六年十一月}\n',encoding='utf8')
    photo=ROOT/'runs/20261113T200556_515188_board_photo/board_original.jpg'
    shutil.copy2(photo,dest/'figures/board_original.jpg')
    rows=json.loads((ROOT/'runs/20261113T195823_604155_reference_inspection/pinmap.json').read_text(encoding='utf8'))
    for row in rows:
        row['physical_revision_match']='PB200-292 REV D; common pins independently matched in archived D.2/D.3 netlists'
    write_json(ROOT/'config/pin_connections.json',rows)
    pins=r'\begin{table}[htbp]\centering\caption{关键引脚与接口（FPGA视角，均为LVCMOS33）}\small\begin{tabular}{llll}\toprule 信号 & 管脚 & 方向 & 接口职责\\\midrule'+'\n'
    wanted={'CLK100MHZ':'100 MHz输入','BTNU':'采样开始按键','M_CLK':'PDM时钟','M_DATA':'PDM数据','M_LRSEL':'PDM通道选择',
            'ACL_MISO':'SPI接收','ACL_MOSI':'SPI发送','ACL_SCLK':'SPI时钟','ACL_CSN':'SPI片选',
            'ACL_INT[1]':'数据就绪','UART_TXD_IN':'FTDI至FPGA','UART_RXD_OUT':'FPGA至FTDI','LED[0]':'配置状态','LED[15]':'时基指示'}
    for row in rows:
        if row['signal'] in wanted:
            direction='输入' if row['direction_from_fpga']=='input' else '输出'
            pins+='\\code{'+row['signal']+'} & '+row['fpga_pin']+' & '+direction+' & '+wanted[row['signal']]+r'\\'+'\n'
    pins+=r'\bottomrule\end{tabular}\par\footnotesize 出处：归档官方主XDC与D.2/D.3图纸；完整29项及来源哈希见config/pin\_connections.json。\end{table}'
    (dest/'generated/pins.tex').write_text(pins,encoding='utf8')
    write_json(dest/'template_provenance.json',{'upstream':'https://github.com/xiaoxinganling/WHUExperiment',
        'commit':'000c2b12693d9b914bfaf4f1ddfe2476a679cf6e',
        'unchanged_files':[{'file':p,'sha256':sha256(dest/p)} for p in ('WHUBachelor.cls','figures/whulogo.pdf','figures/whu.eps','figures/whulogo.eps')]})
    run.event('template_assets_copied',source=str(source),destination=str(dest));run.snapshot('指定模板原类文件和校徽，封面缺项明确保留待补');run.manifest()

if __name__=='__main__':prepare()
