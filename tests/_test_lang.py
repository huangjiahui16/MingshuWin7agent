# -*- coding: utf-8 -*-
"""验证：语言切换 / 附件缩略图 / 悬停预览 / api.md 同步 / 工具全挂。"""
import os, sys, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import tkinter as tk
import win7_assistant as engine
import wb_app

TEST_DIR = os.path.join(ROOT, "tests", "_test_tmp_lang")
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

app = wb_app.MingShuApp()
app._has_key = lambda: True
root = app.root
root.update()

check("默认中文", app.lang == "zh" and app.t is wb_app.TEXT, app.lang)
check("语言按钮存在", hasattr(app, "btn_lang") and app.btn_lang.winfo_exists())
btn_text = app.btn_lang._text if hasattr(app.btn_lang, "_text") else ""
check("按钮文案含中英", "English" in btn_text or "中文" in btn_text, btn_text)

# 切换英文
app.toggle_lang()
root.update()
check("切换后是英文", app.lang == "en" and app.t is wb_app.TEXT_EN)
check("英文标题生效", app.t["nav_chat"] == "Chat")
saved = json.load(open(wb_app.UI_STATE, encoding="utf-8"))
check("语言已写入缓存", saved.get("lang") == "en", saved.get("lang"))
check("英文下窗口标题", "MingShu" in root.title() or app.t["app_title"] in root.title())

# 切回中文
app.toggle_lang()
root.update()
check("切回中文", app.lang == "zh" and app.t is wb_app.TEXT)
saved = json.load(open(wb_app.UI_STATE, encoding="utf-8"))
check("缓存更新为 zh（覆盖旧的）", saved.get("lang") == "zh", saved.get("lang"))

# 附件缩略图 + 预览
png = os.path.join(TEST_DIR, "shot.png")
wb_app._png_write(png, 4, 4, [b"\xff\x00\x00" * 4 for _ in range(4)])
app._add_files([png])
root.update()
check("附件已加入", png in app._attachments)
cards = app.attach_row.winfo_children()
check("附件区有卡片", len(cards) >= 2, len(cards))
app._preview_show(png, cards[-1])
root.update()
check("悬停预览窗口打开", app._preview_win is not None and app._preview_win.winfo_exists())
app._preview_destroy()
check("预览可关闭", app._preview_win is None)

# api.md 读取（测试目录可能没有 → 空列表也接受）
presets, active = engine.load_api_presets()
check("api 预设可解析", isinstance(presets, list))

# 工具全挂（max_tools 默认 0）
import configparser
c = configparser.ConfigParser(interpolation=None)
c.add_section("agent"); c.add_section("assistant"); c.add_section("memory")
holder = {}
def fake_chat(cfgx, messages, tools=None, on_delta=None, stop_event=None):
    holder["n"] = len(tools or [])
    return {"content": "ok", "tool_calls": []}
engine.chat_raw = fake_chat
mem = engine.Memory(memory_path=os.path.join(TEST_DIR, "m.json"),
                    facts_path=engine.FACTS_PATH)
engine.agent_run(c, mem, "hi", engine.Approver(True, None))
check("默认挂载全部工具", holder.get("n", 0) >= 28, holder.get("n"))

root.destroy()
print("RESULT: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
