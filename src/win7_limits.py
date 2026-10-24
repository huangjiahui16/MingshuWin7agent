# -*- coding: utf-8 -*-
"""三道资源墙 + 分段计时（Win7 SP1 原生，纯标准库 ctypes）。

墙的意义：限制由 Windows 内核执行，不依赖本程序的自觉。
  内存墙  Job Object：ProcessMemoryLimit + ActiveProcessLimit，
          超限由内核 TerminateJobObject，用户的 Word / 浏览器毫发无伤。
  CPU 墙  线程空闲优先级（THREAD_PRIORITY_IDLE）：用户一碰键鼠就把我们
          挤到最后，跑完跟没跑一样。可选进程级 IDLE（cpu_wall = process）。
  I/O 墙  THREAD_MODE_BACKGROUND_BEGIN：磁盘 I/O 让位给前台程序，
          机械硬盘上这一条比什么都管用。

注意：不用 CPU 亲和性绑核——老机器多是单核/HT 双核，绑核反而和用户程序
挤进同一个物理核。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import statistics
import threading
import time

IS_WIN = (os.name == "nt")


# ------------------------------------------------------------------ 常量
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
THREAD_MODE_BACKGROUND_END = 0x00020000
THREAD_PRIORITY_IDLE = -15
THREAD_PRIORITY_LOWEST = -2


# ------------------------------------------------------------------ 结构体
class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


STATE = {"memory": "not applied", "cpu": "not applied", "io": "not applied",
         "job_handle": None}


def _k32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


# ------------------------------------------------------------------ 内存墙
def apply_memory_wall(limit_mb=300, max_procs=4):
    """把本进程放进 Job Object：内存超限或子进程超限，内核直接杀掉。

    返回 (ok, 说明)。失败不致命（例如本进程已经在别的 Job 里，
    AssignProcessToJobObject 会报拒绝访问），调用方记录状态即可。
    """
    if not IS_WIN:
        STATE["memory"] = "skipped (not windows)"
        return False, STATE["memory"]
    try:
        k = _k32()
        k.CreateJobObjectW.restype = wt.HANDLE
        k.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int,
                                             wt.LPVOID, wt.DWORD]
        k.SetInformationJobObject.restype = wt.BOOL
        k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        k.AssignProcessToJobObject.restype = wt.BOOL
        k.GetCurrentProcess.restype = wt.HANDLE

        job = k.CreateJobObjectW(None, None)
        if not job:
            STATE["memory"] = "CreateJobObject failed (%d)" % ctypes.get_last_error()
            return False, STATE["memory"]

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = (JOB_OBJECT_LIMIT_PROCESS_MEMORY
                 | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                 | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        info.BasicLimitInformation.LimitFlags = flags
        info.BasicLimitInformation.ActiveProcessLimit = int(max(1, max_procs))
        info.ProcessMemoryLimit = ctypes.c_size_t(int(max(64, limit_mb)) * 1024 * 1024)
        ok = k.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                      ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            STATE["memory"] = "SetInformationJobObject failed (%d)" % ctypes.get_last_error()
            return False, STATE["memory"]

        ok2 = k.AssignProcessToJobObject(job, k.GetCurrentProcess())
        if not ok2:
            # 已经在别的 Job 里（比如被某些启动器托管）：记录但不抛错
            STATE["memory"] = "assign denied (%d) — 进程已在别的 Job" % ctypes.get_last_error()
            return False, STATE["memory"]

        STATE["job_handle"] = job
        STATE["memory"] = "job: %dMB / max %d procs" % (limit_mb, max_procs)
        return True, STATE["memory"]
    except Exception as e:
        STATE["memory"] = "error: %r" % (e,)
        return False, STATE["memory"]


# ------------------------------------------------------------------ CPU / I/O 墙
def _thread_handle():
    """取当前线程的真实句柄。
    不能用 GetCurrentThread() 的伪句柄（-2）：ctypes 传参时会溢出报
    OverflowError，SetThreadPriority 直接失败——必须 OpenThread 拿真句柄。"""
    k = _k32()
    k.GetCurrentThreadId.restype = wt.DWORD
    k.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.OpenThread.restype = wt.HANDLE
    tid = k.GetCurrentThreadId()
    THREAD_SET_INFORMATION = 0x0020
    THREAD_QUERY_INFORMATION = 0x0040
    return k.OpenThread(THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, False, tid)


def begin_worker_thread(io_background=True, cpu_idle=True):
    """工作线程入口调用一次：切到后台 I/O + 空闲优先级。

    只作用于当前线程，窗口/事件循环所在的主线程保持正常优先级，
    否则用户点按钮都要排在 CPU 墙后面，界面会发涩。
    """
    if not IS_WIN:
        STATE["cpu"] = STATE["io"] = "skipped (not windows)"
        return
    try:
        k = _k32()
        k.SetThreadPriority.argtypes = [wt.HANDLE, ctypes.c_int]
        k.SetThreadPriority.restype = wt.BOOL
        h = _thread_handle()
        if not h:
            STATE["cpu"] = "OpenThread failed(%d)" % ctypes.get_last_error()
            return
        try:
            if io_background:
                ok = k.SetThreadPriority(h, THREAD_MODE_BACKGROUND_BEGIN)
                STATE["io"] = "background" if ok else "failed(%d)" % ctypes.get_last_error()
            if cpu_idle:
                ok = k.SetThreadPriority(h, THREAD_PRIORITY_IDLE)
                STATE["cpu"] = "idle" if ok else "failed(%d)" % ctypes.get_last_error()
        finally:
            k.CloseHandle(h)
    except Exception as e:
        STATE["cpu"] = STATE["io"] = "error: %r" % (e,)


def end_worker_thread():
    """线程退出前恢复（不是必须，但便于长生命周期线程复用）。"""
    if not IS_WIN:
        return
    try:
        k = _k32()
        k.SetThreadPriority.argtypes = [wt.HANDLE, ctypes.c_int]
        h = _thread_handle()
        if h:
            k.SetThreadPriority(h, THREAD_MODE_BACKGROUND_END)
            k.CloseHandle(h)
    except Exception:
        pass


def apply_process_priority(level="below"):
    """进程级优先级。level: below / idle / normal。"""
    if not IS_WIN:
        return "skipped"
    try:
        k = _k32()
        k.GetCurrentProcess.restype = wt.HANDLE
        val = {"below": BELOW_NORMAL_PRIORITY_CLASS,
               "idle": IDLE_PRIORITY_CLASS,
               "normal": 0x00000020}.get(level, BELOW_NORMAL_PRIORITY_CLASS)
        ok = k.SetPriorityClass(k.GetCurrentProcess(), val)
        return "ok" if ok else "failed(%d)" % ctypes.get_last_error()
    except Exception as e:
        return "error: %r" % (e,)


# ------------------------------------------------------------------ 分段计时
_LOCK = threading.Lock()
STATS = {"local": [], "net": [], "render": []}
_PERF_PATH = [""]      # 由 engine 注入 data/perf.jsonl
_MAX_KEEP = 400


def set_perf_path(path):
    _PERF_PATH[0] = path or ""


def record(kind, ms, extra=None):
    """记一次耗时（毫秒）。kind: local(本地执行) / net(模型网络) / render(界面渲染)。"""
    try:
        ms = float(ms)
    except Exception:
        return
    with _LOCK:
        arr = STATS.setdefault(kind, [])
        arr.append(ms)
        if len(arr) > _MAX_KEEP:
            del arr[:len(arr) - _MAX_KEEP]
    p = _PERF_PATH[0]
    if p:
        try:
            row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
                   "ms": round(ms, 1)}
            if extra:
                row["x"] = str(extra)[:80]
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass


class timer(object):
    """with limits.timer("local", "read_file"): ..."""

    def __init__(self, kind, extra=None):
        self.kind = kind
        self.extra = extra

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        record(self.kind, (time.perf_counter() - self.t0) * 1000.0, self.extra)
        return False


def report():
    """返回三段统计：次数 / 平均 / 中位 / 总耗时 / 占比。"""
    out = {"count": {}, "avg_ms": {}, "median_ms": {}, "total_ms": {},
           "share": {}}
    total = 0.0
    with _LOCK:
        snap = {k: list(v) for k, v in STATS.items()}
    for k in ("local", "net", "render"):
        arr = snap.get(k) or []
        out["count"][k] = len(arr)
        out["total_ms"][k] = round(sum(arr), 1)
        out["avg_ms"][k] = round(statistics.mean(arr), 1) if arr else 0.0
        out["median_ms"][k] = round(statistics.median(arr), 1) if arr else 0.0
        total += sum(arr)
    for k in ("local", "net", "render"):
        out["share"][k] = round(out["total_ms"][k] / total * 100.0, 1) if total else 0.0
    out["total_ms"]["all"] = round(total, 1)
    out["state"] = dict(STATE)
    return out


def summary_line():
    r = report()
    if not r["total_ms"].get("all"):
        return "还没有计时数据。"
    return ("本地执行 %.0f%%（%d 次，均 %.0fms）｜模型网络 %.0f%%（%d 次，均 %.0fms）"
            "｜界面渲染 %.0f%%（%d 次，均 %.0fms）" % (
                r["share"]["local"], r["count"]["local"], r["avg_ms"]["local"],
                r["share"]["net"], r["count"]["net"], r["avg_ms"]["net"],
                r["share"]["render"], r["count"]["render"], r["avg_ms"]["render"]))
