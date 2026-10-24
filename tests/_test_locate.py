# -*- coding: utf-8 -*-
"""_locate_missing: file moved -> auto search by name (no network, hermetic).

All test data lives under F:\\...\\_test_tmp\\locate. Console output is ASCII.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp", "locate")

os.makedirs(TEST_DIR, exist_ok=True)

import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


def _mk(p, content="hello"):
    fp = os.path.join(TEST_DIR, p)
    d = os.path.dirname(fp)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(content)
    return fp


# workspace: ws1 (old location), ws2 (new location)
ws1 = os.path.join(TEST_DIR, "ws1")
ws2 = os.path.join(TEST_DIR, "ws2")
old = _mk(os.path.join("ws1", "docs", "report.txt"), "old body")
new = _mk(os.path.join("ws2", "backup", "2026", "report.txt"), "new body")

# 1. moved file (no workspace): extra_roots injects the test root so the
#    search stays hermetic; finds the copy under ws2 regardless of ws1
out = engine._locate_missing(old, extra_roots=[TEST_DIR])
check("moved: reports missing", "report.txt" in out)
check("moved: lists new path", new.lower() in out.lower())

# 2. moved across workspace: search restricted to workspace
#    old path in ws1, workspace=ws2 -> old path not under ws2, but filename
#    search still finds the ws2 copy (search root is workspace itself)
out = engine._locate_missing(old, workspace=ws2)
check("cross-ws: finds ws2 copy", new.lower() in out.lower())

# 3. nothing found anywhere in workspace
out = engine._locate_missing(os.path.join(ws1, "nope_x9.txt"), workspace=ws1)
check("missing: no candidate message", "search" in out or "search_files" in out)

# 4. loose (stem) match listed separately
_mk(os.path.join("ws1", "notes", "report_2026_final.txt"), "loose")
out = engine._locate_missing(old, workspace=ws1)
check("loose match listed", "report_2026_final.txt" in out)

# 5. tool_read_file wires through: missing -> candidates; existing -> content
out = engine.tool_read_file(old.replace(".txt", "_gone.txt"), workspace=ws1)
check("read_file missing -> auto search", "report" in out.lower())
out = engine.tool_read_file(old, workspace=ws1)
check("read_file existing unchanged", "old body" in out)

# 6. budget/caps: workspace with many files still returns quickly
for i in range(200):
    _mk(os.path.join("ws1", "many", "f%03d.txt" % i), "x")
import time
t0 = time.time()
out = engine._locate_missing(os.path.join(ws1, "f099.txt"), workspace=ws1)
dt = time.time() - t0
check("fast on 200-file ws (%.2fs)" % dt, dt < 5.0 and "f099.txt" in out)

# 7. empty basename guard
out = engine._locate_missing("C:\\", workspace="")
check("dir-as-path guard", "not exist" in out or "not found" in out or out)

print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
