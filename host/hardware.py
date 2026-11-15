"""Vivado hardware session with explicit port and auditable service lifecycle."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import time
import msvcrt

from audit import ROOT, sha256

VIVADO = Path(os.environ.get('RECORDER_VIVADO',r"D:\LearingTools\2026.1\Vivado\bin\vivado.bat"))
_bundled_openocd=ROOT/'upstream/tools/openocd/bin/openocd.exe'
OPENOCD = Path(os.environ.get('RECORDER_OPENOCD',str(_bundled_openocd) if _bundled_openocd.exists() else
               r"C:\Users\roland\.platformio\packages\tool-openocd-riscv-chipsalliance\bin\openocd.exe"))


@contextmanager
def hardware_lock(run):
    path = ROOT / "state" / "hardware.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if path.stat().st_size == 0:
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        run.event("hardware_lock_acquired", pid=os.getpid())
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            run.event("hardware_lock_released", pid=os.getpid())


def openocd(run, commands, purpose, timeout=90):
    with hardware_lock(run):
        return run.command([OPENOCD, "-f", ROOT / "scripts/jtag_winusb.cfg", "-c", commands],
                           purpose, cwd=run.path, timeout=timeout)


@contextmanager
def hardware_server(run):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    argv = [os.environ["COMSPEC"], "/d", "/c", str(VIVADO.with_name("hw_server.bat")),
            f"-stcp:127.0.0.1:{port}", "-p0", "-I120", "-L-", "-l0x4000"]
    path = run.path / "hw_server.log"
    with path.open("wb") as log:
        server = subprocess.Popen(argv, cwd=run.path, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        run.event("service_started", argv=argv, pid=server.pid, port=port,
                  output=path.relative_to(ROOT).as_posix())
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("hw_server exited: " + path.read_text(errors="replace"))
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("hw_server did not listen within 10 seconds")
            yield f"localhost:{port}"
        finally:
            stop = subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
            server.wait(timeout=15)
            log.flush()
            run.event("service_stopped", pid=server.pid, returncode=server.returncode,
                      cleanup_returncode=stop.returncode, log_sha256=sha256(path))


def vivado(run, script, args=(), purpose="Vivado batch", timeout=180):
    return run.command([os.environ["COMSPEC"], "/d", "/c", VIVADO,
                        "-mode", "batch", "-nolog", "-nojournal", "-notrace",
                        "-source", ROOT / "scripts" / script, "-tclargs", *args],
                       purpose, cwd=run.path, timeout=timeout)
