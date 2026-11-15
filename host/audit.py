"""Append-only execution evidence. All timestamps include Asia/Shanghai offset."""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

# Native tools retain their exact bytes in *.stdout.bin; Python-facing logs use
# UTF-8 regardless of the Windows console code page.
os.environ.setdefault("PYTHONUTF8", "1")
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app_paths import DATA_ROOT,PORTABLE,RESOURCE_ROOT,APP_VERSION
ROOT = DATA_ROOT
TZ = dt.timezone(dt.timedelta(hours=8))


def now():
    return dt.datetime.now(TZ).isoformat(timespec="milliseconds")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(6):
        try:os.replace(tmp,path);break
        except PermissionError:
            if attempt==5:raise
            time.sleep(.02*(attempt+1))


class Run:
    def __init__(self, name, run_id=None):
        if run_id:
            self.run_id=run_id;self.path=ROOT/'runs'/run_id;self.path.mkdir(parents=True,exist_ok=True)
        else:
            stamp=dt.datetime.now(TZ).strftime('%Y%m%dT%H%M%S_%f')
            while True:
                self.run_id=stamp+'_'+name;self.path=ROOT/'runs'/self.run_id
                try:self.path.mkdir(parents=True,exist_ok=False);break
                except FileExistsError:stamp=dt.datetime.now(TZ).strftime('%Y%m%dT%H%M%S_%f')+'_'+uuid.uuid4().hex[:8]
        self.index = 0
        if not (self.path / "run.json").exists():
            write_json(self.path / "run.json", {"run_id": self.run_id, "stage": name,
                       "started": now(), "root": str(ROOT), "python": sys.executable})

    def event(self, kind, **fields):
        record = {"time": now(), "run_id": self.run_id, "kind": kind, **fields}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        lock_path=ROOT/"runs"/".audit.lock"
        with lock_path.open("a+b") as lock:
            if lock_path.stat().st_size==0:lock.write(b"0");lock.flush()
            if os.name=="nt":
                import msvcrt
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
            try:
                for path in (self.path / "actions.jsonl", ROOT / "runs" / "actions.jsonl"):
                    with path.open("a", encoding="utf-8", newline="\n") as f:
                        f.write(line);f.flush();os.fsync(f.fileno())
            finally:
                if os.name=="nt":lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        return record

    def command(self, argv, purpose, cwd=None, timeout=180, input_text=None, env=None):
        self.index += 1
        step = f"{self.index:03d}_{time.time_ns()}"
        binary = self.path / (step + ".stdout.bin")
        readable = self.path / (step + ".log")
        cwd = Path(cwd or ROOT)
        self.event("command_started", step=step, purpose=purpose, argv=list(map(str, argv)),
                   cwd=str(cwd), timeout_s=timeout, input_text=input_text,
                   environment={k: (env or os.environ).get(k) for k in
                                ("XILINX_VIVADO", "PYTHONUTF8", "LANG", "LC_ALL")})
        start = time.monotonic()
        with binary.open("wb") as output:
            p = subprocess.Popen(list(map(str, argv)), cwd=cwd,
                                 stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT, env=env,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            timed_out = False
            try:
                p.communicate(None if input_text is None else input_text.encode("utf-8"), timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                else:
                    p.kill()
                p.wait()
        data = binary.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gb18030", errors="replace")
        readable.write_text(text, encoding="utf-8")
        self.event("command_finished", step=step, returncode=p.returncode,
                   timed_out=timed_out, elapsed_s=time.monotonic() - start,
                   outputs=[str(binary.relative_to(ROOT)), str(readable.relative_to(ROOT))],
                   stdout_sha256=sha256(binary))
        # Large console writes can block a completed build before its stage
        # index is saved. Preserve full files and keep terminal output bounded.
        print(text[-1200:] if len(text)>1200 else text, end="", flush=True)
        print(f"\n[完整输出: {readable.relative_to(ROOT)}]",flush=True)
        self.manifest()
        return p.returncode, text

    def snapshot(self, purpose):
        if PORTABLE:
            release=RESOURCE_ROOT/'release_manifest.json'
            if release.exists():shutil.copy2(release,self.path/'release_manifest.json')
            self.event('runtime_version_snapshot',purpose=purpose,app_version=APP_VERSION,
                       release_manifest_sha256=sha256(release) if release.exists() else None)
            return
        previous=list((ROOT/"runs").glob("*/source_snapshots/*/source_manifest.json"))
        previous=max(previous,key=lambda p:int(p.parent.name)).parent if previous else None
        tag = str(time.time_ns())
        dest = self.path / "source_snapshots" / tag
        entries = []
        for folder in ("host", "scripts", "rtl", "constraints", "docs", "tests", "report", "config"):
            directory = ROOT / folder
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or any(p in ("__pycache__", ".venv") for p in path.parts):
                    continue
                relative = path.relative_to(ROOT)
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                entries.append({"path": relative.as_posix(), "sha256": sha256(path)})
        for name in ("run.ps1", "README.md", "requirements.txt"):
            path = ROOT / name
            if path.exists():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest / name)
                entries.append({"path": name, "sha256": sha256(path)})
        write_json(dest / "source_manifest.json", entries)
        changes=[]
        for entry in entries:
            current=dest/entry["path"];old=previous/entry["path"] if previous else None
            try:
                before=old.read_text(encoding="utf-8").splitlines(True) if old and old.exists() else []
                after=current.read_text(encoding="utf-8").splitlines(True)
                changes.extend(difflib.unified_diff(before,after,fromfile="previous/"+entry["path"],tofile=entry["path"]))
            except UnicodeError:
                changes.append("Binary snapshot: "+entry["path"]+"\n")
        (dest/"changes.patch").write_text("".join(changes),encoding="utf-8")
        self.event("source_snapshot", purpose=purpose, directory=str(dest.relative_to(ROOT)), files=entries)
        self.manifest()

    def manifest(self):
        files = []
        for path in sorted(self.path.rglob("*")):
            if path.is_file() and path.name not in ("manifest.json", "manifest.json.tmp"):
                files.append({"path": path.relative_to(ROOT).as_posix(),
                              "bytes": path.stat().st_size, "sha256": sha256(path)})
        write_json(self.path / "manifest.json", files)

    def status(self, stage, status, reason, evidence=(), next_action="", **extra):
        value = {"stage": stage, "status": status, "run_id": self.run_id,
                 "upstream_revision": None, "bitstream_sha256": None, "config_sha256": None,
                 "inputs": [], "outputs": [], "evidence": list(evidence), "reason": reason,
                 "next_action": next_action, "updated": now(), **extra}
        write_json(self.path / "status.json", value)
        write_json(ROOT / "state" / stage / "status.json", value)
        self.event("stage_status", **value)
        self.manifest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("exec", "snapshot"))
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--cwd")
    parser.add_argument("--timeout", type=int, default=180)
    raw = sys.argv[1:]
    if "--" in raw:
        split = raw.index("--")
        argv = raw[split + 1:]
        raw = raw[:split]
    else:
        argv = []
    args = parser.parse_args(raw)
    run = Run("maintenance", args.run_id)
    if args.operation == "snapshot":
        run.snapshot(args.purpose)
    else:
        if not argv:
            parser.error("exec requires -- followed by a command")
        sys.exit(run.command(argv, args.purpose, args.cwd, args.timeout)[0])
