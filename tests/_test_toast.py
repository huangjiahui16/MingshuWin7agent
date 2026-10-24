# -*- coding: utf-8 -*-
"""右下角提醒：位置、场景图标、自动消失/常驻、点击聚焦。"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import tkinter as tk
import win7_assistant as engine
import wb_app

TEST_DIR = os.path.join(ROOT, "tests", "_test_tmp_toast")
os.makedirs(TEST_DIR, exist_ok=True)
wb_app.SESSIONS_DIR = os.path.join(TEST_DIR, "sessions")
wb_app.SESSIONS_META = os.path.join(TEST_DIR, "sessions.json")
wb_app.UI_STATE = os.path.join(TEST_DIR, "ui_state.json")
engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "记忆.md")
engine.API_MD = os.path.join(TEST_DIR, "api.md")
wb_app.DATA_DIR = TEST_DIR

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print("PASS ", name, extra)
    else:
        fail += 1; print("FAIL ", name, extra)

def pump(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.root.update()
        time.sleep(0.01)

app = wb_app.MingShuApp()
app._has_key = lambda: True
app.root.update()
th = app.th

def canvas_items(win):
    for c in win.winfo_children():
        if isinstance(c, tk.Canvas):
            return c
    return None

# ---- 1) 完成类提醒 ----
w1 = app._toast("done", None, "我已经把资料整理好了，共 12 个文件")
pump()
check("完成提醒已创建", w1 is not None and w1.winfo_exists())
cv = canvas_items(w1)
texts = []
fills = []
if cv:
    for it in cv.find_all():
        t = cv.type(it)
        if t == "text":
            texts.append(cv.itemcget(it, "text"))
        elif t == "oval":
            fills.append(cv.itemcget(it, "fill"))
check("完成图标是 ✓", "✓" in texts, texts)
check("完成图标绿色", th["green"] in fills, fills)
g = w1.geometry() if w1 else ""
check("贴在右下角", g.startswith("340x86+") and "+" in g, g)

# ---- 2) 确认类（sticky，不自动消失）----
w2 = app._toast("ask", None, "要写入工作区外的文件，需要你同意", sticky=True)
pump()
cv2 = canvas_items(w2)
t2 = []
f2 = []
if cv2:
    for it in cv2.find_all():
        if cv2.type(it) == "text":
            t2.append(cv2.itemcget(it, "text"))
        elif cv2.type(it) == "oval":
            f2.append(cv2.itemcget(it, "fill"))
check("确认图标是 ?", "?" in t2, t2)
check("确认图标黄色", th["yellow"] in f2, f2)
# 堆叠：两条不重叠
y1 = int(w1.geometry().split("+")[2]) if w1 else 0
y2 = int(w2.geometry().split("+")[2]) if w2 else 0
check("两条提醒上下堆叠不重叠", abs(y1 - y2) >= 86, (y1, y2))
check("最多同时保留的条数<=3", len(app._toasts) <= 3, len(app._toasts))
# 等一会儿确认 sticky 不会自己消失
pump(1.2)
check("确认类提醒不会自动消失", w2.winfo_exists())

# ---- 3) 出错类 ----
w3 = app._toast("error", None, "接口返回 401，请检查 API Key")
pump()
cv3 = canvas_items(w3)
t3 = []
f3 = []
if cv3:
    for it in cv3.find_all():
        if cv3.type(it) == "text":
            t3.append(cv3.itemcget(it, "text"))
        elif cv3.type(it) == "oval":
            f3.append(cv3.itemcget(it, "fill"))
check("出错图标是 !", "!" in t3, t3)
check("出错图标红色", th["red"] in f3, f3)

# ---- 4) 点击提醒会关闭并聚焦 ----
app._toast_focus(w3)
pump()
check("点击后提醒关闭", not w3.winfo_exists())
check("点击后主窗口提到前台", app.root.state() != "iconic")

# ---- 5) 挂起判定 ----
app.root.update()
fore = app._window_inactive()
check("_window_inactive 返回布尔", isinstance(fore, bool), fore)

# ---- 6) 前台不打扰：模拟窗口在前台时 final 不弹 ----
before = len(app._toasts)
app._window_inactive = lambda: False
app.queue.put(("final", ("这是一条很长的完成汇报" * 3, app.gen_id)))
app._pump()
pump(0.2)
check("前台时完成不弹提醒", len(app._toasts) == before, len(app._toasts))

# ---- 7) 挂起时 final 会弹 ----
app._window_inactive = lambda: True
app.queue.put(("final", ("这是一条很长的完成汇报" * 3, app.gen_id)))
app._pump()
pump(0.2)
check("挂起时完成会弹提醒", len(app._toasts) > before, len(app._toasts))

for w in list(app._toasts):
    app._toast_close(w)
app.root.destroy()
print("RESULT: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
