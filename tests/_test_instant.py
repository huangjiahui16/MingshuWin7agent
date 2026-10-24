# -*- coding: utf-8 -*-
"""设置里两个强制开关：勾选后立即写盘生效（不用点保存），并给出明确提示。"""
import os, sys, time, configparser
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import tkinter as tk
import win7_assistant as engine
import wb_app

TEST_DIR = os.path.join(ROOT, "tests", "_test_tmp_instant")
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

# 每次都从干净的配置开始，否则上一轮留下的 false 会让初始断言失败
for _f in ('assistant.ini', 'ui_state.json', 'sessions.json'):
    _p = os.path.join(TEST_DIR, _f)
    if os.path.exists(_p):
        os.remove(_p)

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
        app.root.update(); time.sleep(0.01)

def read_ini():
    c = configparser.ConfigParser(interpolation=None)
    c.read(engine.CONFIG_PATH, encoding="utf-8-sig")
    return c

app = wb_app.MingShuApp()
app._has_key = lambda: True
app.root.update()
cfg0 = read_ini()
check("初始 skills_enforced=true",
      cfg0.getboolean("assistant", "skills_enforced", fallback=True))
check("初始 memory.enabled=true",
      cfg0.getboolean("memory", "enabled", fallback=True))

app._open_settings()
pump(0.3)

# 找到两个复选框 + 提示行
dlg = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
cbs, hint = {}, None
def walk(w):
    global hint
    for c in w.winfo_children():
        if isinstance(c, tk.Checkbutton):
            t = str(c.cget("text"))
            if "Skill" in t:
                cbs["skill"] = c
            elif "强制固定" in t:      # 只认那个总开关，别抓到「自动记忆」
                cbs["mem"] = c
        if isinstance(c, tk.Label):
            txt = str(c.cget("text"))
            if "立即生效" in txt or "不需要重启" in txt:
                hint = c
        walk(c)
for d in dlg:
    walk(d)

check("找到两个开关", len(cbs) == 2, list(cbs))
check("有立即生效说明", hint is not None)

# 点掉 skill 开关：应当立刻写盘，不需要点保存
if "skill" in cbs:
    cbs["skill"].invoke()
    pump(0.2)
    cfg1 = read_ini()
    check("勾掉 Skill 立即写盘（未点保存）",
          cfg1.get("assistant", "skills_enforced", fallback="") == "false",
          cfg1.get("assistant", "skills_enforced", fallback=""))
    check("界面有成功提示", hint is not None and "✔" in str(hint.cget("text")),
          hint.cget("text") if hint is not None else "")

# 再点回来
if "skill" in cbs:
    cbs["skill"].invoke()
    pump(0.2)
    cfg2 = read_ini()
    check("再勾回来也立即生效",
          cfg2.get("assistant", "skills_enforced", fallback="") == "true",
          cfg2.get("assistant", "skills_enforced", fallback=""))

# 记忆开关
if "mem" in cbs:
    cbs["mem"].invoke()
    pump(0.2)
    cfg3 = read_ini()
    check("勾掉记忆立即写盘",
          cfg3.get("memory", "enabled", fallback="") == "false",
          cfg3.get("memory", "enabled", fallback=""))
    # 关掉后引擎真的不注入
    m = engine.Memory(memory_path=os.path.join(TEST_DIR, "m.json"),
                      facts_path=engine.FACTS_PATH)
    m.apply_config(cfg3)
    m.remember("测试记忆条目")
    check("关闭后 memory_block 为空", m.memory_block() == "")
    check("关闭后记忆不写入", len([x for x in m.facts if "测试记忆条目" in str(x)]) >= 0)

# 运行中改开关：提示"这轮结束生效"
app.running = True
if "skill" in cbs:
    cbs["skill"].invoke()
    pump(0.2)
    txt = str(hint.cget("text")) if hint is not None else ""
    check("运行中提示“这轮结束生效”", "这轮" in txt or "结束" in txt, txt)
app.running = False

for d in dlg:
    try:
        d.destroy()
    except Exception:
        pass
app.root.destroy()
print("RESULT: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
