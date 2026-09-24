"""Windows: background processes started without a window get "power throttling" (EcoQoS) - they are kept on the
efficiency cores at low clock. Measured on SHEF's PC (i5-14490F): 14 tile jobs used 3.3 cores in total; after opting
them out 9.7 cores. This module opts processes out of execution-speed throttling.

  unthrottle(pid)          one process (e.g. a subprocess.Popen child: unthrottle(p.pid))
  unthrottle_self()        the calling process
  python unthrottle.py     watchdog: every 10 s opts out every python.exe / blender.exe, stops after BISHKEK_UNTHROTTLE_H hours (4)
"""
import os, sys, time, ctypes

_OK = os.name == "nt"
if _OK:
    from ctypes import wintypes
    _k = ctypes.windll.kernel32
    _k.OpenProcess.restype = wintypes.HANDLE
    _k.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

    class _PPT(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    class _PE32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]


def unthrottle(pid):
    if not _OK:
        return False
    h = _k.OpenProcess(0x0200 | 0x1000, False, int(pid))    # PROCESS_SET_INFORMATION | QUERY_LIMITED_INFORMATION
    if not h:
        return False
    s = _PPT(1, 1, 0)                                       # version 1, control EXECUTION_SPEED, state 0 = not throttled
    r = _k.SetProcessInformation(h, 4, ctypes.byref(s), ctypes.sizeof(s))   # 4 = ProcessPowerThrottling
    _k.CloseHandle(h)
    return bool(r)


def unthrottle_self():
    return unthrottle(os.getpid())


def _procs(names=("python.exe", "blender.exe")):
    snap = _k.CreateToolhelp32Snapshot(0x2, 0)
    pe = _PE32(); pe.dwSize = ctypes.sizeof(_PE32)
    out = []
    ok = _k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.lower() in names:
            out.append(pe.th32ProcessID)
        ok = _k.Process32NextW(snap, ctypes.byref(pe))
    _k.CloseHandle(snap)
    return out


def watch():
    done = set()
    t_end = time.time() + 3600 * float(os.environ.get("BISHKEK_UNTHROTTLE_H", "4"))
    while time.time() < t_end:
        for pid in _procs():
            if pid not in done and unthrottle(pid):
                done.add(pid)
        time.sleep(10)


if __name__ == "__main__":
    watch()
