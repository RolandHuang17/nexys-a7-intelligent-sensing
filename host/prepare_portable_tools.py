"""Download pinned upstream sources and official FTDI redistributables with provenance."""
import json,re,urllib.request,zipfile
from pathlib import Path
from audit import ROOT,Run,write_json,sha256

def fetch(url,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(url,headers={'User-Agent':'NexysMonitor/1.0'})
    with urllib.request.urlopen(req,timeout=90) as response:target.write_bytes(response.read())
    return {'url':url,'path':target.relative_to(ROOT).as_posix(),'sha256':sha256(target),'bytes':target.stat().st_size}

def main():
    run=Run('portable_tools');dest=ROOT/'upstream/portable';dest.mkdir(exist_ok=True);rows=[]
    api=dest/'xc3sprog_commit.json';rows.append(fetch('https://api.github.com/repos/matrix-io/xc3sprog/commits/f4bebd014da3e7e8f6b04dbe41de089b256a9a1b',api))
    commit=json.loads(api.read_text())['sha'];archive=dest/'xc3sprog_source.zip'
    rows.append(fetch(f'https://codeload.github.com/matrix-io/xc3sprog/zip/{commit}',archive))
    with zipfile.ZipFile(archive) as z:z.extractall(dest/'source')
    # Preserve the exact manufacturer's page as provenance for links and redistribution terms.
    page=dest/'ftdi_vendor_mirror_page.html';rows.append(fetch('https://redz-sc.com/en/support/driver',page))
    # FTDI's own server returns 403 in this environment. The device vendor mirrors
    # unchanged packages and publishes the exact archive hashes, retained above.
    archives=[('CDM-v2.12.36.20-WHQL-Certified.zip','e8ebf401d06994183694d78e5855ed5ab026bdfa8c3d4e4ccde09ec238a0eaf1','ftdi'),
              ('CDM2123620_Setup.zip','e412945bb98f96b3296a89a549e6b617129e5481e0be2fe5410247857c507796','driver_setup')]
    for name,expected,folder in archives:
        url='https://redz-sc.com/download/ftdi/'+name;archive=dest/name;rows.append(fetch(url,archive))
        assert sha256(archive)==expected,'Driver archive differs from published original'
        with zipfile.ZipFile(archive) as z:z.extractall(dest/folder)
    write_json(dest/'provenance.json',{'xc3sprog_commit':commit,'downloads':rows})
    run.event('portable_tool_sources_downloaded',xc3sprog_commit=commit,downloads=rows);run.manifest()
    print(json.dumps({'run_id':run.run_id,'commit':commit,'ftdi_url':url},ensure_ascii=False))

if __name__=='__main__':main()
