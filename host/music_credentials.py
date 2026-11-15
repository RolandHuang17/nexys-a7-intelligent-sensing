"""Windows Credential Manager storage. Secrets never enter audit events or CLI."""
import ctypes,json,os
from ctypes import wintypes as w
from pathlib import Path

TARGET='NexysMonitor/AudioTag/free-api'
class CREDENTIAL(ctypes.Structure):
    _fields_=[('Flags',w.DWORD),('Type',w.DWORD),('TargetName',w.LPWSTR),('Comment',w.LPWSTR),
              ('LastWritten',w.FILETIME),('CredentialBlobSize',w.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),
              ('Persist',w.DWORD),('AttributeCount',w.DWORD),('Attributes',ctypes.c_void_p),('TargetAlias',w.LPWSTR),('UserName',w.LPWSTR)]
def _api():
    a=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
    a.CredWriteW.argtypes=[ctypes.POINTER(CREDENTIAL),w.DWORD];a.CredWriteW.restype=w.BOOL
    a.CredReadW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.POINTER(CREDENTIAL))];a.CredReadW.restype=w.BOOL
    a.CredFree.argtypes=[ctypes.c_void_p]
    return a
def save_key(value):
    value=value.strip()
    if not 16<=len(value)<=256 or not value.isascii() or any(ch.isspace() for ch in value):
        raise ValueError('密钥格式不正确，请重新粘贴；密钥不会显示在错误信息中')
    blob=value.encode('utf8');buf=(ctypes.c_ubyte*len(blob)).from_buffer_copy(blob)
    c=CREDENTIAL();c.Type=1;c.TargetName=TARGET;c.CredentialBlobSize=len(blob);c.CredentialBlob=buf;c.Persist=2;c.UserName='local-user'
    if not _api().CredWriteW(ctypes.byref(c),0):raise OSError('Windows凭据管理器保存失败')
def load_key():
    out=ctypes.POINTER(CREDENTIAL)();a=_api()
    if not a.CredReadW(TARGET,1,0,ctypes.byref(out)):return None
    try:return ctypes.string_at(out.contents.CredentialBlob,out.contents.CredentialBlobSize).decode('utf8')
    finally:a.CredFree(out)
def configured():return bool(load_key())
def open_config(parent=None):
    import tkinter as tk
    from tkinter import ttk,messagebox
    from audit import ROOT,now,write_json
    win=tk.Toplevel(parent) if parent else tk.Tk();win.title('AudioTag 免费账号 · 本机配置');win.geometry('620x290');win.resizable(False,False)
    frame=ttk.Frame(win,padding=20);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='密钥只保存在当前Windows用户的凭据管理器',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=(0,12))
    ttk.Label(frame,text='请本人粘贴 API Key。此窗口不截图，不记录输入内容。').pack(anchor='w')
    entry=ttk.Entry(frame,show='●',width=66);entry.pack(fill='x',pady=10);entry.focus_set()
    confirmed=tk.BooleanVar(value=False)
    ttk.Checkbutton(frame,text='我确认此账号未充值、没有付费余额及扣款方式或订阅',variable=confirmed).pack(anchor='w',pady=6)
    status=tk.StringVar(value='保存后仍需查询实际免费秒数；此窗口不上传录音。')
    ttk.Label(frame,textvariable=status,wraplength=560).pack(anchor='w',pady=6)
    def save():
        if not confirmed.get():status.set('请先核对并确认纯免费账户状态。');return
        try:
            save_key(entry.get());entry.delete(0,'end')
            record={'time':now(),'free_only_confirmed_by_user':True,
                'storage':'Windows Credential Manager','api_stat_verified':False,'budget_yuan':0}
            write_json(ROOT/'state/music_account_attestation.json',record)
            user_state=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'NexysMonitor/state/music_account_attestation.json'
            if user_state!=ROOT/'state/music_account_attestation.json':write_json(user_state,record)
            status.set('已安全保存。本机设置已完成，后续只按真实免费秒数允许请求。')
            ttk.Button(frame,text='完成并关闭',command=win.destroy).pack(pady=5)
        except Exception:status.set('未能安全保存，请检查密钥输入或Windows凭据管理器。')
    ttk.Button(frame,text='保存到本机',command=save).pack(pady=5)
    if parent:win.transient(parent)
    else:win.mainloop()
    return win
if __name__=='__main__':open_config()
