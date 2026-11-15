import sys
from pathlib import Path
import fitz
from PIL import Image,ImageOps,ImageDraw
from audit import ROOT,Run,write_json,sha256

def render(pdf):
    pdf=Path(pdf);run=Run('pdf_render');output=run.path/'pages';output.mkdir()
    doc=fitz.open(pdf);texts=[]
    for i,page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(output/f'page_{i+1:02d}.png')
        texts.append({'page':i+1,'characters':len(page.get_text()),'text':page.get_text()})
    for group in range(0,len(doc),9):
        canvas=Image.new('RGB',(1200,1740),'#e1e5e9');draw=ImageDraw.Draw(canvas)
        for j in range(group,min(group+9,len(doc))):
            im=Image.open(output/f'page_{j+1:02d}.png');im.thumbnail((380,545))
            x=(j-group)%3*400+10;y=(j-group)//3*580+20
            canvas.paste(im,(x,y));draw.text((x,y+548),f'Page {j+1}',fill='black')
        canvas.save(run.path/f'contact_{group//9+1}.png')
    write_json(run.path/'page_texts.json',texts)
    run.event('pdf_rendered',input=str(pdf),sha256=sha256(pdf),pages=len(doc));run.manifest()
    print(run.path);return run.path

if __name__=='__main__':render(sys.argv[1])
