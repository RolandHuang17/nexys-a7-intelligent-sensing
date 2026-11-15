"""Export the same TikZ sources as individual vector PDFs and preview PNGs."""
import json,shutil,sys,math
import pymupdf
from PIL import Image,ImageDraw,ImageFont
from audit import ROOT,Run,sha256,write_json
from report import TEX

def main():
    run=Run('diagram_gallery');index=json.loads((ROOT/'report/generated/visual_figure_index.json').read_text(encoding='utf8'))
    rows=index['figures'];source=ROOT/'report/Diagram-gallery.tex'
    source.write_text(r'''\documentclass[multi=tikzpicture,border=4mm]{standalone}
\usepackage[UTF8]{ctex}
\usepackage{tikz,graphicx,xcolor,etoolbox,float}
\graphicspath{{figures/}}
\input{visuals/style}
\begin{document}
'''+''.join('\\input{visuals/'+row['figure']+'}\n' for row in rows)+r'\end{document}'+'\n',encoding='utf8')
    rc,_=run.command([TEX,'-xelatex','-interaction=nonstopmode','-halt-on-error','-file-line-error','-outdir='+str(run.path),'Diagram-gallery.tex'],
                     '用报告同一份TikZ源码导出26幅独立矢量图',cwd=ROOT/'report',timeout=240)
    assert rc==0
    pdf=run.path/'Diagram-gallery.pdf';doc=pymupdf.open(pdf);assert len(doc)==len(rows)
    target=ROOT/'deliver/插图';target.mkdir(exist_ok=True);shutil.copy2(pdf,target/'图解合集.pdf')
    canvas=Image.new('RGB',(1800,math.ceil(len(rows)/3)*330),'#E7EDF3');draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    for i,row in enumerate(rows):
        name=row['figure'];one=pymupdf.open();one.insert_pdf(doc,from_page=i,to_page=i);one.save(target/(name+'.pdf'));one.close()
        doc[i].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(target/(name+'.png'))
        im=Image.open(target/(name+'.png'));im.thumbnail((570,275));x=(i%3)*600;y=(i//3)*330
        draw.rounded_rectangle((x+8,y+8,x+592,y+320),radius=12,fill='white')
        canvas.paste(im,(x+(600-im.width)//2,y+15+(275-im.height)//2))
        title=f'{i+1:02d}  '+name;draw.text((x+20,y+292),title,font=font,fill='#173B5C')
        row['exports']=[{'file':name+ext,'sha256':sha256(target/(name+ext))} for ext in ('.pdf','.png')]
    canvas.save(target/'插图总览.png');write_json(target/'插图索引.json',index)
    (target/'说明.md').write_text('# 独立插图\n\n26幅图与报告使用同一份TikZ源码。PDF可无损放大，PNG可直接用于答辩。\n\n'
        '完整源码：../报告源码/visuals/；合集入口：../报告源码/Diagram-gallery.tex。\n'
        '从报告源码目录编译：latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Diagram-gallery.tex\n'
        '数据来源、输入哈希和图稿哈希见插图索引.json；设计示意不能替代实板测量。\n',encoding='utf8')
    run.event('diagram_exports_completed',count=len(rows),pdf_sha256=sha256(target/'图解合集.pdf'),output='deliver/插图');run.manifest();print(run.run_id)
if __name__=='__main__':main()
