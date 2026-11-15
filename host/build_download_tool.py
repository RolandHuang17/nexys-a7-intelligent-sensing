"""Build the pinned GPL xc3sprog helper against FTDI's original D2XX library."""
import json,os,shutil,urllib.request
from audit import ROOT,Run,write_json,sha256

def build():
    r=Run('build_xc3sprog');base=ROOT/'upstream/portable';meta=json.loads((base/'provenance.json').read_text(encoding='utf8'))
    source=base/'source'/('xc3sprog-'+meta['xc3sprog_commit']);work=ROOT/'.portable_build/xc3sprog';work.mkdir(parents=True,exist_ok=True)
    compat=work/'compat/libusb';compat.mkdir(parents=True,exist_ok=True)
    cached=base/'compat/libusb/usb.h'
    url='https://raw.githubusercontent.com/mcuee/libusb-win32/master/libusb/src/lusb0_usb.h'
    if cached.exists():data=cached.read_bytes()
    else:
        data=urllib.request.urlopen(url,timeout=40).read();cached.parent.mkdir(parents=True,exist_ok=True);cached.write_bytes(data)
    (compat/'usb.h').write_bytes(data)
    write_json(base/'usb_header_provenance.json',{'url':url,'sha256':sha256(compat/'usb.h')})
    ftdi=ROOT/'upstream/tools/openocd';driver=base/'ftdi'
    cmake=ROOT/'.venv/Scripts/cmake.exe'
    args=[cmake,'-S',source,'-B',work,'-G','MinGW Makefiles','-DCMAKE_BUILD_TYPE=Release','-DUSE_WIRINGPI=OFF',
          '-DLIBFTDI_INCLUDE_DIR='+str(ftdi/'include/libftdi1'),'-DLIBFTDI_LIBRARIES='+str(ftdi/'bin/libftdi1.dll'),
          '-DLIBFTD2XX_INCLUDE_DIR='+str(driver),'-DLIBFTD2XX_LIBRARIES='+str(driver/'amd64/ftd2xx.lib'),
          '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG -fpermissive -DO_NONBLOCK=0 -DO_SYNC=0 -I'+str(work/'compat'),
          '-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG -I'+str(work/'compat')]
    rc,_=r.command(args,'配置固定提交的D2XX下载后端',timeout=120);assert rc==0
    rc,_=r.command([cmake,'--build',work,'--target','xc3sprog','--parallel','6'],'构建Windows x64独立下载助手',timeout=180);assert rc==0
    dest=base/'xc3sprog';dest.mkdir(exist_ok=True)
    for p in [work/'xc3sprog.exe',ftdi/'bin/libftdi1.dll',ftdi/'bin/libusb-1.0.dll',driver/'amd64/FTD2XX64.dll']:
        shutil.copy2(p,dest/p.name)
    shutil.copy2(driver/'amd64/FTD2XX64.dll',dest/'ftd2xx.dll')
    for name in ('LICENSE','COPYING','README.Win32','devlist.txt','cablelist.txt'):
        shutil.copy2(source/name,dest/name)
    rc,out=r.command([dest/'xc3sprog.exe','-h'],'下载助手启动及参数检查',cwd=dest,timeout=10)
    assert 'xc3sprog' in out.lower()
    write_json(base/'xc3sprog_build.json',{'source_commit':meta['xc3sprog_commit'],'run_id':r.run_id,
        'binary_sha256':sha256(dest/'xc3sprog.exe'),'compiler':'MinGW-w64 GCC 8.1.0','backend':'FTD2XX; libftdi path unused'})
    r.manifest();print(r.run_id)

if __name__=='__main__':build()
