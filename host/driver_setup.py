"""Run the unchanged signed FTDI installer only after a deliberate UI action."""
import ctypes
from ctypes import wintypes as w
from app_paths import RESOURCE_ROOT
from audit import sha256

def install(run):
    from portable_program import release
    release() # Includes the pinned hash of the signed original installer.
    path=RESOURCE_ROOT/'driver/CDM2123620_Setup.exe'
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_=[('cbSize',w.DWORD),('fMask',w.ULONG),('hwnd',w.HWND),('lpVerb',w.LPCWSTR),
            ('lpFile',w.LPCWSTR),('lpParameters',w.LPCWSTR),('lpDirectory',w.LPCWSTR),('nShow',ctypes.c_int),
            ('hInstApp',w.HINSTANCE),('lpIDList',ctypes.c_void_p),('lpClass',w.LPCWSTR),('hkeyClass',w.HKEY),
            ('dwHotKey',w.DWORD),('hIcon',w.HANDLE),('hProcess',w.HANDLE)]
    info=SHELLEXECUTEINFO();info.cbSize=ctypes.sizeof(info);info.fMask=0x40|0x100
    info.lpVerb='runas';info.lpFile=str(path);info.nShow=1
    shell=ctypes.WinDLL('shell32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    shell.ShellExecuteExW.argtypes=[ctypes.POINTER(SHELLEXECUTEINFO)];shell.ShellExecuteExW.restype=w.BOOL
    run.event('official_driver_setup_requested',file_sha256=sha256(path),elevation='only installer')
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code=ctypes.get_last_error();run.event('driver_setup_not_started',windows_error=code)
        if code==1223:return '已取消驱动安装；监测软件仍可使用现有驱动。'
        raise ctypes.WinError(code)
    kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
    kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    try:
        kernel.WaitForSingleObject(info.hProcess,0xffffffff);code=w.DWORD()
        kernel.GetExitCodeProcess(info.hProcess,ctypes.byref(code));run.event('official_driver_setup_exited',exit_code=code.value)
        return f'驱动安装窗口已结束（退出码 {code.value}）。请点刷新；如提示重启，保存数据后按安装器提示操作。'
    finally:kernel.CloseHandle(info.hProcess)
