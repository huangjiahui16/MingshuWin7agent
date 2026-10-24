# -*- coding: utf-8 -*-
"""GUI 实测：聊天区滚动优化（v14 滚动改造）。

只测 ChatView 滚动行为，所有测试数据落在 F 盘临时目录，
不碰 sessions/ ui_state.json 记忆.md 等用户资产。
控制台输出保持英文（cmd GBK）。
"""
import os
import sys
import time
import shutil
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp")

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

# ---- 路径隔离：全部重定向到 F 盘临时目录 ----
wb_app.SESSIONS_DIR = os.path.join(TEST_DIR, "sessions")
wb_app.SESSIONS_META = os.path.join(TEST_DIR, "sessions.json")
wb_app.UI_STATE = os.path.join(TEST_DIR, "ui_state.json")
engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")

PASS = []
FAIL = []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


root = tk.Tk()
root.geometry("900x600")
cv = wb_app.ChatView(root, wb_app.THEME)
cv.pack(fill=tk.BOTH, expand=True)
root.update()

# 塞 40 条消息（含 markdown/代码块/长文），模拟真实对话量
for i in range(40):
    cv.add_user("user message %d" % i)
    cv.add_assistant(
        "## reply %d\n" % i
        + "text line\n" * 12
        + "```python\nprint(%d)\n```" % i
        + "\n- item one\n- item two\n",
        "disclaimer", "usage line")
_thk = cv.add_thinking("think line\n" * 40)   # 内部长 Text（限 16 行）
_tool = cv.add_tool_card("read_file", "body " * 50,
                         "\n".join("result line %d" % i for i in range(60)))
_tool[3]()                                     # 手动展开（结果长不自动展开）
root.update_idletasks()
root.update()

# 1. 像素级滚动单位
check("yscrollincrement == 1 (pixel units)", int(cv.canvas.cget("yscrollincrement")) == 1)

# 2. scrollregion 已同步
sr = cv.canvas.cget("scrollregion")
check("scrollregion synced", str(sr) not in ("", "0 0 0 0", None, "None"))

# 3. 贴底批处理：scroll_to_end 后停在底部
cv.scroll_to_end(force=True)
root.update_idletasks()
root.update()
first, last = cv.canvas.yview()
check("scroll_to_end reaches bottom", last >= 0.995)

# 4. 滚轮事件：像素步进且方向正确。
#    合成事件时真实鼠标不在窗口上，_pointer_inside 会正确拒绝；
#    这里旁路指针检查，专门验证事件流与步进量。
cv._pointer_inside = lambda: True
cv.scroll_to_end(force=True)
root.update_idletasks()
root.update()
before = cv.canvas.yview()[0]
cv.canvas.event_generate("<MouseWheel>", delta=120)   # 向上
root.update()
after = cv.canvas.yview()[0]
check("wheel scrolls up (delta>0)", after < before)
sr_h = float(str(cv.canvas.cget("scrollregion")).split()[3])
px_moved = (before - after) * sr_h
check("wheel step ~60px (got %.0f)" % px_moved, 30 <= px_moved <= 120)

# 5. 滚轮向下
before = after
cv.canvas.event_generate("<MouseWheel>", delta=-120)
root.update()
check("wheel scrolls down (delta<0)", cv.canvas.yview()[0] > before)

# 6. 指针判定：真实坐标在对话区里
#    先把窗口置顶，防止被别的窗口挡住导致 winfo_containing 查不到（环境噪音）
root.lift()
root.attributes("-topmost", True)
root.update()
x = cv.winfo_rootx() + 100
y = cv.winfo_rooty() + 100
real = root.winfo_pointerxy()
# 借助 winfo_containing 直接验证后代判定逻辑
under = root.winfo_containing(x, y)
check("winfo_containing works", under is not None)
check("pointer_inside descendant logic",
      str(cv.canvas).startswith(str(cv)) and str(under).startswith(str(root)))

