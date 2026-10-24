# -*- coding: utf-8 -*-
"""Blank-bubble regression test: _fit_text_height must actually shrink Text.

Root cause fixed 2026-10-24: Text.count returns a tuple (n,) on this Tk;
int(tuple) raised TypeError and was swallowed -> every bubble stuck at the
default 24 lines with a big blank area below the content.
Console output ASCII only. Paths redirected to F:\\ temp dir.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp", "blank")
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
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


def _dl(t):
    r = t.count("1.0", "end", "displaylines")
    return int(r[0]) if isinstance(r, (tuple, list)) else int(r)


root = tk.Tk()
root.geometry("900x700")
cv = wb_app.ChatView(root, wb_app.THEME)
cv.pack(fill=tk.BOTH, expand=True)
root.update()


def _last_texts():
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Text):
                out.append(c)
            walk(c)

    walk(cv.inner)
    return out


# 1. short assistant reply must NOT stay at default 24 lines
cv.add_assistant("short reply", "disc", "usage")
root.update(); root.update()
texts = _last_texts()
t = texts[-1]
check("short reply fitted (h=%d, dl=%d)" % (int(float(t.cget("height"))), _dl(t)),
      int(float(t.cget("height"))) == _dl(t) and int(float(t.cget("height"))) <= 3)

# 2. long reply fits its displaylines
cv.add_assistant("\n".join("line %d" % i for i in range(60)), "disc", "")
root.update(); root.update()
t2 = _last_texts()[-1]
check("long reply fitted (h=%d, dl=%d)" % (int(float(t2.cget("height"))), _dl(t2)),
      abs(int(float(t2.cget("height"))) - _dl(t2)) <= 1)

# 3. window narrower -> rewrap -> height grows (adaptive actually alive)
root.geometry("520x700")
root.update(); root.update()
check("narrow window refit (h=%d)" % int(float(t2.cget("height"))),
      int(float(t2.cget("height"))) >= int(float(t2.cget("height"))))
check("narrow refit changed or matches dl",
      int(float(t2.cget("height"))) == _dl(t2))

# 4. user bubble visible and compact
cv.add_user("hello from user")
root.update(); root.update()
last_row = cv.inner.winfo_children()[-1]
lb = None


def _walk(w):
    global lb
    for c in w.winfo_children():
        if isinstance(c, tk.Label) and "hello from user" in str(c.cget("text")):
            lb = c
        _walk(c)


_walk(last_row)
check("user label exists", lb is not None)
if lb is not None:
    # 画布对视口外的内嵌窗口会取消映射：先滚回顶部让该行进入视口
    cv.canvas.yview_moveto(0.0)
    root.update(); root.update()
    check("user label mapped & shown", lb.winfo_ismapped() and lb.winfo_height() > 5)
    check("user label text kept", "hello from user" in str(lb.cget("text")))

# 5. tool card / thinking capped, not default 24
cv.add_thinking("think\n" * 40)
cv.add_tool_card("read_file", "x\n" * 60, "")
root.update(); root.update()
th = None
tc = None
for row in cv.inner.winfo_children():
    for card in row.winfo_children():
        for w in card.winfo_children():
            if isinstance(w, tk.Text):
                th = w if th is None else th
                tc = w
check("thinking capped <=16 (h=%s)" % th.cget("height"),
      int(float(th.cget("height"))) <= 16)
check("tool card capped <=20 (h=%s)" % tc.cget("height"),
      int(float(tc.cget("height"))) <= 20)

# 6. stream fold must not leave an empty tall row (the 550px blank-row bug)
cv.add_user("q")
cv.stream_begin()
cv.stream_push("chunk " * 300)
root.update(); root.update()
cv.stream_fold()
root.update(); root.update()
zombies = [r for r in cv.inner.winfo_children()
           if len(r.winfo_children()) == 0 and r.winfo_reqheight() > 60]
check("no empty tall row after stream fold", not zombies)
cv.add_assistant("final answer", "disc", "usage")
root.update(); root.update()
# distance between user bubble and next visible bubble must be small
rows = [r for r in cv.inner.winfo_children() if r.winfo_children()]
gaps_ok = True
prev = None
for r in rows:
    if prev is not None:
        gap = r.winfo_rooty() - (prev.winfo_rooty() + prev.winfo_height())
        if gap > 40:
            gaps_ok = False
    prev = r
check("no big gaps between bubbles", gaps_ok)

# 7. delete session removes local cache file
import json
sid = "testsession01"
os.makedirs(wb_app.SESSIONS_DIR, exist_ok=True)
hp = os.path.join(wb_app.SESSIONS_DIR, sid + ".json")
with open(hp, "w", encoding="utf-8") as f:
    json.dump([{"role": "user", "content": "hi"}], f, ensure_ascii=False)
wb_app.SESSIONS_META = os.path.join(TEST_DIR, "sessions.json")
store = wb_app.SessionStore()
store.sessions.append({"id": sid, "title": "t", "created": 0, "updated": 0,
                       "goal": "", "goal_paused": False})
store.delete(sid)
check("delete removes local cache file", not os.path.exists(hp))

root.destroy()
print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
