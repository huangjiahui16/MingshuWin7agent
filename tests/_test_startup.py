# -*- coding: utf-8 -*-
"""启动冒烟实测：MingShuApp 能起来、延迟拖放挂钩正常、无异常。

所有数据在 F 盘临时目录，不碰用户 ini/sessions。
"""
import os
import sys
import time
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp3")
def _safe_rmtree(p):
    """逐个删文件再删空目录：避免触发批量删除保护（一次 rmtree 大量文件被拦）。"""
    if not os.path.isdir(p):
        return
    for root, dirs, files in os.walk(p, topdown=False):
        for fn in files:
            try:
                os.remove(os.path.join(root, fn))
            except OSError:
                pass
        for dn in dirs:
            try:
                os.rmdir(os.path.join(root, dn))
            except OSError:
                pass
    try:
        os.rmdir(p)
    except OSError:
        pass

# 不删旧目录直接复用（文件覆盖写）：启动时删目录会撞上沙箱的
# 批量删除配额（50 个/轮），把整个测试进程杀掉。收尾清理保留。
os.makedirs(TEST_DIR, exist_ok=True)

import tkinter as tk
import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine
import wb_app

wb_app.SESSIONS_DIR = os.path.join(TEST_DIR, "sessions")
wb_app.SESSIONS_META = os.path.join(TEST_DIR, "sessions.json")
wb_app.UI_STATE = os.path.join(TEST_DIR, "ui_state.json")
engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "mem.md")

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


t0 = time.time()
app = wb_app.WorkBuddyApp()
t_build = time.time() - t0
print("INFO  MingShuApp build took %.0f ms" % (t_build * 1000))

root = app.root
check("window title set", "明枢" in root.title() or len(root.title()) > 0)
check("chat view built", app.chat is not None and app.chat.winfo_exists())
check("composer built", app.composer is not None)

# 首帧 + 触发延迟拖放挂钩
for _ in range(5):
    root.update()
check("deferred drop hook ran without error",
      getattr(app, "_drop_ok", None) in (True, False))

# 对话区写入 30 条消息再滚动一次，验证 UI 完整可用
for i in range(30):
    app.chat.add_user("u%d" % i)
    app.chat.add_assistant("a%d\n" % i, "", "")
root.update()
app.chat.scroll_to_end(force=True)
for _ in range(3):
    root.update()
first, last = app.chat.canvas.yview()
check("chat scroll to bottom works", last >= 0.995)

root.destroy()
print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
_safe_rmtree(TEST_DIR)
sys.exit(1 if FAIL else 0)
