"""Stage public demo files, versioned provenance and local-only documentation."""
import json,zipfile,shutil
from audit import ROOT,Run,write_json,sha256

if __name__=='__main__':
    r=Run('stage_music_assets');p=ROOT/'music_demo/manifest.json';manifest=json.loads(p.read_text(encoding='utf8'))
    for row in manifest['tracks']:
        cached=(ROOT/'upstream/music/licenses'/(row['title']+'.html')).read_text(encoding='utf8')
        if 'creativecommons.org/licenses/by/4.0' not in cached:raise ValueError('作者许可出处未核实')
        row.update(license='CC BY 4.0',credit=f'{row["title"]} by {row["artist"]}; Licensed under Creative Commons Attribution 4.0; https://creativecommons.org/licenses/by/4.0/ ; '+row['license_page'])
    write_json(p,manifest)
    (ROOT/'music_demo/署名与用途.txt').write_text('曲目按作者官网CC BY 4.0许可提供，演示和再分发须保留署名。library是五首入库曲目，其余仅供库外验收。\n\n'+'\n\n'.join(x['credit'] for x in manifest['tracks']),encoding='utf8')
    out=ROOT/'deliver/软件';out.mkdir(exist_ok=True)
    archive=out/'手机演示歌单.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
        for file in (ROOT/'music_demo').rglob('*'):
            if file.is_file():z.write(file,file.relative_to(ROOT))
    state=json.loads((ROOT/'state/build/status.json').read_text(encoding='utf8'))
    build_id=json.loads((ROOT/'runs'/state['run_id']/'build_inputs.json').read_text(encoding='utf8'))['build_id']
    (ROOT/'rtl/build_id.svh').write_text("`define RECORDER_BUILD_ID 32'h"+build_id+'\n',encoding='ascii')
    r.event('public_demo_staged',tracks=len(manifest['tracks']),archive=str(archive.relative_to(ROOT)),sha256=sha256(archive),firmware_header_restored_to_10s_build=build_id)
    r.manifest();print(r.run_id)
