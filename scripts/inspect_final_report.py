"""Render every PDF page and record page count, text coverage and PDF links."""
import argparse
import json
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw


def inspect(pdf, output):
    output.mkdir(parents=True, exist_ok=True)
    doc=pymupdf.open(pdf)
    assert 1 <= len(doc) <= 40, f'{len(doc)} pages exceeds report limit'
    pages=[]
    for i,p in enumerate(doc):
        p.get_pixmap(matrix=pymupdf.Matrix(1.55,1.55),alpha=False).save(output/f'page-{i+1:02}.png')
        overflow=[]
        for b in p.get_text('dict')['blocks']:
            if b['type']!=0: continue
            for line in b.get('lines',[]):
                for span in line['spans']:
                    r=pymupdf.Rect(span['bbox'])
                    if r.x0 < -1 or r.y0 < -1 or r.x1 > p.rect.width+1 or r.y1 > p.rect.height+1:
                        overflow.append(span['text'])
        pages.append({'page':i+1,'characters':len(p.get_text()),'text':p.get_text(),
                      'links':[l['uri'] for l in p.get_links() if 'uri' in l], 'outside_page':overflow})
    for offset in range(0,len(doc),6):
        canvas=Image.new('RGB',(1200,1750),'#dce3e9');draw=ImageDraw.Draw(canvas)
        for j in range(offset,min(offset+6,len(doc))):
            im=Image.open(output/f'page-{j+1:02}.png');im.thumbnail((560,790))
            x=(j-offset)%2*600+20;y=(j-offset)//2*580+15
            im.thumbnail((560,540))
            canvas.paste(im,(x,y));draw.text((x,y+545),f'Page {j+1}',fill='#153c5b')
        canvas.save(output/f'contact-{offset//6+1:02}.jpg',quality=92)
    check={'pdf':str(pdf),'page_count':len(doc),'cover_download_link':any('NexysMonitor-v1.6.0-win-x64.exe' in u for u in pages[0]['links']),
           'no_text_outside_page':not any(p['outside_page'] for p in pages),
           'pages':pages}
    assert check['cover_download_link'], 'No direct EXE link on cover'
    assert check['no_text_outside_page'], 'Text outside page'
    (output/'inspection.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in check.items() if k!='pages'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pdf',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();inspect(args.pdf,args.output)
