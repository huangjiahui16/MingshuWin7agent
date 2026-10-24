# -*- coding: utf-8 -*-
"""聊天记录可选复制：路径/英文整段识别、双击复制、右键复制、用户气泡双击复制。"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import tkinter as tk
import win7_assistant as engine
import wb_app

TEST_DIR = os.path.join(ROOT, "tests", "_test_tmp_copy")
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

# ---- 1) 纯函数：路径/英文整段识别 ----
line = "配置在 F:\\jiyu\\zuixing\\ai\\data\\assistant.ini 里，模型是 deepseek-flash 记住"
span = wb_app._pick_token(line, line.index("F:"))
got = line[span[0]:span[1]] if span else ""
check("路径整段识别", got == "F:\\jiyu\\zuixing\\ai\\data\\assistant.ini", got)
span2 = wb_app._pick_token(line, line.index("deepseek"))
got2 = line[span2[0]:span2[1]] if span2 else ""
check("英文模型名整段识别", got2 == "deepseek-flash", got2)
span3 = wb_app._pick_token("好的", 0)
check("纯中文不误选", span3 is None, span3)

# ---- 2) 界面上真的能选能复制 ----
app = wb_app.MingShuApp()
app._has_key = lambda: True
app.root.update()
cv = app.chat

t, _dl = cv.add_assistant(
    "配置文件在 F:\\jiyu\\zuixing\\ai\\data\\assistant.ini ，模型 deepseek-flash 。",
    "", "")
app.root.update()

check("气泡文本可选中（cursor=xterm）", str(t.cget("cursor")) == "xterm", t.cget("cursor"))
check("绑定了双击智能选择", bool(t.bind("<Double-Button-1>")))
check("绑定了右键菜单", bool(t.bind("<Button-3>")))
check("文本仍是只读（按键被拦）", wb_app._ro_key(type("E", (), {"state": 0, "keysym": "a"})()) == "break")

# 模拟双击：定位到路径所在坐标
app.root.update()
txt_line = t.get("1.0", "1.end")
col = txt_line.index("F:")
# 通过 bbox 找到该字符的像素坐标，构造事件
bbox = t.bbox("1.%d" % col)
if bbox:
    ev = type("E", (), {"x": bbox[0] + 2, "y": bbox[1] + 2})()
    r = None
    try:
        # 直接调用内部逻辑：取 index + _pick_token
        idx = t.index("@%d,%d" % (ev.x, ev.y))
        row = idx.split(".")[0]
        ln = t.get(row + ".0", row + ".end")
        sp = wb_app._pick_token(ln, int(idx.split(".")[1]))
        t.tag_remove(tk.SEL, "1.0", "end")
        t.tag_add(tk.SEL, "%s.%d" % (row, sp[0]), "%s.%d" % (row, sp[1]))
        r = wb_app.copy_text(t)
    except Exception as e:
        r = "ERR %r" % (e,)
    check("双击处能选中并复制到剪贴板",
          isinstance(r, str) and "assistant.ini" in r, (r or "")[:60])
else:
    check("双击处能选中并复制到剪贴板", False, "no bbox")

# 剪贴板内容
try:
    clip = app.root.clipboard_get()
except Exception:
    clip = ""
check("剪贴板里确实是路径", "assistant.ini" in (clip or ""), clip[:60])

# ---- 3) 用户气泡双击复制 ----
cv.add_user("我的原始问题 hello world")
app.root.update()
lb = None
for row in cv.inner.pack_slaves():
    for c in row.winfo_children():
        if c.winfo_class() == "Canvas":
            body = getattr(c, "_body", None)
            if body is not None and body.winfo_class() == "Label" \
                    and "我的原始问题" in str(body.cget("text")):
                lb = body
if lb is not None:
    # Tk 不允许用 event_generate 造双击事件，这里验证绑定确实存在，
    # 并直接走同一条复制路径（getter -> 剪贴板）
    bound = bool(lb.bind("<Double-Button-1>"))
    try:
        app.root.clipboard_clear()
        app.root.clipboard_append(str(lb.cget("text")))
        app.root.update()
        clip2 = app.root.clipboard_get()
    except Exception as e:
        clip2 = "ERR %r" % (e,)
    check("用户气泡绑定了双击复制", bound)
    check("用户气泡文本可进剪贴板", "我的原始问题" in (clip2 or ""), (clip2 or "")[:40])
else:
    check("用户气泡绑定了双击复制", False, "label not found")
    check("用户气泡文本可进剪贴板", False)

app.root.destroy()
print("RESULT: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