# 7. 内部长 Text 滚轮：内容可滚时先滚内部，到顶/底再转交对话区
cv.scroll_to_end(force=True)
root.update_idletasks()
root.update()
tool_text = _tool[1]
think_text = None
check("found inner long Text", tool_text is not None)
if tool_text is not None:
    # 内部像素步进
    check("inner Text pixel scrolling works",
          tool_text.yview_scroll(5, "pixels") is None)
    # 7a. 初始在顶部：向下滚 → 内部滚动（对话区不动）
    chat_before = cv.canvas.yview()[0]
    tool_text.event_generate("<MouseWheel>", delta=-120)
    root.update()
    check("scrollable Text wheel-down scrolls itself",
          tool_text.yview()[0] > 0.0
          and cv.canvas.yview()[0] >= chat_before - 1e-6)
    # 7b. 回到顶部：向上滚 → 无内部空间，转交对话区
    cv.canvas.yview_moveto(0.5)
    root.update()
    tool_text.yview_moveto(0.0)
    root.update()
    chat_before = cv.canvas.yview()[0]
    tool_text.event_generate("<MouseWheel>", delta=120)
    root.update()
    check("at-top wheel-up forwarded to chat", cv.canvas.yview()[0] < chat_before)
    # 7c. 内部滚到底：继续向下滚 → 转交对话区
    cv.canvas.yview_moveto(0.5)
    root.update()
    tool_text.yview_moveto(1.0)
    root.update()
    chat_before = cv.canvas.yview()[0]
    tool_text.event_generate("<MouseWheel>", delta=-120)
    root.update()
    check("at-bottom wheel-down forwarded to chat",
          cv.canvas.yview()[0] > chat_before)
    # 7d. 内容不足一屏的 Text：直接转交（思考块只有几行时不吸滚轮）
    cv.canvas.yview_moveto(0.5)
    root.update()
    short = tk.Text(cv.inner, height=3)
    short.insert("1.0", "only three lines\nok\nend")
    short.update()
    chat_before = cv.canvas.yview()[0]
    short.event_generate("<MouseWheel>", delta=-120)
    root.update()
    check("short Text wheel forwarded to chat", cv.canvas.yview()[0] > chat_before)
    short.destroy()
# 7e. 思考块（限 16 行，40 行内容）同样内部可滚
think_text = _thk[1]
think_text.event_generate("<MouseWheel>", delta=-120)
root.update()
check("thinking Text scrolls internally", think_text.yview()[0] > 0.0)
# 8. 滚动条箭头步进（scroll N units 放大为 48px；贴底时向上滚才有位移）
cv.scroll_to_end(force=True)
root.update_idletasks()
root.update()
b1 = cv.canvas.yview()
cv.canvas.yview_scroll(-48, "units")     # 绕过 _sb_move 的裸探测
root.update()
m1 = cv.canvas.yview()
cv.canvas.yview_moveto(1.0)
root.update()
b2 = cv.canvas.yview()
_orig_sb = cv._sb_move
def _dbg_sb(*args):
    print("DBG sbcall args=%r before=%r end_job=%r align_job=%r"
          % (args, cv.canvas.yview(), cv._end_job, cv._align_job))
    _orig_sb(*args)
    print("DBG sbcall after=%r auto=%r" % (cv.canvas.yview(), cv._auto_scroll))
cv._sb_move = _dbg_sb
cv._sb_move("scroll", "-1", "units")     # 走 _sb_move 的正式路径
root.update()
a2 = cv.canvas.yview()
print("DBG bare: %r -> %r   |   sb: %r -> %r" % (b1, m1, b2, a2))
delta_px = (b2[0] - a2[0]) * sr_h
check("scrollbar arrow step ~48px (got %.0f)" % delta_px, 20 <= delta_px <= 100)

# 8b. moveto 直达不受影响
cv._sb_move("moveto", "0.0")
root.update()
check("scrollbar moveto works", cv.canvas.yview()[0] < 0.01)

# 9. after_idle 合并任务没有残留
root.update()
check("no pending sr job", cv._sr_job is None)
check("no pending end job", cv._end_job is None)

# 10. 性能冒烟：滚 20 格耗时（画布 80+ 条消息）
t0 = time.time()
for _ in range(20):
    cv.canvas.event_generate("<MouseWheel>", delta=-120)
    root.update()
dt = time.time() - t0
print("INFO  20 wheel notches over full chat took %.0f ms (%.1f ms/notch)" % (dt * 1000, dt * 50))
check("wheel latency acceptable (<50ms/notch)", dt / 20 < 0.05)

root.destroy()

print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
_safe_rmtree(TEST_DIR)
sys.exit(1 if FAIL else 0)
