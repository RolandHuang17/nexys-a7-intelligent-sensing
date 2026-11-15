"""Read-only enumeration using Digilent's archived dmgr.h / dpcdecl.h ABI."""
import ctypes as c
import json
import sys


class DVC(c.Structure):
    _pack_ = 16
    _fields_ = [("name", c.c_char * 64), ("connection", c.c_char * 261), ("dtp", c.c_uint32)]


def probe():
    dll = c.CDLL(r"C:\Windows\System32\dmgr.dll")
    dll.DmgrGetVersion.argtypes = [c.c_void_p]
    dll.DmgrGetVersion.restype = c.c_int
    dll.DmgrEnumDevices.argtypes = [c.POINTER(c.c_int)]
    dll.DmgrEnumDevices.restype = c.c_int
    dll.DmgrGetDvc.argtypes = [c.c_int, c.POINTER(DVC)]
    dll.DmgrGetDvc.restype = c.c_int
    dll.DmgrGetInfo.argtypes = [c.POINTER(DVC), c.c_uint32, c.c_void_p]
    dll.DmgrGetInfo.restype = c.c_int
    dll.DmgrGetLastError.restype = c.c_int
    dll.DmgrFreeDvcEnum.restype = c.c_int
    version = c.create_string_buffer(256)
    version_ok = dll.DmgrGetVersion(version)
    count = c.c_int()
    enum_ok = dll.DmgrEnumDevices(c.byref(count))
    result = {"library": dll._name, "version_ok": version_ok,
              "version": version.value.decode(errors="replace"), "enum_ok": enum_ok,
              "count": count.value, "error": dll.DmgrGetLastError(), "dvc_size": c.sizeof(DVC), "devices": []}
    try:
        for index in range(count.value if enum_ok else 0):
            dvc = DVC()
            ok = dll.DmgrGetDvc(index, c.byref(dvc))
            entry = {"ok": ok, "name": dvc.name.decode(errors="replace"),
                     "connection": dvc.connection.decode(errors="replace"), "transport": dvc.dtp}
            if ok:
                for key, code in (("product", 3), ("serial", 5), ("usb_path", 12)):
                    value = c.create_string_buffer(1024)
                    info_ok = dll.DmgrGetInfo(c.byref(dvc), code, value)
                    entry[key] = value.value.decode(errors="replace") if info_ok else None
                cap = c.c_uint32()
                entry["cap_ok"] = dll.DmgrGetInfo(c.byref(dvc), 9, c.byref(cap))
                entry["capabilities"] = cap.value
            result["devices"].append(entry)
    finally:
        dll.DmgrFreeDvcEnum()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if enum_ok else 2


if __name__ == "__main__":
    sys.exit(probe())
