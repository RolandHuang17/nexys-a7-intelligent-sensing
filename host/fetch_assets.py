"""Download primary references and preserve exact bytes and provenance."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

from audit import ROOT, Run, now, sha256, write_json

ASSETS = [
    ("Nexys-A7-100T-OOB-hw.xpr.zip", "https://github.com/Digilent/Nexys-A7/releases/download/100T/OOB/2025.1-1/Nexys-A7-100T-OOB-hw.xpr.zip", "77672b7708bd676d5dd0c979bafebd70fa1d1b4a09aff34dbe20f464247bca13"),
    ("Nexys-A7-100T-Master.xdc", "https://raw.githubusercontent.com/Digilent/digilent-xdc/master/Nexys-A7-100T-Master.xdc", None),
    ("nexys-a7_rm.pdf", "https://digilent.com/reference/_media/reference/programmable-logic/nexys-a7/nexys-a7_rm.pdf", None),
    ("nexys-a7-d3-sch.pdf", "https://digilent.com/reference/_media/programmable-logic/nexys-a7/nexys-a7-d3-sch.pdf", None),
    ("adxl362.pdf", "https://www.analog.com/media/en/technical-documentation/data-sheets/adxl362.pdf", None),
    ("PdmDes.vhd", "https://raw.githubusercontent.com/Digilent/Nexys-A7-HW/ac08e1961a6085f7237b346c45785818595dfb71/src/hdl/PdmDes.vhd", None),
    ("ADXL362Ctrl.vhd", "https://raw.githubusercontent.com/Digilent/Nexys-A7-HW/ac08e1961a6085f7237b346c45785818595dfb71/src/hdl/ADXL362Ctrl.vhd", None),
    ("OOB_README.md", "https://raw.githubusercontent.com/Digilent/Nexys-A7-100T-OOB/master/README.md", None),
    ("dmgr.h", "https://raw.githubusercontent.com/Digilent/USB104A7-dspi/master/DSPI_App/USB104A7_dspi_DemoApp/dmgr.h", None),
    ("dpcdecl.h", "https://raw.githubusercontent.com/Digilent/USB104A7-dspi/master/DSPI_App/USB104A7_dspi_DemoApp/dpcdecl.h", None),
]


def download(run, name, url, expected=None):
    directory = ROOT / "upstream" / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.exists() and (expected is None or sha256(target) == expected):
        run.event("asset_reused", name=name, url=url, sha256=sha256(target))
        return True
    run.event("download_started", name=name, url=url, expected_sha256=expected)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        offset = partial.stat().st_size if partial.exists() else 0
        request_headers = {"User-Agent": "Nexys-coursework-reproducibility/1.0"}
        if offset:
            request_headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=90) as response:
            headers = dict(response.headers)
            final_url = response.url
            mode = "ab" if offset and response.status == 206 else "wb"
            run.event("download_transfer", name=name, requested_offset=offset, mode=mode,
                      status=response.status, content_range=response.headers.get("Content-Range"))
            with partial.open(mode) as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
        digest = sha256(partial)
        if expected is not None and expected != digest:
            raise ValueError(f"SHA256 mismatch: {digest}")
        if name.endswith(".pdf") and partial.read_bytes()[:5] != b"%PDF-":
            raise ValueError("server response is not a PDF")
        partial.replace(target)
        record = {"name": name, "url": url, "final_url": final_url, "fetched": now(),
                  "bytes": target.stat().st_size, "sha256": digest, "headers": headers}
        write_json(target.with_suffix(target.suffix + ".source.json"), record)
        run.event("download_finished", **record)
        print(f"OK {name}: {target.stat().st_size} B {digest}", flush=True)
        return True
    except Exception as error:
        run.event("download_failed", name=name, url=url, error=repr(error))
        print(f"FAILED {name}: {error}", flush=True)
        return False


def main():
    run = Run("references")
    run.snapshot("固定官方基线与传感器文档下载程序")
    outcomes = [download(run, *asset) for asset in ASSETS]
    archive = ROOT / "upstream" / "assets" / ASSETS[0][0]
    if archive.exists() and sha256(archive) == ASSETS[0][2]:
        with zipfile.ZipFile(archive) as z:
            names = [n for n in z.namelist() if n.endswith("Nexys4DdrUserDemo.bit")]
            if len(names) != 1:
                raise RuntimeError(f"Expected one baseline bitstream: {names}")
            target = ROOT / "upstream" / "baseline" / "Nexys4DdrUserDemo.bit"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(names[0]))
            digest = sha256(target)
            if digest != "5a92da8b2852ecac5fe0bc7340f1e9f9c9d94b0f27c3b8187749ef915ba50c69":
                raise RuntimeError("Baseline bitstream hash mismatch")
            write_json(run.path / "baseline_assets.json", {"archive_sha256": sha256(archive),
                       "member": names[0], "bitstream_sha256": digest})
            write_json(run.path / "zip_members.json", z.namelist())
            run.event("baseline_extracted", member=names[0], sha256=digest)
    run.manifest()
    print("RUN_ID=" + run.run_id, flush=True)
    return 0 if all(outcomes) else 2


if __name__ == "__main__":
    sys.exit(main())
