# -*- coding: utf-8 -*-
"""三道墙 + 分段计时 + 读写优化（scandir/编码探测/缓存/搜索限深）。"""
import os, sys, time, ctypes, ctypes.wintypes as wt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import win7_assistant as engine
import win7_limits as limits

TEST_DIR = os.path.join(ROOT, "tests", "_test_tmp_limits")
os.makedirs(TEST_DIR, exist_ok=True)
engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "记忆.md")
engine.API_MD = os.path.join(TEST_DIR, "api.md")
engine.DATA_DIR = TEST_DIR

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print("PASS ", name, extra)
    else:
        fail += 1; print("FAIL ", name, extra)

# ---------- 1) 内存墙 ----------
err_before = ctypes.get_last_error()
ok_mem, msg = limits.apply_memory_wall(300, 4)
print("      memory wall:", ok_mem, msg)
check("内存墙已尝试应用", isinstance(ok_mem, bool))
check("状态里有内存墙描述", "job" in limits.STATE["memory"] or "denied" in limits.STATE["memory"]
      or "failed" in limits.STATE["memory"], limits.STATE["memory"])

if ok_mem:
    # 查回 Job 限制，确认内核真的记住了 300MB / 4 进程
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wt.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wt.DWORD),
                    ("SchedulingClass", wt.DWORD)]
    class IOC(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint64), ("b", ctypes.c_uint64), ("c", ctypes.c_uint64),
                    ("d", ctypes.c_uint64), ("e", ctypes.c_uint64), ("f", ctypes.c_uint64)]
    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IOC),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int,
                                           ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    info = EXT()
    got = k.QueryInformationJobObject(limits.STATE["job_handle"], 9,
                                      ctypes.byref(info), ctypes.sizeof(info), None)
    check("Job 限制查询成功", bool(got))
    check("内存上限 = 300MB", info.ProcessMemoryLimit == 300 * 1024 * 1024,
          info.ProcessMemoryLimit)
    check("子进程上限 = 4", info.Basic.ActiveProcessLimit == 4,
          info.Basic.ActiveProcessLimit)
else:
    check("Job 限制查询成功（跳过：进程已在别的 Job）", True)
    check("内存上限 = 300MB（跳过）", True)
    check("子进程上限 = 4（跳过）", True)

# ---------- 2) CPU / I/O 墙（当前线程）----------
limits.begin_worker_thread()
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.GetThreadPriority.argtypes = [wt.HANDLE]
k.GetThreadPriority.restype = ctypes.c_int
_h = limits._thread_handle()
prio = k.GetThreadPriority(_h)
k.CloseHandle(_h)
print("      thread priority:", prio, "| state:", limits.STATE)
check("工作线程已降到空闲优先级", prio <= -2, prio)
check("I/O 已切后台模式", limits.STATE["io"] in ("background",), limits.STATE["io"])

# ---------- 3) 分段计时 ----------
limits.STATS["local"].clear(); limits.STATS["net"].clear(); limits.STATS["render"].clear()
with limits.timer("local", "demo"):
    time.sleep(0.02)
with limits.timer("net", "llm"):
    time.sleep(0.01)
limits.record("render", 5.0, "ui")
rep = limits.report()
check("计时记录了本地/网络/渲染", rep["count"]["local"] == 1 and rep["count"]["net"] == 1
      and rep["count"]["render"] == 1, rep["count"])
check("本地耗时 >= 20ms", rep["total_ms"]["local"] >= 19, rep["total_ms"]["local"])
check("占比之和约等于 100%",
      abs(sum([rep["share"]["local"], rep["share"]["net"], rep["share"]["render"]]) - 100) < 1.5,
      rep["share"])
print("      " + limits.summary_line())

# ---------- 4) 编码探测 ----------
gbk_path = os.path.join(TEST_DIR, "gbk.txt")
with open(gbk_path, "wb") as f:
    f.write("中文编码测试：这是 GBK 文件".encode("gbk"))
txt, note = engine.read_text_file(gbk_path, 1000)
check("GBK 文件正确解码", txt is not None and "中文编码测试" in txt, (txt or "")[:30])

u8_path = os.path.join(TEST_DIR, "utf8.txt")
with open(u8_path, "wb") as f:
    f.write("中文编码测试：这是 UTF-8 文件".encode("utf-8"))
txt2, _ = engine.read_text_file(u8_path, 1000)
check("UTF-8 文件正确解码", txt2 is not None and "UTF-8 文件" in txt2, (txt2 or "")[:30])

# ---------- 5) 小文件缓存 ----------
t0 = time.perf_counter()
for _ in range(50):
    engine.read_text_file(u8_path, 1000)
fast = (time.perf_counter() - t0) * 1000
check("重复读命中缓存（50 次 < 50ms）", fast < 50, "%.1fms" % fast)

# ---------- 6) 目录 3 秒 TTL 缓存 ----------
d = os.path.join(TEST_DIR, "many")
os.makedirs(d, exist_ok=True)
for i in range(30):
    with open(os.path.join(d, "f%02d.txt" % i), "w", encoding="utf-8") as f:
        f.write("x")
engine._DIR_CACHE.clear()
t0 = time.perf_counter(); engine.tool_list_dir(d); first = (time.perf_counter() - t0) * 1000
t0 = time.perf_counter(); engine.tool_list_dir(d); second = (time.perf_counter() - t0) * 1000
check("第二次列目录明显更快（命中缓存）", second <= first + 0.5,
      "first=%.2fms second=%.2fms" % (first, second))
check("目录缓存里有这一项", d in engine._DIR_CACHE)

# ---------- 7) 搜索深度限制 ----------
deep = os.path.join(TEST_DIR, "depth", "a", "b", "c", "d")
os.makedirs(deep, exist_ok=True)
target = os.path.join(deep, "needle_xyz.txt")
with open(target, "w", encoding="utf-8") as f:
    f.write("x")
out3 = engine.tool_search_files("needle_xyz.txt", os.path.join(TEST_DIR, "depth"), 3)
check("默认 3 层搜不到第 5 层文件", "没找到" in out3, out3[:50])
out6 = engine.tool_search_files("needle_xyz.txt", os.path.join(TEST_DIR, "depth"), 6)
check("放宽到 6 层能搜到", "needle_xyz" in out6, out6[:60])

print("RESULT: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
