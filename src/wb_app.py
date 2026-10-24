# -*- coding: utf-8 -*-
"""
明枢Win7 桌面助手前端（wb_app.py）
====================================================================
自绘聊天界面，布局/交互参考主流桌面 AI 客户端，纯 Python 标准库
（tkinter）实现，可在 Windows 7 + Python 3.8.10 上直接运行，无需
Electron / Node / 任何第三方依赖。

布局（对齐官方）：
  ┌───────────┬──────────────────────────────────────────┐
  │ 侧边栏     │ 顶栏：标题 / 模式 / 模型 / 工作目录 / 布局   │
  │ 新对话     ├──────────────────────────────────────────┤
  │ 搜索会话   │                                          │
  │ 最近会话   │  对话区（消息气泡 / 思考 / 工具卡片 /       │
  │ 导航       │  权限批准 / 阶段状态 / 免责声明）           │
  │ 底部控制   │                                          │
  │           ├──────────────────────────────────────────┤
  │           │  输入区（工具栏 / 多行输入 / 发送·停止）     │
  └───────────┴──────────────────────────────────────────┘

核心功能（对齐官方 docs/cn/cli/web-ui.md）：
  - 会话管理：新建 / 切换 / 重命名 / 删除 / 自动标题 / 搜索
  - 主 Agent 模式：Agent（全工具）/ Plan（只读计划）/ Ask（纯问答）
  - 权限模式：每次询问 / 跳过确认 / 免打扰（拒绝危险操作）
  - 工具执行展示：内联工具卡片（名称 / 参数 / 结果，可折叠）
  - 权限批准：对话内卡片，允许 / 拒绝
  - 目标模式（/goal）、深度思考开关、排队发送
  - 主题：浅色 / 深色（官方配色令牌）；语言：中文 / English
  - 命令面板（Ctrl+K）、快捷键（Enter 发送 / Shift+Enter 换行 / Esc 停止）
  - 终端视图、设置面板、长期记忆（记住/回忆）
  - 任意 OpenAI 兼容接口（DeepSeek / 通义 / Kimi / OpenAI / Ollama）
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    ROOT = BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # ROOT/src
    ROOT = os.path.dirname(BASE_DIR)                        # ROOT
# 可写数据统一放 ROOT/data：配置、会话、日志、崩溃记录、剪贴板图片
DATA_DIR = os.path.join(ROOT, "data")
try:
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    pass
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import tkinter as tk
except ImportError:
    print("当前 Python 没有 tkinter 组件，无法启动图形界面。")
    print("请改用命令行模式：python win7_assistant.py --cli")
    sys.exit(1)

import win7_assistant as engine

SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
SESSIONS_META = os.path.join(DATA_DIR, "sessions.json")
UI_STATE = os.path.join(DATA_DIR, "ui_state.json")

# 版本戳：改过代码后一眼能看出窗口里跑的是新版还是旧进程
APP_BUILD = "v18 · 2026-10-24"


def _asset_path(name):
    """资源文件定位：兼容源码运行、PyInstaller onefile（_MEIPASS）和
    onefile 外的 assets 目录（exe 同级）。"""
    cands = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(os.path.join(meipass, "assets", name))
        cands.append(os.path.join(meipass, name))
    cands.append(os.path.join(ROOT, "assets", name))
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        cands.append(os.path.join(exe_dir, "assets", name))
    except Exception:
        pass
    for p in cands:
        if os.path.isfile(p):
            return p
    return cands[0] if cands else name

# ---------------------------------------------------------------- 主题令牌
# 取值来自官方 Web UI 样式表（index-DESzSkbX.css）的设计变量。

THEME = {
    "bg_primary": "#fefefe", "bg_secondary": "#f5f5f7", "bg_card": "#ffffff",
    "bg_hover": "#f5f5f5", "bg_input": "#ffffff", "bg_code": "#f8f9fa",
    "bg_user": "#eef2ff", "bg_tool": "#fafafa", "bg_error": "#fff1f0",
    "bg_permission": "#fffbe6", "bg_chip": "#f0f0f2", "bg_terminal": "#121314",
    "fg_primary": "#1a1a1a", "fg_secondary": "#5c5c5c", "fg_tertiary": "#8e8e93",
    "fg_user": "#1e3a8a", "fg_code": "#c7254e", "fg_link": "#1677ff",
    "fg_terminal": "#cccccc", "fg_on_brand": "#ffffff",
    "border": "#dcdee3", "border_muted": "#e8eaed", "border_input": "#e5e7eb",
    "accent": "#1677ff", "accent_brand": "#1a1a1a", "accent_brand_hover": "#000000",
    "green": "#16a34a", "red": "#dc2626", "yellow": "#b45309",
    "scrollbar": "#d4d4d8", "scroll_trough": "#f4f4f5",
}


# ---------------------------------------------------------------- 界面语言

TEXT = {
    "app_title": "明枢Win7",
    "new_chat": "＋ 新对话",
    "recent": "最近会话",
    "nav_chat": "对话", "nav_terminal": "终端", "nav_settings": "设置",
    "nav_help": "帮助",
    "perm_ask": "每次询问", "perm_bypass": "跳过确认",
    "perm_dontask": "免打扰",
    "gear_auto": "🟢 自动", "gear_ask": "🟡 询问",
    "gear_strict": "🟠 严格", "gear_locked": "🔴 锁死",
    "gear_hint": "点我切换权限档位",
    "gear_desc": "L0 只读 · L1 写 logs/ · L2 改配置 · L3 动系统",
    "mode_agent": "Agent", "mode_plan": "Plan", "mode_ask": "Ask",
    "model": "模型", "workspace": "工作目录", "workspace_all": "整台电脑",
    "workspace_set": "设置工作目录", "workspace_clear": "取消限制",
    "goal": "目标", "goal_pause": "暂停",
    "goal_resume": "继续", "goal_clear": "清除",
    "deep_think": "◇ 深度思考", "palette": "⌘K 命令",
    "send": "发送 (Enter)", "force_send": "强制发送", "interrupt": "打断",
    "stop": "停止", "queued": "（排队中）",
    "hint": "Enter 发送 · Shift+Enter 换行 · Esc 停止 · Ctrl+K 命令面板",
    "thinking": "思考过程", "phase_streaming": "接收中…", "phase_tool": "执行工具",
    "phase_done": "处理中…", "phase_stopping": "正在停止…",
    "disclaimer": "回答由 AI 生成，仅供参考",
    "perm_title": "需要你的批准",
    "perm_allow": "允许执行", "perm_deny": "拒绝",
    "perm_always": "高级权限，以后不用问我",
    "perm_ok": "已允许", "perm_no": "已拒绝", "perm_always_ok": "已开启高级权限，以后同类操作不再询问",
    "tool_result": "执行结果", "scroll_latest": "跳到最新 ↓",
    "rename": "重命名", "delete": "删除", "copy_id": "复制会话 ID",
    "delete_confirm": "将结束当前对话并删除其历史记录，确定吗？",
    "session_untitled": "新对话",
    "settings_title": "设置",
    "settings_budget": "省 token / 预算",
    "settings_history": "携带历史条数（越小越省）",
    "settings_max_tokens": "单次回复上限 tokens（0 = 不限）",
    "settings_thinking": "思考档位（V4 系列默认带思考，关了最省）",
    "settings_skills_force": "强制执行 Skill（关掉后技能库清单和加载工具都不注入，最省 token）",
    "settings_mem_force": "强制固定记忆（关掉后不注入长期记忆，也不保存新记忆）",
    "think_off": "关闭", "think_low": "低", "think_high": "高", "think_max": "最高",
    "settings_tool_chars": "工具结果回传上限（字符）", "settings_llm": "模型接口",
    "settings_base": "接口地址", "settings_key": "API Key",
    "settings_model": "模型", "settings_proxy": "代理（Win7 抽风时才填）",
    "settings_agent": "Agent", "settings_steps": "单任务最大步数",
    "settings_perm": "危险操作确认", "settings_ws": "限制操作的目录",
    "settings_ui": "界面", "save": "保存", "need_key": "还没有配置 API Key，请先在「设置 → 模型接口」里填写。",
    "terminal_hint": "在这里输入 cmd 命令回车执行（工作目录：%s）",
    "terminal_run": "执行", "terminal_clear": "清空",
    "empty_chat_hint": "跟他说第一件事就会开工。比如：「看看我桌面上有什么」「帮我找 C 盘里的 PDF」「记住：我每周五下午要交周报」。",
    "attach": "文件",
    "attach_hint": "▤ 把文件拖进窗口，或点「文件」按钮添加（可多选，纯文本会直接读给 AI）",
    "attach_count": "待发送 %d 个文件（发送后自动清空）",
    "attach_remove": "移除",
    "attach_dialog": "选择要发给 AI 的文件",
    "attach_too_many": "一次最多带 10 个文件。",
    "attach_fail": "读不了的路径：%s",
    "settings_memory": "记忆",
    "settings_mem_enable": "启用长期记忆（关掉后不再注入，也不保存）",
    "settings_mem_auto": "自动记忆（模型学到持久事实时主动存入）",
    "settings_mem_inject": "每次任务注入的记忆条数（越多越占 token）",
    "settings_mem_keep": "最多保留多少条（超出自动淘汰最旧的）",
    "mem_view": "查看记忆", "mem_clear": "清空记忆",
    "mem_view_title": "长期记忆", "mem_empty": "（还没有记忆。对她说「记住：xxx」就能存一条）",
    "mem_cleared": "已清空长期记忆。", "mem_count": "共 %d 条",
    "mem_save": "保存记忆", "mem_reload": "重新载入",
    "mem_saved": "已保存记忆，共 %d 条。",
    "mem_edit_hint": "一行一条，以 # 开头的是说明不会被记住。改完点「保存记忆」，"
                     "同时会在程序目录生成 记忆.md，用记事本改也行。",
    "net_list": "查看端口连接", "net_scan": "扫描端口", "net_sniff": "抓包",
    "lang_btn": "中文 / English",
    "paste_img": "已粘贴剪贴板图片：%s",
    "lang_busy": "请先停止当前任务再切换语言。",
    "api_preset": "预设（来自 api.md）",
    "api_load": "载入预设",
    "api_test": "测试连通",
    "api_testing": "正在测试…",
    "api_ok": "连接正常",
    "api_md_hint": "预设清单就在程序目录的 api.md 里，改哪边都会同步。",
    "force_hint_default": "这两个开关改完立即生效，不需要重启。",
    "force_applied": "已立即生效：下一条消息就按新设置走。",
    "force_next_round": "已保存；正在跑的这一轮仍用旧设置，这轮结束就生效（不用重启）。",
}

# 工具名 -> 展示名（对齐官方 tool.* 文案风格）
TOOL_ZH = {
    "list_dir": "列出目录", "read_file": "读取文件", "search_files": "搜索文件",
    "grep_files": "全文搜索", "run_cmd": "执行命令", "write_file": "写入文件",
    "open_path": "打开路径", "sys_info": "系统信息", "web_fetch": "抓取网页",
    "remember": "记住", "recall": "回忆",
    "net_list": "查看端口连接", "net_scan": "扫描端口", "net_sniff": "抓取数据包",
    "compare": "比对快照", "proc_list": "查看进程", "reg_query": "查询注册表",
    "schedule_add": "添加定时任务", "schedule_list": "查看定时任务",
    "schedule_del": "删除定时任务", "audit_log": "查看审计日志",
    "detect_preset": "探测本机预设",
    "app_launch": "后台启动程序", "proc_windows": "查程序窗口",
    "proc_kill": "结束进程", "restore_file": "恢复备份",
    "download_file": "多线程下载", "load_skill": "加载技能",
}


def tool_target(name, args):
    """工具真正作用在什么对象上：路径 / 命令 / 网址。"""
    for k in ("path", "pattern", "command", "url", "query", "keyword", "host"):
        v = args.get(k) if isinstance(args, dict) else None
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def tool_head_text(name, args):
    """卡片标题：把工具名和它动的对象放一起，比如「▣ 写入文件 · C:\\...\\hello.py」。"""
    zh = TOOL_ZH.get(name, name)
    t = tool_target(name, args)
    if not t:
        return "▣ %s" % zh
    t = t.replace("\n", " ")
    if len(t) > 54:
        t = "…" + t[-53:]
    return "▣ %s · %s" % (zh, t)


def tool_body_text(name, args, max_preview=30):
    """卡片正文：按工具类型给人看的细节，而不是一串裸 JSON。"""
    if not isinstance(args, dict):
        return str(args)
    if name == "write_file":
        path = args.get("path", "") or ""
        content = args.get("content", "") or ""
        n = content.count("\n") + 1
        preview = "\n".join(content.split("\n")[:max_preview])
        return _tr("写入：%s\n%d 行 / %d 字符\n--- 内容（前 %d 行）---\n%s",
                   "Write: %s\n%d lines / %d chars\n--- content (first %d lines) ---\n%s") % (
            path, n, len(content), max_preview, preview)
    if name == "run_cmd":
        return "$ %s" % (args.get("command", "") or "")
    if name in ("read_file", "list_dir", "open_path"):
        extra = []
        if args.get("max_chars"):
            extra.append(_tr("最多 %s 字符", "up to %s chars") % args["max_chars"])
        return (tool_target(name, args) or "") + (("\n" + " · ".join(extra)) if extra else "")
    if name in ("search_files", "grep_files"):
        return _tr("%s\n范围：%s", "%s\nscope: %s") % (args.get("pattern", "") or "",
                                args.get("path", "") or _tr("用户主目录", "home folder"))
    if name == "web_fetch":
        return args.get("url", "") or ""
    if name == "net_list":
        return _tr("本机 TCP/UDP 连接与监听端口（%s）", "Local TCP/UDP connections and listening ports (%s)") % (args.get("kind", "all") or "all")
    if name == "net_scan":
        ports = (args.get("ports", "") or "").strip() or _tr("常用端口", "common ports")
        return _tr("扫描 %s 的 %s", "Scan %s ports %s") % (args.get("host", "") or "?", ports)
    if name == "net_sniff":
        return _tr("抓取 %s 秒数据包（需管理员权限）%s", "Capture packets for %s s (needs admin)%s") % (
            args.get("seconds", 5) or 5,
            (_tr("，存到 %s", ", saved to %s") % args["save_pcap"]) if args.get("save_pcap") else "")
    if name == "compare":
        return _tr("比对 %s：\n  左：%s\n  右：%s", "Compare %s:\n  left: %s\n  right: %s") % (args.get("kind", "?"),
                                              args.get("left", "")[:60],
                                              args.get("right", "")[:60])
    if name == "proc_list":
        return _tr("列出进程%s", "List processes%s") % ((_tr("（过滤：%s）", " (filter: %s)") % args["filter"]) if args.get("filter") else "")
    if name == "reg_query":
        return _tr("查询注册表：%s%s", "Read registry: %s%s") % (args.get("key", ""),
                                   "\\%s" % args["value"] if args.get("value") else "")
    if name in ("schedule_add", "schedule_del"):
        return "%s：%s" % (args.get("name", "?"), args.get("when", "") or args.get("action", ""))
    if name == "audit_log":
        bits = []
        if args.get("tool"):
            bits.append(_tr("工具=%s", "tool=%s") % args["tool"])
        if args.get("result"):
            bits.append(_tr("结果=%s", "result=%s") % args["result"])
        if args.get("since"):
            bits.append(_tr("从 %s 起", "since %s") % args["since"])
        return _tr("审计日志%s（最近 %s 条）", "Audit log%s (last %s)") % (_tr("，", ", ").join(bits), args.get("tail", 30))
    try:
        return json.dumps(args, ensure_ascii=False, indent=2)
    except Exception:
        return str(args)

FONT = ("Microsoft YaHei", -14)          # 负值 = 像素字号：避开 pt→px 的半像素换算，Win7 上更清晰
FONT_SMALL = ("Microsoft YaHei", -12)
FONT_TINY = ("Microsoft YaHei", -11)
FONT_BOLD = ("Microsoft YaHei", -14, "bold")
FONT_TITLE = ("Microsoft YaHei", -18, "bold")
MONO = ("Consolas", -13)
MONO_SMALL = ("Consolas", -12)

# 只读文本：允许方向键/选择/Ctrl+C，拦掉一切编辑键
_NAV_KEYS = ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
             "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Menu")


def _ro_key(e):
    if bool(e.state & 0x4) and e.keysym.lower() in ("c", "a", "insert"):
        return None
    if e.keysym in _NAV_KEYS:
        return None
    return "break"


def copy_text(t):
    """复制选中内容；没有选中就复制全部。返回复制的文本。"""
    try:
        text = t.get(tk.SEL_FIRST, tk.SEL_LAST)
    except Exception:
        text = t.get("1.0", "end-1c")
    try:
        t.clipboard_clear()
        t.clipboard_append(text)
    except Exception:
        pass
    return text


def _wheel_inside(widget, e):
    """鼠标是不是在这个控件里：决定滚轮事件该不该被它消费。
    bind_all 会让所有控件都收到，不判断的话滚动设置面板会连对话区一起滚。"""
    try:
        x, y = widget.winfo_pointerxy()
        return (widget.winfo_rootx() <= x <= widget.winfo_rootx() + widget.winfo_width()
                and widget.winfo_rooty() <= y <= widget.winfo_rooty() + widget.winfo_height())
    except Exception:
        return False


def _pick_token(line_text, col):
    """在光标所在的这一行里，找出"路径 / 英文串 / 数字"的起止列。
    双击时用它整段选中，省得用户一个词一个词地拖。"""
    best = None
    for m in re.finditer(r"[A-Za-z0-9_\-\\.\\/:~%$@#+=?&]{3,}", line_text):
        if m.start() <= col <= m.end():
            if best is None or (m.end() - m.start()) > (best[1] - best[0]):
                best = (m.start(), m.end())
    return best


def make_copyable(t):
    """让 Text 只读但可选中、可右键复制。
    Tk 的 state=DISABLED 会连选择一起禁掉，所以这里保持 NORMAL 并拦掉编辑键。"""
    t.configure(state=tk.NORMAL, cursor="xterm")
    t.bind("<Key>", _ro_key)
    # 自己处理 Ctrl+C / Ctrl+A：不依赖 Text 类绑定，也不需要窗口先拿到焦点
    t.bind("<Control-c>", lambda e: (copy_text(t), "break")[1])
    t.bind("<Control-C>", lambda e: (copy_text(t), "break")[1])
    t.bind("<Control-a>", lambda e: (t.tag_add(tk.SEL, "1.0", "end-1c"), "break")[1])
    t.bind("<Control-A>", lambda e: (t.tag_add(tk.SEL, "1.0", "end-1c"), "break")[1])

    def _line_copy(_e=None):
        try:
            idx = t.index("insert")
            return t.get(idx + " linestart", idx + " lineend")
        except Exception:
            return ""

    def _double(e):
        """双击：整段选中英文/路径并直接复制（选中可见，用户能看清选了什么）。"""
        try:
            idx = t.index("@%d,%d" % (e.x, e.y))
            row = idx.split(".")[0]
            line = t.get(row + ".0", row + ".end")
            col = int(idx.split(".")[1])
            span = _pick_token(line, col)
            if not span:
                return None
            t.tag_remove(tk.SEL, "1.0", "end")
            t.tag_add(tk.SEL, "%s.%d" % (row, span[0]), "%s.%d" % (row, span[1]))
            t.mark_set("insert", "%s.%d" % (row, span[1]))
            copy_text(t)
            return "break"
        except Exception:
            return None

    t.bind("<Double-Button-1>", _double)

    menu = tk.Menu(t, tearoff=0)
    menu.add_command(label=_tr("复制选中内容（未选中则复制全部）",
                              "Copy selection (whole message if nothing selected)"),
                     command=lambda: copy_text(t))
    menu.add_command(label=_tr("复制整条消息", "Copy whole message"),
                     command=lambda: copy_text(t))
    menu.add_command(label=_tr("复制光标所在行", "Copy the line at the cursor"),
                     command=lambda: (t.clipboard_clear(),
                                      t.clipboard_append(_line_copy())))
    menu.add_separator()
    menu.add_command(label=_tr("全选", "Select all"),
                     command=lambda: t.tag_add(tk.SEL, "1.0", "end-1c"))

    def popup(e):
        try:
            t.focus_set()
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    t.bind("<Button-3>", popup)
    return t


def make_label_copyable(lb, getter):
    """气泡是 Label（本身不能选择），给个右键复制。"""
    menu = tk.Menu(lb, tearoff=0)

    def copy_it():
        lb.clipboard_clear()
        lb.clipboard_append(getter())

    menu.add_command(label=_tr("复制这条消息", "Copy this message"), command=copy_it)
    lb.configure(cursor="hand2")
    lb.bind("<Double-Button-1>", lambda e: copy_it())   # 双击即复制整条

    def popup(e):
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    lb.bind("<Button-3>", popup)


# ---------------------------------------------------------------- 拖拽进来
# Tk 8.6 没有跨平台拖放。Windows 上走 Win32 的 WM_DROPFILES：
# DragAcceptFiles 注册收 WM_DROPFILES，再用 SetWindowLongPtr 把窗口过程换成自己的，
# 收到消息时用 DragQueryFileW 取出路径，其余消息原样转给 Tk 原来的窗口过程。

_DND = {"proc": None, "olds": {}, "hooked": set(), "ready": False, "root": None,
        "on_files": None, "queue": [], "busy": False}


def _dnd_scan(root):
    """把还没挂过的窗口（含所有 Tk 子控件）都注册成拖放目标。
    Tk 的每个控件在 Windows 上都是独立窗口，只注册顶层的话，
    在消息气泡/输入框上松手是收不到的。"""
    if not _DND["ready"]:
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    set_ptr = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    set_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    set_ptr.restype = ctypes.c_void_p
    proc = _DND["proc"]

    hwnds = []
    try:
        parent = user32.GetParent(root.winfo_id())
        if parent:
            hwnds.append(parent)
    except Exception:
        pass

    # 输入框（Text/Entry）不挂钩：窗口过程被换成 Python 回调后，
    # 每一次按键、每一条输入法消息都要先过一遍 Python，拼音/英文连打时会明显发涩。
    # 不注册它不影响拖放——拖到输入框上，消息会落到已注册的父窗口（composer）。
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            if w.winfo_class() not in ("Text", "Entry"):
                hwnds.append(w.winfo_id())
            stack.extend(w.winfo_children())
        except Exception:
            continue

    for h in hwnds:
        if not h or h in _DND["hooked"]:
            continue
        if len(_DND["hooked"]) > 150:
            # 挂得太多既拖慢消息循环又吃内存，够了就停
            break
        try:
            hw = wintypes.HWND(int(h))
            old = set_ptr(hw, -4, ctypes.cast(proc, ctypes.c_void_p))
            if not old:
                continue
            shell32.DragAcceptFiles(hw, True)
            _DND["olds"][int(h)] = old
            _DND["hooked"].add(int(h))
        except Exception:
            continue

    # 清掉已销毁窗口的登记：一是别让映射表无限长大，
    # 二是 HWND 会被系统复用，留着会让新控件被误判成"已挂过"从而收不到拖放
    try:
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        dead = [h for h in _DND["hooked"] if not user32.IsWindow(wintypes.HWND(h))]
        for h in dead:
            _DND["hooked"].discard(h)
            _DND["olds"].pop(h, None)
    except Exception:
        pass


def enable_file_drop(root, on_files):
    """给窗口挂上「文件拖进来」能力。成功返回 True，失败静默返回 False。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        WM_DROPFILES = 0x0233
        LR = ctypes.c_ssize_t          # LRESULT / LONG_PTR
        WNDPROC = ctypes.WINFUNCTYPE(LR, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        # 关键：不声明 argtypes 时 ctypes 会把 64 位窗口过程指针截成 32 位，
        # 转调原过程就 access violation，整个消息循环跟着坏。
        call_prev = getattr(user32, "CallWindowProcW", None) or user32.CallWindowProcW
        call_prev.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM]
        call_prev.restype = LR

        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                           wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        def proc(h, msg, wp, lp):
            # 重要：窗口过程是 Windows 同步调进来的，此时绝对不能再碰 Tk/Tcl
            # （root.after、控件操作都不行）——重入 Tcl 会直接把进程弄崩，
            # 而且崩得没有 Python 异常、没有 crash.log。这里只做纯 Win32 的事，
            # 取到路径塞进队列，交给 Tk 主循环去处理。
            try:
                if msg == WM_DROPFILES:
                    hdrop = wintypes.HANDLE(wp)
                    paths = []
                    try:
                        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                        buf = ctypes.create_unicode_buffer(1024)
                        for i in range(count):
                            if shell32.DragQueryFileW(hdrop, i, buf, 1024):
                                paths.append(buf.value)
                    finally:
                        try:
                            shell32.DragFinish(hdrop)
                        except Exception:
                            pass
                    if paths:
                        _DND["queue"].extend(paths)
                    return 0
            except Exception:
                return 0
            old = _DND["olds"].get(int(h))
            if old is None:
                return 0
            return call_prev(old, h, msg, wp, lp)

        _DND["proc"] = WNDPROC(proc)      # 必须留引用，否则回调被 GC
        _DND["root"] = root
        _DND["on_files"] = on_files
        _DND["ready"] = True
        _dnd_scan(root)
        return len(_DND["hooked"]) > 0
    except Exception:
        _DND["ready"] = False
        return False


def refresh_drop_targets(root):
    """新控件（新消息、切会话）建出来后补挂拖放。已挂过的会跳过。"""
    try:
        _dnd_scan(root)
    except Exception:
        pass


# ---------------------------------------------------------------- 工具函数

def load_ui_state():
    try:
        with open(UI_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(state):
    try:
        with open(UI_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except Exception:
        pass




# ---------------------------------------------------------------- 会话存储

# 当前界面语言（"zh"/"en"）。模块级函数（工具卡片、帮助页等）拿不到 self.t，
# 统一用 _tr(中文, English) 取对应文案。
UI_LANG = ["zh"]


def _tr(zh, en):
    return en if UI_LANG[0] == "en" else zh


# ---------------------------------------------------------------- 剪贴板 / 图片
# Win7 剪贴板：文件走 CF_HDROP(15)，位图走 CF_DIB(8)。Tk 自己读不了这两类，
# 所以用 ctypes 直接读，图片再自己编码成 PNG（纯标准库 zlib，不依赖 PIL）。

def _clip_files():
    """剪贴板里的文件列表（在资源管理器里 Ctrl+C 复制文件后能拿到）。"""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        k = ctypes.windll.shell32
        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.OpenClipboard.restype = wintypes.BOOL
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = wintypes.BOOL
        k.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                     wintypes.LPWSTR, wintypes.UINT]
        k.DragQueryFileW.restype = wintypes.UINT
        if not u.OpenClipboard(None):
            return None
        try:
            if not u.IsClipboardFormatAvailable(15):
                return None
            h = u.GetClipboardData(15)
            if not h:
                return None
            n = k.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
            out = []
            for i in range(min(int(n or 0), 10)):
                buf = ctypes.create_unicode_buffer(1024)
                if k.DragQueryFileW(h, i, buf, 1024):
                    out.append(buf.value)
            return out or None
        finally:
            u.CloseClipboard()
    except Exception:
        return None


def _png_write(path, width, height, rows):
    """把若干 RGB 行（top-down，每行 bytes）写成 PNG。"""
    import struct
    import zlib
    raw = b"".join(b"\x00" + r for r in rows)
    comp = zlib.compress(raw, 6)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", comp))
        f.write(chunk(b"IEND", b""))
    return path


def _clip_image_png(out_path):
    """剪贴板里的位图 -> PNG 文件。成功返回路径，否则 None。"""
    try:
        import ctypes
        import struct
        from ctypes import wintypes
        u = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.OpenClipboard.restype = wintypes.BOOL
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalLock.restype = wintypes.LPVOID
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        k32.GlobalSize.restype = ctypes.c_size_t
        if not u.OpenClipboard(None):
            return None
        try:
            if not u.IsClipboardFormatAvailable(8):
                return None
            h = u.GetClipboardData(8)
            if not h:
                return None
            size = int(k32.GlobalSize(h) or 0)
            ptr = k32.GlobalLock(h)
            if not ptr:
                return None
            try:
                buf = ctypes.string_at(ptr, size)
            finally:
                k32.GlobalUnlock(h)
            if len(buf) < 40:
                return None
            bi_hdr = struct.unpack("<IiiHHIIiiII", buf[:40])
            w, hh = int(bi_hdr[1]), int(bi_hdr[2])
            bpp = int(bi_hdr[4])
            comp = int(bi_hdr[5])
            if comp != 0 or bpp not in (24, 32) or w <= 0 or hh == 0:
                return None
            flip = hh > 0                    # 正高度=bottom-up
            height = abs(hh)
            stride = ((w * bpp // 8) + 3) // 4 * 4
            need = stride * height
            px = buf[40:40 + need]
            if len(px) < need:
                return None
            step = bpp // 8
            rows = []
            for y in range(height):
                src_y = (height - 1 - y) if flip else y
                line = px[src_y * stride: src_y * stride + stride]
                out = bytearray()
                for x in range(w):
                    o = x * step
                    out += bytes((line[o + 2], line[o + 1], line[o]))  # BGR -> RGB
                rows.append(bytes(out))
            return _png_write(out_path, w, height, rows)
        finally:
            u.CloseClipboard()
    except Exception:
        return None


IMG_EXTS = (".png", ".gif", ".bmp", ".ppm", ".pgm", ".ico", ".jpg", ".jpeg")




# 英文界面：键与 TEXT 一一对应，缺的键会回落到中文，避免 KeyError
TEXT_EN = {
    "app_title": "MingShu Win7",
    "new_chat": "+ New chat",
    "recent": "Recent chats",
    "nav_chat": "Chat",
    "nav_terminal": "Terminal",
    "nav_settings": "Settings",
    "nav_help": "Help",
    "perm_ask": "Ask every time",
    "perm_bypass": "Skip confirmation",
    "perm_dontask": "Do not disturb",
    "gear_auto": "🟢 Auto",
    "gear_ask": "🟡 Ask",
    "gear_strict": "🟠 Strict",
    "gear_locked": "🔴 Locked",
    "gear_hint": "Click to change the permission level",
    "gear_desc": "L0 read only · L1 write logs/ · L2 change settings · L3 touch the system",
    "mode_agent": "Agent",
    "mode_plan": "Plan",
    "mode_ask": "Ask",
    "model": "Model",
    "workspace": "Workspace",
    "workspace_all": "Whole computer",
    "workspace_set": "Set workspace",
    "workspace_clear": "Remove limit",
    "goal": "Goal",
    "goal_pause": "Pause",
    "goal_resume": "Resume",
    "goal_clear": "Clear",
    "deep_think": "◇ Deep thinking",
    "palette": "⌘K Commands",
    "send": "Send (Enter)",
    "force_send": "Send anyway",
    "interrupt": "Stop",
    "stop": "Stop",
    "queued": " (queued)",
    "hint": "Enter to send · Shift+Enter for a new line · Esc to stop · Ctrl+K for commands",
    "thinking": "Thinking",
    "phase_streaming": "Receiving…",
    "phase_tool": "Running tool",
    "phase_done": "Working…",
    "phase_stopping": "Stopping…",
    "disclaimer": "Answer generated by AI. Please double-check anything important.",
    "perm_title": "Your approval is needed",
    "perm_allow": "Allow",
    "perm_deny": "Deny",
    "perm_always": "Always allow (don't ask again)",
    "perm_ok": "Allowed",
    "perm_no": "Denied",
    "perm_always_ok": "Always-allow is on for this kind of action",
    "tool_result": "Result",
    "scroll_latest": "Jump to latest ↓",
    "rename": "Rename",
    "delete": "Delete",
    "copy_id": "Copy chat ID",
    "delete_confirm": "This will end the chat and delete its history. Continue?",
    "session_untitled": "New chat",
    "settings_title": "Settings",
    "settings_budget": "Cost and token budget",
    "settings_history": "Messages of history to send (lower saves tokens)",
    "settings_max_tokens": "Max reply tokens (0 = no limit)",
    "settings_thinking": "Thinking level (V4 models think by default; off is cheapest)",
    "settings_skills_force": "Force skills (off = no skill list, no skill loader, saves tokens)",
    "settings_mem_force": "Force long-term memory (off = nothing injected or saved)",
    "think_off": "Off",
    "think_low": "Low",
    "think_high": "High",
    "think_max": "Max",
    "settings_tool_chars": "Max characters of a tool result",
    "settings_llm": "Model API",
    "settings_base": "API base URL",
    "settings_key": "API key",
    "settings_model": "Model name",
    "settings_proxy": "Proxy (only if Win7 networking acts up)",
    "settings_agent": "Agent",
    "settings_steps": "Max steps per task",
    "settings_perm": "Confirm dangerous actions",
    "settings_ws": "Folder the agent may touch",
    "settings_ui": "Interface",
    "save": "Save",
    "need_key": "No API key yet. Open Settings → Model API and fill it in.",
    "terminal_hint": "Type a command and press Enter (working folder: %s)",
    "terminal_run": "Run",
    "terminal_clear": "Clear",
    "empty_chat_hint": "Send your first request and it starts working. For example: \"What is on my desktop?\", \"Find PDFs on my C drive\", \"Remember: I hand in a weekly report every Friday afternoon\".",
    "attach": "Files",
    "attach_hint": "▤ Drag files into the window, click Files, or press Ctrl+V to paste files or a screenshot (plain text files are read straight into the chat)",
    "attach_count": "%d file(s) ready to send (cleared after sending)",
    "attach_remove": "Remove",
    "attach_dialog": "Choose files to send to the AI",
    "attach_too_many": "Up to 10 files at a time.",
    "attach_fail": "Cannot read: %s",
    "settings_memory": "Memory",
    "settings_mem_enable": "Enable long-term memory (off = nothing injected or saved)",
    "settings_mem_auto": "Auto-save facts the model learns about you",
    "settings_mem_inject": "How many memory entries to inject (more costs more tokens)",
    "settings_mem_keep": "How many entries to keep (oldest are dropped)",
    "mem_view": "View memory",
    "mem_clear": "Clear memory",
    "mem_view_title": "Long-term memory",
    "mem_empty": "(No memory yet. Say \"remember: ...\" to add one.)",
    "mem_cleared": "Long-term memory cleared.",
    "mem_count": "%d entries",
    "mem_save": "Save memory",
    "mem_reload": "Reload",
    "mem_saved": "Saved %d memory entries.",
    "mem_edit_hint": "One entry per line. Lines starting with # are notes and are not saved. Click Save memory when done.",
    "net_list": "List connections",
    "net_scan": "Scan ports",
    "net_sniff": "Capture packets",
    "lang_btn": "English / 中文",
    "paste_img": "Pasted clipboard image: %s",
    "lang_busy": "Stop the running task before switching language.",
    "api_preset": "Preset (from api.md)",
    "api_load": "Load preset",
    "api_test": "Test connection",
    "api_testing": "Testing…",
    "api_ok": "Connection OK",
    "api_md_hint": "The preset list lives in api.md next to the program. Edit it there or here — both stay in sync.",
    "force_hint_default": "Both switches take effect immediately — no restart needed.",
    "force_applied": "Applied. The next message uses the new setting.",
    "force_next_round": "Saved. The running task keeps the old setting; it applies when this turn ends (no restart).",
}
# 兜底：任何没翻译到的键沿用中文，绝不让界面因为缺键崩掉
for _k, _v in TEXT.items():
    TEXT_EN.setdefault(_k, _v)


class SessionStore(object):
    """sessions.json 管元数据，sessions/<id>.json 管每个会话的滚动历史。"""

    def __init__(self):
        self.sessions = []
        self._load()

    def _load(self):
        if os.path.exists(SESSIONS_META):
            try:
                with open(SESSIONS_META, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception:
                self.sessions = []
        if not os.path.isdir(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR, exist_ok=True)

    def _save(self):
        with open(SESSIONS_META, "w", encoding="utf-8") as f:
            json.dump(self.sessions, f, ensure_ascii=False, indent=1)

    def list(self):
        return sorted(self.sessions, key=lambda s: s.get("updated", 0), reverse=True)

    def create(self):
        s = {"id": uuid.uuid4().hex[:12], "title": "", "created": time.time(),
             "updated": time.time(), "goal": "", "goal_paused": False}
        self.sessions.append(s)
        self._save()
        return s

    def get(self, sid):
        for s in self.sessions:
            if s["id"] == sid:
                return s
        return None

    def touch(self, sid):
        s = self.get(sid)
        if s:
            s["updated"] = time.time()
            self._save()

    def rename(self, sid, title):
        s = self.get(sid)
        if s:
            s["title"] = title.strip()
            self._save()

    def delete(self, sid):
        self.sessions = [s for s in self.sessions if s["id"] != sid]
        self._save()
        p = os.path.join(SESSIONS_DIR, sid + ".json")
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    def history_path(self, sid):
        return os.path.join(SESSIONS_DIR, sid + ".json")

    def load_history(self, sid):
        p = self.history_path(sid)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def prune(self, days):
        if not days or days <= 0:
            return
        cutoff = time.time() - days * 86400
        for s in list(self.sessions):
            if s.get("updated", 0) < cutoff:
                self.delete(s["id"])


# ---------------------------------------------------------------- Markdown 渲染

# ---------------------------------------------------------------- 圆角组件

def _rr_pts(w, h, r):
    """圆角矩形多边形顶点（配 smooth=True 使用）。"""
    r = max(2, min(r, w / 2.0, h / 2.0))
    return [r, 0, w - r, 0, w, r, w, h - r, w - r, h, r, h, 0, h - r, 0, r]


def _fit_text_height(t, min_h=1, max_h=None):
    """按实际显示行数重算 Text 高度——窗口变宽行数变少时不留底部大片空白。

    坑：Text.count 在 tkinter 里返回元组 (n,)，直接 int() 会 TypeError，
    被旧版 try 吞掉后整个自适应静默失效，气泡全部停在默认 24 行高（大片空白）。
    """
    try:
        r = t.count("1.0", "end", "displaylines")
        n = int(r[0]) if isinstance(r, (tuple, list)) else int(r)
    except Exception:
        return
    n = max(n, min_h)
    if max_h:
        n = min(n, max_h)
    try:
        if int(float(t.cget("height"))) != n:
            t.configure(height=n)
    except Exception:
        pass


def _bind_fit(t, min_h=1, max_h=None):
    """给 Text 挂自适应高度：宽度变化（改 wraplength / 窗口缩放）后自动贴合。"""
    def _on(_e=None):
        try:
            t.after_idle(lambda: _fit_text_height(t, min_h, max_h))
        except Exception:
            pass
    t.bind("<Configure>", _on, add="+")
    _fit_text_height(t, min_h, max_h)


class RoundCard(tk.Canvas):
    """圆角卡片：Canvas 自绘圆角底色 + 内嵌 body 控件。
    wide=True 用于撑满整行的卡片（body 宽度跟随卡片宽度）；
    否则卡片收缩到 body 需要的宽度（用户气泡）。"""

    def __init__(self, master, color, radius=10, outline=None, wide=False, bg=None):
        try:
            mbg = bg or master.cget("bg")
        except Exception:
            mbg = bg or "#ffffff"
        tk.Canvas.__init__(self, master, bg=mbg, highlightthickness=0, bd=0)
        self._color, self._r, self._ol, self._wide = color, radius, outline, wide
        self._body = None
        self._win = None
        self._fit_job = None
        self.bind("<Configure>", self._on_cfg, add="+")

    def set_body(self, widget, padx=12, pady=10):
        self._body = widget
        self._px, self._py = padx, pady
        self._win = self.create_window(padx, pady, anchor="nw", window=widget)
        widget.bind("<Configure>", lambda e: self._schedule(), add="+")
        self._schedule()

    def _on_cfg(self, _e=None):
        self._schedule()

    def _schedule(self):
        if self._fit_job is not None:
            try:
                self.after_cancel(self._fit_job)
            except Exception:
                pass
        try:
            self._fit_job = self.after_idle(self._fit)
        except Exception:
            pass

    def _fit(self):
        self._fit_job = None
        if self._body is None:
            return
        try:
            if self._wide:
                cw = max(int(self.winfo_width()), 1)
                if cw <= 2:                     # 还没被布局，先按需求宽度
                    cw = self._body.winfo_reqwidth() + 2 * self._px
                self.itemconfigure(self._win, width=max(cw - 2 * self._px, 60))
            else:
                cw = self._body.winfo_reqwidth() + 2 * self._px
            ch = max(self._body.winfo_reqheight(), 1) + 2 * self._py
            if (self.winfo_reqwidth(), self.winfo_reqheight()) != (cw, ch):
                self.configure(width=int(cw), height=int(ch))
            self.delete("_bg")
            self.create_polygon(*_rr_pts(cw, ch, self._r), fill=self._color,
                                outline=self._ol or "",
                                width=1 if self._ol else 0, smooth=True,
                                tags=("_bg",))
            self.tag_lower("_bg")
        except Exception:
            pass


class RoundButton(tk.Canvas):
    """圆角按钮：Canvas 自绘。替代 tk.Button 的平面矩形。"""

    def __init__(self, master, text, command, bg, fg, font,
                 radius=9, padx=14, pady=6, outline=None):
        self._text, self._font = text, font
        self._bg, self._fg, self._ol = bg, fg, outline
        self._r, self._px, self._py = radius, padx, pady
        self._cmd = command
        self._hover = self._shade(bg)
        self._cur = bg
        self._painted = (0, 0)
        try:
            mbg = master.cget("bg")
        except Exception:
            mbg = bg
        tk.Canvas.__init__(self, master, bg=mbg, highlightthickness=0, bd=0,
                           cursor="hand2")
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._paint(self._hover))
        self.bind("<Leave>", lambda e: self._paint(self._bg))
        # 被 pack(fill=X/Y) 拉伸时按实际尺寸重画
        self.bind("<Configure>", self._on_cfg, add="+")
        self._paint(bg)

    def _on_cfg(self, _e=None):
        try:
            w, h = int(self.winfo_width()), int(self.winfo_height())
            if (w, h) != self._painted and w > 2 and h > 2:
                self._paint(self._cur)
        except Exception:
            pass

    def _paint(self, color):
        self._cur = color
        self.delete("all")
        t = self.create_text(self._px, self._py, text=self._text,
                             font=self._font, fill=self._fg, anchor="nw")
        bb = self.bbox(t)
        w_req = bb[2] - bb[0] + 2 * self._px
        h_req = bb[3] - bb[1] + 2 * self._py
        w = max(int(self.winfo_width()), int(w_req))
        h = max(int(self.winfo_height()), int(h_req))
        self._painted = (int(w), int(h))
        self.configure(width=int(w), height=int(h))
        self.create_polygon(*_rr_pts(w, h, self._r), fill=color,
                            outline=self._ol or "",
                            width=1 if self._ol else 0, smooth=True,
                            tags=("_bg",))
        self.tag_lower("_bg")

    @staticmethod
    def _shade(color):
        try:
            c = color.lstrip("#")
            r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
            return "#%02x%02x%02x" % (int(r * 0.88), int(g * 0.88), int(b * 0.88))
        except Exception:
            return color

    def set_text(self, text):
        self._text = text
        self._paint(self._bg)

    def _on_click(self, _e=None):
        try:
            self._cmd()
        except Exception:
            pass


class MarkdownText(object):
    """把一个 Text widget 当作画布，渲染官方风格的 Markdown 子集：
    代码块 / 行内代码 / 粗体 / 标题 / 列表 / 表格(等宽对齐) / 分隔线。"""

    def __init__(self, text_widget, theme):
        self.t = text_widget
        self.th = theme

    def _tags(self):
        th = self.th
        t = self.t
        t.tag_configure("h1", font=("Microsoft YaHei", -19, "bold"),
                        foreground=th["accent"], spacing1=8, spacing3=6)
        t.tag_configure("h2", font=("Microsoft YaHei", -17, "bold"),
                        foreground=th["accent"], spacing1=7, spacing3=5)
        t.tag_configure("h3", font=("Microsoft YaHei", -14, "bold"),
                        foreground=th["green"], spacing1=5, spacing3=3)
        t.tag_configure("code", font=MONO, background=th["bg_code"],
                        foreground="#24292f", lmargin1=10, lmargin2=10,
                        rmargin=10, spacing1=4, spacing3=6, wrap="word")
        t.tag_configure("inline_code", font=MONO_SMALL, background=th["bg_code"],
                        foreground="#0e7490")
        t.tag_configure("bold", font=("Microsoft YaHei", -14, "bold"))
        t.tag_configure("li", lmargin1=14, lmargin2=18, spacing1=1, spacing3=1)
        t.tag_configure("quote", lmargin1=12, lmargin2=12, foreground=th["fg_secondary"])
        t.tag_configure("hr", foreground=th["border"], spacing1=6, spacing3=6)
        t.tag_configure("link", foreground=th["fg_link"], underline=True)

    def render(self, md):
        if "code" not in self.t.tag_names():
            self._tags()
        md = md or ""
        parts = md.split("```")
        # parts: [文本, 代码, 文本, 代码, ...]；奇数下标是代码块
        for i, part in enumerate(parts):
            if i % 2 == 1:
                self._render_code_block(part)
            else:
                self._render_text(part)
        t = self.t
        _bind_fit(t)          # 宽度变化后按 displaylines 重算高度，不留空白

    def _render_code_block(self, block):
        lines = block.split("\n")
        lang = ""
        if lines and lines[0].strip() and " " not in lines[0].strip():
            lang = lines[0].strip()
            lines = lines[1:]
        code = "\n".join(lines)
        head = ("``` %s" % lang) if lang else "```"
        self.t.insert("end", head + "\n", ("code",))
        self.t.insert("end", code.rstrip("\n") + "\n", ("code",))

    def _render_text(self, text):
        for raw in text.split("\n"):
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                self.t.insert("end", "\n")
                continue
            if stripped.startswith("###"):
                self._inline(line.lstrip("#").strip(), "h3")
            elif stripped.startswith("##"):
                self._inline(line.lstrip("#").strip(), "h2")
            elif stripped.startswith("#"):
                self._inline(line.lstrip("#").strip(), "h1")
            elif stripped.startswith(("- ", "* ", "+ ")):
                self.t.insert("end", "  • ", ("li",))
                self._inline(stripped[2:], "li")
            elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".)" :
                self.t.insert("end", "  " + stripped.split(" ", 1)[0] + " ", ("li",))
                rest = stripped.split(" ", 1)[1] if " " in stripped else ""
                self._inline(rest, "li")
            elif stripped.startswith(">"):
                self._inline(stripped[1:].strip(), "quote")
            elif stripped in ("---", "***", "___"):
                self.t.insert("end", "─" * 48 + "\n", ("hr",))
            else:
                self._inline(line, ())

    def _inline(self, text, base_tag):
        """行内：`code`、**bold**、[link](url)"""
        import re as _re
        tokens = _re.split(r"(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))", text)
        for tok in tokens:
            if not tok:
                continue
            if tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
                self.t.insert("end", tok[1:-1], ("inline_code",) if not base_tag
                              else ("inline_code", base_tag))
            elif tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
                self.t.insert("end", tok[2:-2], ("bold",) if not base_tag
                              else ("bold", base_tag))
            elif tok.startswith("["):
                m = _re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
                if m:
                    self.t.insert("end", m.group(1), ("link",) if not base_tag
                                  else ("link", base_tag))
                    continue
                self.t.insert("end", tok, (base_tag,) if base_tag else ())
            else:
                self.t.insert("end", tok, (base_tag,) if base_tag else ())


# ---------------------------------------------------------------- 滚动消息区

class ChatView(tk.Frame):
    """官方对话区：Canvas 滚动 + 消息气泡 + 跳到最新按钮。"""

    def __init__(self, master, theme):
        tk.Frame.__init__(self, master, bg=theme["bg_primary"])
        self.th = theme
        self.t = TEXT   # 文案表：add_thinking 等要用；之前漏了会 AttributeError
        # yscrollincrement=1 → yview_scroll 的 "units" 就是 1 像素，
        # 滚轮/滚动条按像素步进，比默认"一格跳 1/10 窗高"顺滑得多
        self.canvas = tk.Canvas(self, bg=theme["bg_primary"], highlightthickness=0,
                                yscrollincrement=1)
        self.sb = tk.Scrollbar(self, width=10, command=self._sb_move,
                               bg=theme["scrollbar"], troughcolor=theme["scroll_trough"],
                               relief="flat", borderwidth=0)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = tk.Frame(self.canvas, bg=theme["bg_primary"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._inner_resized)
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.bind_all("<MouseWheel>", self._wheel)
        for seq in ("<Prior>", "<Next>", "<Home>", "<End>"):
            self.canvas.bind(seq, self._key_scroll)
        self._wraps = []          # [(label, width_ratio)] 供 resize 时重排
        self._width = 800
        self._latest_btn = None
        self._auto_scroll = True
        self._sr_job = None       # scrollregion 合并更新用的 after_idle 任务
        self._end_job = None      # 贴底滚动合并执行用的 after_idle 任务
        self._align_job = None    # 二次对齐任务；用户一滚就要取消，防拽回底部
        self._glide_steps = 0     # 平滑贴底动画步数
        self._stream_card = None  # 流式输出的临时气泡（最终会用 markdown 气泡替换）
        self._stream_row = None   # 流式气泡所在行；discard 时连行一起销毁
        self._stream_tb = None
        self._stream_text = ""
        # 正文/思考增量缓冲区：按 40ms 合并刷屏，别一个 token 插一次 Text
        self._delta_buf = []
        self._delta_job = None
        self._think = None        # 实时思考卡片
        self._think_buf = []
        self._think_job = None
        self._hidden_rows = 0     # 为省内存折叠掉的早期消息条数
        self._top_ph = None       # "上面还有 N 条"占位标签
        self.max_live_rows = 120  # 画布里最多保留多少条消息的实体控件
        self.on_scroll = lambda auto: None
        self.after(200, self._auto_sync)   # 高度回缩兜底轮询

    # ---- 内部机制 ----
    def _content_height(self):
        """按 pack 子项求和算内容真实高度。不能用 inner.winfo_reqheight()：
        画布窗口 item 的显式高度会经 TkSetRequestedSize 污染请求尺寸。"""
        total = 0
        try:
            for ch in self.inner.pack_slaves():
                total += ch.winfo_reqheight()
                py = ch.pack_info().get("pady") or (0, 0)
                if not isinstance(py, tuple):
                    py = (py, py)
                total += int(py[0]) + int(py[1])
        except Exception:
            pass
        return max(total, 1)

    def _request_sync(self):
        if self._sr_job is None:
            self._sr_job = self.after_idle(self._sync_scrollregion)

    def _auto_sync(self):
        """兜底轮询：Tk 画布窗口 item 只长不缩，内容收缩时不会有任何事件，
        必须主动发现高度差并重配 scrollregion（顺带把 item 高度拽回来）。"""
        try:
            total = self._content_height()
            sr = str(self.canvas.cget("scrollregion")).split()
            cur = int(float(sr[3])) if len(sr) >= 4 else -1
            if abs(cur - total) > 1:
                self._sync_scrollregion()
        except Exception:
            pass
        self.after(200, self._auto_sync)

    def _inner_resized(self, _e):
        # 内层一变高这里就触发；流式输出时一秒能来几十次。
        # bbox("all") 要遍历画布上全部子项，同步做会拖卡滚动——
        # 用 after_idle 把同一帧里的多次触发合并成一次。
        if self._sr_job is None:
            self._sr_job = self.after_idle(self._sync_scrollregion)

    def _sync_scrollregion(self):
        self._sr_job = None
        try:
            total = self._content_height()
            w = max(int(self._width), 1)
            # 显式给定 item 高度：画布窗口 item 只长不缩，不显式拽回的话
            # 聊天记录会永远停在历史上的最大高度（"记录提前产生长度"）。
            # 高度按 pack_slaves 求和——inner.winfo_reqheight 会被
            # TkSetRequestedSize 污染（显式 item 高度会覆盖它的请求尺寸）。
            self.canvas.itemconfig(self._win, height=total, width=w)
            self.canvas.configure(scrollregion=(0, 0, w, total))
        except Exception:
            return
        # 内容长高时（新消息、流式文字）如果还处于跟随状态，就一直贴在底部。
        # glide 锚点动画期间例外：新行的 configure 会触发这里，不拦住的话
        # 会瞬间 yview_moveto(1.0) 把"停在用户气泡旁"的动画整个顶掉。
        if self._auto_scroll and not getattr(self, "_gliding", False):
            self.canvas.yview_moveto(1.0)

    def _canvas_resized(self, e):
        self._width = max(e.width, 200)
        self.canvas.itemconfig(self._win, width=self._width)
        for w, ratio in self._wraps:
            try:
                if ratio is None:          # 用户气泡：贴内容
                    self._fit_user_wrap(w)
                else:
                    w.configure(wraplength=int(self._width * ratio))
            except Exception:
                pass
        if self._auto_scroll and not getattr(self, "_gliding", False):
            self.scroll_to_end(force=True)

    def _on_scroll(self, first, last):
        # 这里只负责同步滚动条。
        # 千万别用它来判断"用户是否停在底部"：内容一变长，最后一条消息就跑到
        # 可视区外，last 自然从 1.0 掉到 0.9x，于是自动跟随被误关掉，
        # 表现就是"新回答出现在下面，得手动往下拉"。
        self.sb.set(first, last)

    def _user_scrolled(self, going_up=False):
        """只在真正的用户操作后调用（滚轮/拖滚动条/翻页），据此决定是否继续跟随。
        going_up：用户在向上滚。向上滚必须立刻断开跟随——哪怕只离底部 48px，
        否则贴底逻辑会在下一帧把视图吸回去，用户感觉"滚不动"。
        向下滚时用像素距离判断"是否回到底部"：长对话里 0.5% 可能是几百像素，
        50px 内都算还在底部。"""
        if going_up:
            self._auto_scroll = False
        else:
            try:
                _first, last = self.canvas.yview()
                sr = str(self.canvas.cget("scrollregion")).split()
                h = float(sr[3]) if len(sr) == 4 and sr[3] else 0
                px_from_bottom = (1.0 - float(last)) * h
                self._auto_scroll = px_from_bottom < 50
            except Exception:
                self._auto_scroll = True
        # 用户手动滚动了，挂起的贴底对齐必须作废，否则会把视图拽回底部
        if self._align_job is not None:
            try:
                self.after_cancel(self._align_job)
            except Exception:
                pass
            self._align_job = None
        try:
            self.on_scroll(self._auto_scroll)
        except Exception:
            pass

    def _sb_move(self, *args):
        # 滚动条箭头按 "units" 步进；yscrollincrement=1 时一个 unit 只有 1 像素，
        # 不放大一下点一下箭头才挪 1px，等于没动。1 格箭头 ≈ 48 像素。
        if len(args) == 3 and args[0] == "scroll" and args[2] == "units":
            try:
                n = int(float(args[1]) * 48)
                self.canvas.yview_scroll(n, "units")
                self._user_scrolled(going_up=(n < 0))
                return
            except Exception:
                self.canvas.yview(*args)
        else:
            try:
                going_up = len(args) == 2 and args[0] == "moveto" \
                    and float(args[1]) < self.canvas.yview()[0]
            except Exception:
                going_up = False
            self.canvas.yview(*args)
            self._user_scrolled(going_up=going_up)
            return
        self._user_scrolled()

    def _wheel(self, e):
        if not self._pointer_inside():
            return
        # 像素级步进：120（一个标准滚轮格）≈ 60px，比默认一格格跳 1/10 窗高顺滑；
        # 高分辨率滚轮的小 delta 也会自然变成平滑滚动
        d = e.delta
        if d > 120:
            d = 120
        elif d < -120:
            d = -120
        self.canvas.yview_scroll(int(-d / 2), "units")
        self._user_scrolled(going_up=(d > 0))

    def _wheel_from_child(self, e):
        """气泡里的长 Text（思考 / 工具结果 / 权限详情）滚轮智能分配：
        内容超出可视高度时先滚内部，滚到顶/底再转交对话区；
        内容不到一屏时直接转交，不会把滚轮"吸住"。"""
        d = e.delta
        if d > 120:
            d = 120
        elif d < -120:
            d = -120
        w = e.widget
        if isinstance(w, tk.Text):
            try:
                first, last = w.yview()
                can_up = first > 0.0005
                can_down = last < 0.9995
                if (d > 0 and can_up) or (d < 0 and can_down):
                    w.yview_scroll(int(-d / 2), "pixels")
                    return "break"
            except Exception:
                pass
        self._wheel(e)
        return "break"

    def _attach_wheel(self, w):
        try:
            w.bind("<MouseWheel>", self._wheel_from_child)
        except Exception:
            pass

    def _key_scroll(self, e):
        k = e.keysym
        up = k in ("Prior", "Home")
        if k == "Prior":
            self.canvas.yview_scroll(-1, "pages")
        elif k == "Next":
            self.canvas.yview_scroll(1, "pages")
        elif k == "Home":
            self.canvas.yview_moveto(0.0)
        elif k == "End":
            self.canvas.yview_moveto(1.0)
        self._user_scrolled(going_up=up)
        return "break"

    def _pointer_inside(self):
        # 用"指针下控件是否为对话区后代"判断，而不是只比矩形：
        # 设置弹窗压在对话区上面时，矩形判断会让两个区一起滚。
        try:
            x, y = self.winfo_pointerxy()
            under = self.winfo_containing(x, y)
            return under is not None and str(under).startswith(str(self) + ".")
        except Exception:
            return False


    def register_wrap(self, widget, ratio):
        self._wraps.append((widget, ratio))
        try:
            widget.configure(wraplength=int(self._width * ratio))
        except Exception:
            pass

    def clear(self):
        self.stream_discard()
        for child in self.inner.winfo_children():
            child.destroy()
        self._wraps = []
        self._auto_scroll = True

    def scroll_to_end(self, force=False):
        if not (self._auto_scroll or force):
            return
        # 流式输出时每次 chunk 都会喊一次贴底；用 after_idle 合并成
        # 一帧最多做一次，别每次都强推 update_idletasks 同步重排（卡顿主因）
        if self._end_job is None:
            self._end_job = self.after_idle(self._do_scroll_end)

    def _do_scroll_end(self):
        self._end_job = None
        self._glide_target = 1.0    # AI 输出已开始跟随，glide 锚点作废
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)
            # 内层高度有时在这一帧之后才定下来，下一帧再对齐一次，避免差半屏
            self._align_job = self.after_idle(self._safe_bottom)
        except Exception:
            pass

    def _safe_bottom(self):
        self._align_job = None
        try:
            if self._auto_scroll:
                self.canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _anchor_frac(self):
        """发送后滚动目标：最后一条用户气泡的底边贴近视口底部（留 60px 余量），
        而不是绝对最底——否则用户消息被顶出视野，看起来像"发出去看不到"。"""
        try:
            row = getattr(self, "_last_user_row", None)
            # 注意别判 winfo_ismapped：画布窗口里的子项经常报 0（Tk 已知怪癖），
            # 但 winfo_y() 几何数据是准的；之前在这里误判导致锚点永远失效。
            if row is None or not row.winfo_exists():
                return 1.0
            # 别依赖 winfo_y：刚 pack 的行在首次 idle 布局前 y=0，锚点会算成 0。
            # 按 pack 顺序求和，和 _content_height 同一套坐标系，任何时刻都准。
            y_bottom = 0
            for ch in self.inner.pack_slaves():
                py = ch.pack_info().get("pady") or (0, 0)
                if not isinstance(py, tuple):
                    py = (py, py)
                y_bottom += ch.winfo_reqheight() + int(py[0]) + int(py[1])
                if ch is row:
                    break
            y_bottom += 60.0    # 气泡底再留 60px 余量，别贴着屏幕边
            total = max(float(self._content_height()), 1.0)
            vh = max(float(self.canvas.winfo_height()), 1.0)
            # yview 分数是相对 scrollregion 总高的（offset = frac * total）
            return min(max((y_bottom - vh) / total, 0.0), 1.0)
        except Exception:
            return 1.0

    def glide_to_end(self):
        """发送消息后平滑滑到目标位置（每帧逼近剩余距离的一半，约 0.2s），
        而不是瞬间甩到底；期间用户向上滚立即中止。
        AI 尚未回复时目标=用户气泡旁；AI 开始输出后 scroll_to_end 自动接管跟随。"""
        self._auto_scroll = True
        # 先撤掉旧的贴底/对齐任务：不撤的话它们的 yview_moveto(1.0) 会瞬间
        # 跳到底，把动画整个顶掉（实测 glide 一步都没走就被拉到底）
        for job_attr in ("_align_job", "_end_job"):
            job = getattr(self, job_attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, job_attr, None)
        self._glide_steps = 0
        self._glide_target = None   # 第一帧布局稳定后再算锚点（新建行未 mapped 时算不准）
        self._gliding = True
        self._glide_next()

    def _glide_next(self):
        try:
            if not self._auto_scroll:
                return                     # 用户中途往上滚了，别拽人
            self.canvas.update_idletasks()
            first, last = self.canvas.yview()
            target = self._glide_target
            if target is None:             # 第一帧：行已布局，锚点才算得准
                target = self._anchor_frac()
                self._glide_target = target
                self._gliding = target < 0.999
                if target >= 0.999:
                    self.scroll_to_end(force=True)
                    return
            d = target - first
            if abs(d) < 0.012 or self._glide_steps > 14:
                self._gliding = False
                self.canvas.yview_moveto(target)
                if target >= 0.999:
                    self.scroll_to_end(force=True)   # 真到底才交给贴底任务
                self._glide_target = 1.0
                return
            self._glide_steps += 1
            self.canvas.yview_moveto(first + d * 0.5)
            self.after(16, self._glide_next)
        except Exception:
            self._gliding = False
            self.scroll_to_end(force=True)

    def hide_latest_button(self):
        if self._latest_btn:
            try:
                self._latest_btn.place_forget()
            except Exception:
                pass

    def jump_to_latest(self):
        """点「跳到最新」：强制回到底部，并恢复跟随状态。"""
        self._auto_scroll = True
        try:
            self.scroll_to_end(force=True)
        except Exception:
            pass
        self.hide_latest_button()
        try:
            self.on_scroll(True)
        except Exception:
            pass

    def show_latest_button(self, text, command):
        if self._latest_btn is None:
            self._latest_btn = tk.Label(self, text=text, bg=self.th["accent"],
                                        fg="#ffffff", font=FONT_SMALL, cursor="hand2",
                                        padx=10, pady=3)
        else:
            self._latest_btn.configure(text=text)
        self._latest_btn.bind("<Button-1>", lambda e: command())
        self._latest_btn.place(relx=0.5, rely=0.94, anchor="center")

    # ---- 消息构建 ----
    def _slot(self, side="left", pady=(4, 4)):
        row = tk.Frame(self.inner, bg=self.th["bg_primary"])
        if side == "right":
            row.pack(fill=tk.X, anchor="e", padx=(120, 16), pady=pady)
        elif side == "center":
            row.pack(fill=tk.X, padx=16, pady=pady)
        else:
            row.pack(fill=tk.X, anchor="w", padx=(16, 120), pady=pady)
        self._trim_rows()
        # 新行加入后立刻同步内容高度：显式 item 高度不会自己长，
        # 不同步的话 inner 会冻在旧高度、子窗口全部 unmap（气泡空白）。
        self._request_sync()
        return row

    # ---- 内存 / 滚动保护：只保留最近若干条消息的实体控件 ----
    #
    # 每条消息都是一堆真窗口（Frame/Label/Text），几百条之后滚动要重排全部子窗口，
    # 既卡又吃内存。超出上限就把最早的收掉，顶上留一行"上面还有 N 条"占位。
    # 历史在会话文件里，不会真的丢。

    def _trim_rows(self):
        if not self._auto_scroll:
            # 用户正往回看，这时删内容会让视图乱跳；等回到底部再收
            return
        try:
            kids = [w for w in self.inner.winfo_children() if w is not self._top_ph]
        except Exception:
            return
        over = len(kids) - self.max_live_rows
        if over <= 0:
            return
        for row in kids[:over]:
            self._forget_wraps(row)
            try:
                row.destroy()
            except Exception:
                pass
            self._hidden_rows += 1
        self._sync_top_ph()

    def _forget_wraps(self, root_w):
        """销毁一条消息后清掉 _wraps 里属于它的引用，否则控件回收不了。"""
        try:
            dead = set()
            stack = [root_w]
            while stack:
                w = stack.pop()
                dead.add(str(w))
                try:
                    stack.extend(w.winfo_children())
                except Exception:
                    pass
            self._wraps = [(w, r) for (w, r) in self._wraps if str(w) not in dead]
        except Exception:
            pass

    def _sync_top_ph(self):
        if self._hidden_rows <= 0:
            return
        txt = _tr("▲ 上面还有 %d 条较早的消息（已折叠以节省内存，完整内容在会话记录里）",
                 "▲ %d earlier messages folded to save memory (full text stays in the chat file)") \
              % self._hidden_rows
        try:
            if self._top_ph is not None and self._top_ph.winfo_exists():
                self._top_ph.configure(text=txt)
                return
        except Exception:
            self._top_ph = None
        try:
            lb = tk.Label(self.inner, text=txt, bg=self.th["bg_primary"],
                          fg=self.th["fg_tertiary"], font=FONT_TINY, anchor="w", pady=2)
            kids = self.inner.winfo_children()
            if kids:
                lb.pack(fill=tk.X, before=kids[0])
            else:
                lb.pack(fill=tk.X)
            self._top_ph = lb
        except Exception:
            pass

    def note(self, kind, text):
        """居中提示：hint(灰字) / warn(红字) / error(红底卡片)。"""
        th = self.th
        if kind == "error":
            row = self._slot("center")
            card = tk.Frame(row, bg=th["bg_error"])
            card.pack(fill=tk.X)
            lb = tk.Label(card, text="▲ " + text, bg=th["bg_error"], fg=th["red"],
                          font=FONT_SMALL, justify="left", wraplength=1, padx=10, pady=6)
            lb.pack(fill=tk.X)
            self.register_wrap(lb, 0.9)
            return lb
        row = self._slot("center", pady=(2, 2))
        lb = tk.Label(row, text=text, bg=th["bg_primary"],
                      fg=th["red"] if kind == "warn" else th["fg_tertiary"],
                      font=FONT_SMALL, anchor="w")
        lb.pack(fill=tk.X)
        if kind == "hint":
            lb.configure(justify="center")
            self.register_wrap(lb, 0.9)
        return lb

    def _fit_user_wrap(self, lb):
        """用户气泡贴内容：短消息单行收窄（wraplength=0），长消息才换行。
        固定 wraplength 会让 Label 请求宽度恒等于换行宽度，短消息也撑出
        一大块空泡——"气泡长度要根据实际内容变化"就是这里。"""
        try:
            import tkinter.font as _tkf
            max_w = max(int(self._width * 0.6), 120)
            nat = _tkf.Font(font=FONT).measure(str(lb.cget("text")))
            lb.configure(wraplength=0 if nat <= max_w - 24 else max_w)
        except Exception:
            pass

    def add_user(self, text):
        row = self._slot("right")
        card = RoundCard(row, self.th["bg_user"], radius=10)
        card.pack(anchor="e")
        # 关键：Label 的父控件必须是 card 自己。
        # 之前 master=row、却被当成 card 的 window item 显示（跨父渲染），
        # Tk 在滚动重绘时会把内容画到可视区外——表现就是"只有气泡没有文字"，
        # 而且时好时坏（取决于滚动/重绘时机），探针里碰巧是好的。
        lb = tk.Label(card, text=text, bg=self.th["bg_user"], fg=self.th["fg_user"],
                      font=FONT, justify="left", wraplength=1, padx=0, pady=0)
        card.set_body(lb, padx=12, pady=10)
        make_label_copyable(lb, lambda: text)
        self._wraps.append((lb, None))     # None=用户气泡，resize 时走贴内容逻辑
        self._fit_user_wrap(lb)
        self._last_user_row = row    # glide 锚点：发送后停在这条气泡旁

    # ---- 流式输出气泡 ----
    def stream_begin(self):
        if self._stream_tb is not None:
            self.stream_discard()
        row = self._slot("left")
        card = tk.Frame(row, bg=self.th["bg_card"], highlightbackground=self.th["border"],
                        highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True)
        t = tk.Text(card, wrap=tk.WORD, font=FONT, bg=self.th["bg_card"],
                    fg=self.th["fg_primary"], relief="flat", borderwidth=0,
                    padx=12, pady=10, cursor="arrow", spacing2=3, spacing3=2)
        t.pack(fill=tk.BOTH, expand=True)
        t.configure(state=tk.DISABLED)
        self._attach_wheel(t)
        self._stream_row = row
        self._stream_card = card
        self._stream_tb = t
        self._stream_text = ""

    def stream_append(self, piece):
        if self._stream_tb is None:
            self.stream_begin()
        self._stream_text += piece
        try:
            t = self._stream_tb
            t.configure(state=tk.NORMAL)
            t.insert("end", piece)
            # 中间态太长只留尾部，最终答复会用 markdown 气泡完整重渲染
            lines = int(t.index("end-1c").split(".")[0])
            if lines > 400:
                t.delete("1.0", "end-300l")
            t.configure(state=tk.DISABLED)
            t.see("end")
        except Exception:
            pass
        self.scroll_to_end()

    def stream_push(self, piece):
        """正文增量入口：先攒着，40ms 合并刷一次。

        一个 token 一个事件地 insert 到 Text 会把主循环占满——打字和滚动都得排队，
        表现出来就是"输入框卡死""上下滚不动"。合并后一秒最多刷 25 次。
        """
        self._delta_buf.append(piece)
        if self._delta_job is None:
            self._delta_job = self.after(40, self._flush_delta)
        if len(self._delta_buf) > 60:      # 攒太多了立刻刷，别让字一直不出来
            self._flush_delta()

    def _flush_delta(self):
        if self._delta_job is not None:
            try:
                self.after_cancel(self._delta_job)
            except Exception:
                pass
            self._delta_job = None
        if not self._delta_buf:
            return
        piece = "".join(self._delta_buf)
        self._delta_buf = []
        self.stream_append(piece)

    def stream_fold(self):
        """这一步其实是工具调用前的叙述文字：收走并清掉临时气泡，返回文字。"""
        self._flush_delta()
        if self._stream_tb is None:
            return ""
        txt = self._stream_text
        self.stream_discard()
        return txt

    def stream_discard(self):
        self._delta_buf = []
        if self._delta_job is not None:
            try:
                self.after_cancel(self._delta_job)
            except Exception:
                pass
            self._delta_job = None
        # 必须连 row 一起销毁：只销毁卡片会留下一个保持原高度的空 Frame，
        # 界面上就是"一大块空白，气泡离得很远"（实测空行残留 550px）
        if self._stream_row is not None:
            try:
                self._stream_row.destroy()
            except Exception:
                pass
        self._stream_row = None
        if self._stream_card is not None:
            try:
                self._stream_card.destroy()
            except Exception:
                pass
        self._stream_card = None
        self._stream_tb = None
        self._stream_text = ""

    # ---- 实时思考卡片 ----
    # 思考中：标题可点，展开能看到正在冒出来的思考内容；
    # 思考结束：自动收起并解除点击（按用户要求，结束后不再展开查看）。

    def think_begin(self):
        self.think_discard()
        row = self._slot("left", pady=(2, 2))
        head = tk.Label(row, text="◇ %s" % self.t["thinking"], bg=self.th["bg_primary"],
                        fg=self.th["fg_tertiary"], font=FONT_SMALL, anchor="w",
                        cursor="hand2")
        head.pack(fill=tk.X)
        body = tk.Frame(row, bg=self.th["bg_primary"])
        t = tk.Text(body, wrap=tk.WORD, font=FONT_SMALL, bg=self.th["bg_primary"],
                    fg=self.th["fg_tertiary"], relief="flat", borderwidth=0,
                    padx=10, pady=4, height=6, spacing2=2)
        t.pack(fill=tk.X)
        make_copyable(t)
        self._attach_wheel(t)
        state = {"open": False}

        def toggle(_e=None):
            th = self._think
            if th is None or not th["live"]:
                return                      # 思考结束后不再支持展开
            if state["open"]:
                body.pack_forget()
            else:
                body.pack(fill=tk.X)
                # Tk 8.6.9 怪癖：行内首次 pack 偶发卡在 1x1 永不映射，拆了重装即好
                def _ensure_mapped(_w=body):
                    try:
                        if _w.winfo_exists() and not _w.winfo_ismapped():
                            _w.pack_forget()
                            _w.pack(fill=tk.X)
                    except Exception:
                        pass
                try:
                    self.after_idle(_ensure_mapped)
                except Exception:
                    pass
                self.scroll_to_end()
                self._request_sync()
            state["open"] = not state["open"]
            head.configure(text=self._think_head())

        head.bind("<Button-1>", toggle)
        self._think = {"row": row, "head": head, "body": body, "t": t,
                       "state": state, "toggle": toggle, "live": True,
                       "n": 0, "t0": time.time(), "trunc": False}
        head.configure(text=self._think_head())
        return head, t

    def _think_head(self):
        th = self._think
        if not th:
            return ""
        if not th["live"]:
            return "◇ 思考完成（%d 字 · %.1f 秒）" % (th["n"], time.time() - th["t0"])
        mark = "▾" if th["state"]["open"] else "▸"
        return "%s ◇ 思考中…（点击%s）· %d 字" % (
            mark, "收起" if th["state"]["open"] else "展开", th["n"])

    def think_push(self, piece):
        """思考碎片攒起来，40ms 刷一次（和正文同理，防卡顿）。"""
        if self._think is None:
            self.think_begin()
        self._think_buf.append(piece)
        if self._think_job is None:
            self._think_job = self.after(40, self._flush_think_buf)
        if len(self._think_buf) > 60:
            self._flush_think_buf()

    def _flush_think_buf(self):
        if self._think_job is not None:
            try:
                self.after_cancel(self._think_job)
            except Exception:
                pass
            self._think_job = None
        if not self._think_buf:
            return
        piece = "".join(self._think_buf)
        self._think_buf = []
        self.think_append(piece)

    def think_append(self, text):
        if self._think is None:
            self.think_begin()
        th = self._think
        if not text or th is None:
            return
        t = th["t"]
        if th["trunc"]:
            return
        try:
            cur_len = len(t.get("1.0", "end-1c"))
        except Exception:
            cur_len = 0
        limit = 6000
        if cur_len + len(text) > limit:
            try:
                t.configure(state=tk.NORMAL)
                t.insert("end", _tr("\n…（思考内容过长，这里只显示前 %d 字）",
                                            "\n... (thinking is long, showing the first %d characters)") % limit)
                t.configure(state=tk.DISABLED)
            except Exception:
                pass
            th["trunc"] = True
            return
        try:
            t.configure(state=tk.NORMAL)
            t.insert("end", text)
            t.configure(state=tk.DISABLED)
            th["n"] += len(text)
            lines = int(t.index("end-1c").split(".")[0])
            t.configure(height=min(max(lines, 1), 18))
            th["head"].configure(text=self._think_head())
        except Exception:
            pass
        if th["state"]["open"]:
            self.scroll_to_end()

    def think_finish(self):
        """思考结束：收起内容并解除点击（结束后不再展开查看）。"""
        self._flush_think_buf()
        th = self._think
        if not th or not th["live"]:
            return
        th["live"] = False
        try:
            th["body"].pack_forget()
            th["head"].unbind("<Button-1>")
            th["head"].configure(cursor="arrow", text=self._think_head())
        except Exception:
            pass
        self.scroll_to_end()

    def think_discard(self):
        self._think_buf = []
        self._think_job = None
        th = self._think
        if th is None:
            return
        try:
            th["row"].destroy()
        except Exception:
            pass
        self._think = None

    def add_assistant(self, md_text, disclaimer="", usage_line=""):
        row = self._slot("left")
        card = RoundCard(row, self.th["bg_card"], radius=10,
                         outline=self.th["border"], wide=True)
        card.pack(fill=tk.X)
        t = tk.Text(card, wrap=tk.WORD, font=FONT, bg=self.th["bg_card"],
                    fg=self.th["fg_primary"], relief="flat", borderwidth=0,
                    padx=2, pady=2, cursor="arrow", spacing2=3, spacing3=2)
        # 先按目标像素宽换算出字符列宽：未映射的 Text 实际宽度是 1px，
        # 不设列宽的话 displaylines 会按 1px 算出几百行，把气泡高度永久撑爆。
        try:
            import tkinter.font as _tkf
            _avg = max(_tkf.Font(font=FONT).measure("0"), 4)
            _chars = max(int((self._width - 56) / _avg), 20)
            t.configure(width=_chars)
        except Exception:
            pass
        card.set_body(t, padx=12, pady=10)
        MarkdownText(t, self.th).render(md_text)
        make_copyable(t)
        self._attach_wheel(t)
        # 用量行（比免责声明醒目一档，让人看得见花了多少 token）
        ul = None
        if usage_line:
            ul = tk.Label(row, text=usage_line, bg=self.th["bg_primary"],
                          fg=self.th["fg_secondary"], font=FONT_SMALL, anchor="w")
            ul.pack(fill=tk.X, pady=(3, 0))
        # 官方免责声明
        dl = tk.Label(row, text=disclaimer, bg=self.th["bg_primary"],
                      fg=self.th["fg_tertiary"], font=FONT_TINY, anchor="w")
        dl.pack(fill=tk.X, pady=(1, 0))
        return t, dl

    def _collapsible(self, parent, head_text, opened=False, color=None):
        """可折叠块的公共骨架：返回 (head, body, state, toggle)。"""
        outer = tk.Frame(parent, bg=self.th["bg_primary"])
        outer.pack(fill=tk.X)
        head = tk.Label(outer, text=head_text, bg=self.th["bg_primary"],
                        fg=color or self.th["fg_tertiary"], font=FONT_SMALL,
                        cursor="hand2", anchor="w")
        head.pack(fill=tk.X)
        body = tk.Frame(outer, bg=self.th["bg_primary"])
        state = {"open": False}

        def toggle(_e=None):
            if state["open"]:
                body.pack_forget()
            else:
                body.pack(fill=tk.X)
                # Tk 8.6.9 怪癖：嵌在画布窗口层级里的行，首次 pack 偶发
                # 卡死不布局（控件停在 1x1 永不映射，看起来像"点了没反应"）。
                # idle 后还没映射就拆了重装一次，实测一装就好。
                def _ensure_mapped(_w=body):
                    try:
                        if _w.winfo_exists() and not _w.winfo_ismapped():
                            _w.pack_forget()
                            _w.pack(fill=tk.X)
                    except Exception:
                        pass
                try:
                    self.after_idle(_ensure_mapped)
                except Exception:
                    pass
                self.scroll_to_end()
            state["open"] = not state["open"]
            # 展开/收起改变了行高：画布 item 高度是显式管理的，不同步的话
            # 新展开的内容在旧高度之外，会被 unmap（看起来像"点了没反应"）
            self._request_sync()

        head.bind("<Button-1>", toggle)
        if opened:
            toggle()
        return head, body, state, toggle

    def add_thinking(self, text, expanded=False):
        row = self._slot("left")
        head, body, state, toggle = self._collapsible(
            row, "◇ " + self.t["thinking"], opened=expanded)
        t = tk.Text(body, wrap=tk.WORD, font=FONT_SMALL, bg=self.th["bg_primary"],
                    fg=self.th["fg_tertiary"], relief="flat", borderwidth=0,
                    padx=8, pady=4, height=min(max(text.count("\n") + 1, 1), 16))
        t.insert("1.0", text)
        make_copyable(t)
        self._attach_wheel(t)
        _bind_fit(t, min_h=1, max_h=16)
        t.pack(fill=tk.X)
        return head, t

    def add_tool_card(self, name, body_text, result_text="", title=None):
        row = self._slot("left")
        card = RoundCard(row, self.th["bg_tool"], radius=10,
                         outline=self.th["border"], wide=True)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=self.th["bg_tool"])
        card.set_body(inner, padx=2, pady=2)
        head = tk.Label(inner, text=title or ("▣ %s" % TOOL_ZH.get(name, name)),
                        bg=self.th["bg_tool"], fg=self.th["fg_secondary"],
                        font=FONT_SMALL, anchor="w", cursor="hand2", padx=8, pady=5)
        head.pack(fill=tk.X)
        body = tk.Frame(inner, bg=self.th["bg_tool"])
        t = tk.Text(body, wrap=tk.WORD, font=MONO_SMALL, bg=self.th["bg_code"],
                    fg=self.th["fg_secondary"], relief="flat", borderwidth=0,
                    padx=8, pady=6)
        content = body_text or ""
        if result_text:
            content += ("\n" if content else "") + _tr("结果：", "Result:") + "\n%s" % result_text
        t.insert("1.0", content.strip() or _tr("（无输出）", "(no output)"))
        make_copyable(t)
        self._attach_wheel(t)
        _bind_fit(t, min_h=1, max_h=20)
        t.pack(fill=tk.X)

        state = {"open": False}

        def toggle(_e=None):
            if state["open"]:
                body.pack_forget()
                state["open"] = False
            else:
                body.pack(fill=tk.X, padx=6, pady=(0, 6))
                state["open"] = True
                self.scroll_to_end()

        head.bind("<Button-1>", toggle)
        # 短结果自动展开
        if result_text and len(result_text) < 400:
            toggle()
        return head, t, state, toggle



    def add_permission(self, desc, title, t_allow, t_deny, on_result, t_always=None):
        row = self._slot("left")
        card = RoundCard(row, self.th["bg_permission"], radius=10,
                         outline=self.th["yellow"], wide=True)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=self.th["bg_permission"])
        card.set_body(inner, padx=2, pady=2)
        head = tk.Label(inner, text="⚠ " + title, bg=self.th["bg_permission"],
                        fg=self.th["yellow"], font=FONT_BOLD, anchor="w",
                        padx=8, pady=6, wraplength=720, justify="left")
        head.pack(fill=tk.X)
        body = tk.Frame(inner, bg=self.th["bg_permission"])
        t = tk.Text(body, wrap=tk.WORD, font=MONO_SMALL, bg=self.th["bg_permission"],
                    fg=self.th["fg_primary"], relief="flat", borderwidth=0)
        t.insert("1.0", desc)
        make_copyable(t)
        self._attach_wheel(t)
        _bind_fit(t, min_h=1, max_h=12)
        t.pack(fill=tk.X)
        btns = tk.Frame(inner, bg=self.th["bg_permission"])
        done = {"v": False}

        def choose(v, always=False):
            if done["v"]:
                return
            done["v"] = True
            # 选完立刻收起：命令正文和按钮都撤掉，只留一行结论，
            # 免得卡片一直杵在对话里让人以为没生效
            body.pack_forget()
            btns.pack_forget()
            first = (desc.strip().splitlines() or [_tr("（无描述）", "(no description)")])[0][:70]
            if always:
                txt = "⚔ " + (t_always or TEXT["perm_always_ok"])
                fg = self.th["accent"]
            elif v:
                txt = "✓ " + TEXT["perm_ok"]
                fg = self.th["green"]
            else:
                txt = "✕ " + TEXT["perm_no"]
                fg = self.th["fg_tertiary"]
            head.configure(text="%s  ·  %s" % (txt, first), fg=fg)
            self.scroll_to_end()
            on_result(v, always)

        btns.pack(fill=tk.X, padx=8, pady=8)
        RoundButton(btns, "✓ " + t_allow, lambda: choose(True),
                    self.th["green"], "#ffffff", FONT_SMALL).pack(side=tk.LEFT, padx=(0, 8))
        RoundButton(btns, "✕ " + t_deny, lambda: choose(False),
                    self.th["bg_chip"], self.th["fg_secondary"], FONT_SMALL).pack(side=tk.LEFT)
        RoundButton(btns, "⚔ " + (t_always or TEXT["perm_always"]),
                    lambda: choose(True, True),
                    self.th["bg_chip"], self.th["accent"], FONT_SMALL).pack(side=tk.RIGHT)
        return card


# ---------------------------------------------------------------- 应用主体

def _timed_render(fn):
    """记录一次界面渲染耗时（占比统计三段之一）。"""
    def wrapper(*a, **k):
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            try:
                lim = getattr(engine, "limits", None)
                if lim is not None:
                    lim.record("render", (time.perf_counter() - t0) * 1000.0,
                               getattr(fn, "__name__", "render"))
            except Exception:
                pass
    wrapper.__name__ = getattr(fn, "__name__", "render")
    return wrapper


class MingShuApp(object):
    def __init__(self):
        if not os.path.exists(engine.CONFIG_PATH):
            engine.write_default_config()
        # 注意：不用 engine.load_config()——它会在缺 Key 时直接退出，
        # 而图形界面要能启动并在对话里提示去设置。
        self.cfg = engine.read_config()
        # 三道资源墙：内存(Job) / CPU(线程优先级) / I/O(后台模式)。
        # 墙由内核执行，代码写漏也不会拖垮用户整机。
        try:
            self.limits_state = engine.boot_limits(self.cfg)
        except Exception as e:
            self.limits_state = {"error": repr(e)}
        self.store = SessionStore()
        state = load_ui_state()
        self.mode = state.get("mode", "agent")           # agent / plan / ask
        self.perm_mode = state.get("perm", "ask")        # auto/ask/strict/locked
        self.deep_think = False
        self.goal_paused = False

        self.th = THEME
        # 界面语言：首次默认中文；点切换按钮后写进 ui_state.json，下次开机沿用
        self.lang = (state.get("lang") or "zh")
        UI_LANG[0] = self.lang
        self.t = TEXT_EN if self.lang == "en" else TEXT

        self.root = tk.Tk()
        self.root.title("%s  %s" % (self.t["app_title"], APP_BUILD))
        self.root.geometry("1120x740")
        self.root.minsize(880, 560)
        self.root.configure(bg=self.th["bg_primary"])
        # DPI 缩放：125%/150% 下把 Tk scaling 和窗口尺寸一起放大，
        # 100% 时什么都不做（零风险）。不调的话字会很小或坐标系与屏幕差一截。
        try:
            dpi = float(self.root.winfo_fpixels("1i"))
            if abs(dpi - 96.0) > 1.0:
                self.root.tk.call("tk", "scaling", dpi / 72.0)
                k = dpi / 96.0
                self.root.geometry("%dx%d" % (int(1120 * k), int(740 * k)))
        except Exception:
            pass
        # 窗口/任务栏图标
        # 1) iconbitmap 用 .ico（部分 Tk 版本对 PNG 压缩格式的 ico 读不了）
        # 2) iconphoto 用 PNG 兜底——这条在 Win7 上最可靠，任务栏也跟随
        try:
            ico = _asset_path("mingshu.ico")
            if ico and os.path.isfile(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass
        try:
            png = _asset_path("mingshu.png")
            if png and os.path.isfile(png):
                big = tk.PhotoImage(file=png)      # 256
                mid = big.subsample(8, 8)          # 32，任务栏用这个
                small = big.subsample(16, 16)      # 16
                self._icon_refs = (big, mid, small)   # 必须留引用，否则被 GC
                self.root.iconphoto(True, big, mid, small)
        except Exception:
            pass

        self.queue = queue.Queue()
        self.running = False
        # 后台预热：并发测一遍各线路延迟并缓存结果，等真正发消息时直接用最快的
        # （只在 assistant.ini 里配了 mirrors 才会真的发请求）
        try:
            threading.Thread(target=lambda: engine.pick_base(self.cfg),
                             daemon=True).start()
        except Exception:
            pass
        self.stop_event = threading.Event()
        self.pending_msgs = []          # 排队发送的消息
        self.gen_id = 0                 # 世代令牌：打断后旧线程的 final 事件整体作废
        self._pending_after = None      # 排队消息的 after 回调 id（打断时要撤销）
        self.cur_session = None
        self.think_buffer = []
        self.last_tool_card = None
        self.perm_waiting = False
        self.turn_tokens = 0
        self.turn_usage = {}            # 本轮各分项 token（prompt/completion/reasoning）
        self.session_tokens = 0         # 本会话累计
        self._approver = None           # 当前这轮的审批器（"高级权限"要即时改它）
        self._attachments = []          # 待发送的文件（拖进来、选进来或粘贴的）
        self._preview_win = None        # 附件悬停大图预览窗口
        self._preview_img = None
        self._preview_job = None
        self._toasts = []               # 右下角提醒（最多同时 3 条）
        self._drop_ok = False

        self._ensure_api_md()
        self._build_ui()
        self._bind_keys()
        # 拖文件进窗口（Win32 WM_DROPFILES）；失败就只剩「文件」按钮，不影响使用
        # 拖放出过原生崩溃，留一个配置开关：assistant.ini 里 [assistant] enable_drop = false
        self._drop_enabled = self.cfg.getboolean("assistant", "enable_drop", fallback=True)
        if self._drop_enabled:
            # 拖放挂钩要递归枚举全部 HWND，是启动流程里最重的一步；
            # 挪到首帧之后再挂，窗口能早百来毫秒出来，功能不受影响
            self.root.after(80, self._enable_drop_late)
        # 让 Tk 回调里的异常也留下痕迹（pythonw 下 stderr 是黑洞）
        self.root.report_callback_exception = self._on_tk_error

        # 恢复或新建会话
        sessions = self.store.list()
        last_id = state.get("last_session")
        target = None
        if last_id:
            target = self.store.get(last_id)
        if target is None and sessions:
            target = sessions[0]
        if target is None:
            target = self.store.create()
        self.switch_session(target["id"])
        self._refresh_sessions()
        # 启动时回收孤儿记忆：已被删除的会话在 facts.json 里的残留一次清干净
        try:
            engine.Memory(facts_path=engine.FACTS_PATH).purge_orphan_facts(
                [s["id"] for s in self.store.list()])
        except Exception:
            pass

        days = self.cfg.getint("agent", "cleanup_days", fallback=0) if \
            self.cfg.has_option("agent", "cleanup_days") else 0
        if days > 0:
            self.store.prune(days)
            self._refresh_sessions()

        self.root.after(60, self._pump)
        self.root.after(400, self._hotkey_tick)   # Ctrl+Alt+Q 全局中断
        self.root.after(20 * 1000, self._sched_tick)      # 20 秒一轮，够细又不吵
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ 界面构建

    def _enable_drop_late(self):
        """首帧之后再挂 Win32 拖放（见 __init__ 里的注释）。"""
        try:
            self._drop_ok = enable_file_drop(self.root, self._on_files_dropped)
            self._drain_drop_queue()
        except Exception as e:
            print("[drop] enable failed: %r" % (e,))

    def _ensure_api_md(self):
        """首次运行生成 api.md（用当前 ini 的值作为第一个预设）。"""
        try:
            if os.path.isfile(engine.API_MD):
                return
            presets = [("deepseek", {
                "label": "DeepSeek（当前使用，便宜）",
                "base_url": self.cfg.get("llm", "base_url", fallback=""),
                "api_key": self.cfg.get("llm", "api_key", fallback=""),
                "model": self.cfg.get("llm", "model", fallback=""),
            }), ("qwen", {
                "label": "通义千问",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "",
                "model": "qwen-plus",
            })]
            engine.save_api_presets(presets, active="deepseek")
        except Exception:
            pass

    def _build_ui(self):
        th = self.th
        self.outer = tk.Frame(self.root, bg=th["bg_primary"])
        self.outer.pack(fill=tk.BOTH, expand=True)

        # 侧边栏
        self.sidebar = tk.Frame(self.outer, bg=th["bg_secondary"], width=252)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        # 右侧主区
        self.main = tk.Frame(self.outer, bg=th["bg_primary"])
        self.main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self._build_header()
        self._build_chat()
        self._build_composer()

    def _build_sidebar(self):
        th = self.th
        for w in self.sidebar.winfo_children():
            w.destroy()
        pad = dict(padx=12)

        # 品牌区
        brand = tk.Frame(self.sidebar, bg=th["bg_secondary"])
        brand.pack(fill=tk.X, pady=(14, 10), **pad)
        tk.Label(brand, text=_tr("◆ 明枢Win7", "◆ MingShu Win7"), bg=th["bg_secondary"],
                 fg=th["fg_primary"], font=FONT_TITLE, anchor="w").pack(side=tk.LEFT)
        tk.Label(brand, text="Win7", bg=th["bg_chip"], fg=th["fg_secondary"],
                 font=FONT_TINY, padx=6, pady=1).pack(side=tk.LEFT, padx=(8, 0))

        # 新对话
        self.btn_new = RoundButton(self.sidebar, self.t["new_chat"],
                                   self.new_session, th["accent_brand"],
                                   th["fg_on_brand"], FONT_BOLD, pady=7)
        self.btn_new.pack(fill=tk.X, **pad)

        # 搜索
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *a: self._refresh_sessions())
        se = tk.Entry(self.sidebar, textvariable=self.search_var, font=FONT_SMALL,
                      bg=th["bg_input"], fg=th["fg_primary"], relief="flat",
                      insertbackground=th["fg_primary"])
        se.pack(fill=tk.X, pady=(8, 4), ipady=4, **pad)
        se.bind("<FocusIn>", lambda e: se.configure(fg=th["fg_primary"]))
        self.search_entry = se

        tk.Label(self.sidebar, text=self.t["recent"], bg=th["bg_secondary"],
                 fg=th["fg_tertiary"], font=FONT_TINY, anchor="w").pack(fill=tk.X,
                                                                       pady=(6, 2), **pad)
        self.session_box = tk.Frame(self.sidebar, bg=th["bg_secondary"])
        self.session_box.pack(fill=tk.BOTH, expand=True)

        # 导航
        nav = tk.Frame(self.sidebar, bg=th["bg_secondary"])
        nav.pack(fill=tk.X, pady=(8, 4), **pad)
        self.nav_btns = {}
        # 语言切换（放在「对话」上方）
        self.btn_lang = RoundButton(nav, self.t["lang_btn"], self.toggle_lang,
                                    th["bg_chip"], th["fg_secondary"], FONT_SMALL,
                                    radius=7, padx=10, pady=4)
        self.btn_lang.pack(fill=tk.X, pady=(0, 4))
        for key, icon in (("chat", "●"), ("terminal", "▶"), ("settings", "⚙"),
                          ("help", "?")):
            b = RoundButton(nav, "%s  %s" % (icon, self.t["nav_" + key]),
                            lambda k=key: self._nav(k),
                            th["bg_secondary"], th["fg_secondary"], FONT_SMALL,
                            radius=7, padx=10, pady=4)
            b.pack(fill=tk.X, pady=1)
            self.nav_btns[key] = b

        # 底部控制
        bottom = tk.Frame(self.sidebar, bg=th["bg_secondary"])
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 10), **pad)
        self.btn_perm = tk.Button(bottom, text="", font=FONT_SMALL, relief="flat",
                                  anchor="w", cursor="hand2", bg=th["bg_secondary"],
                                  fg=th["fg_secondary"],
                                  command=self._cycle_perm)
        self.btn_perm.pack(fill=tk.X, pady=1)
        tk.Label(bottom, text=_tr("明枢Win7 · %s · 纯标准库", "MingShu Win7 · %s · stdlib only") % APP_BUILD,
                 bg=th["bg_secondary"], fg=th["fg_tertiary"],
                 font=FONT_TINY, anchor="w").pack(fill=tk.X, pady=(6, 0))

    def _build_header(self):
        th = self.th
        self.header = tk.Frame(self.main, bg=th["bg_primary"], height=46)
        self.header.pack(fill=tk.X, padx=12, pady=(10, 4))
        self.header.pack_propagate(False)

        self.btn_toggle = tk.Button(self.header, text="☰", font=FONT, relief="flat",
                                    bg=th["bg_primary"], fg=th["fg_secondary"],
                                    cursor="hand2", command=self._toggle_sidebar)
        self.btn_toggle.pack(side=tk.LEFT)

        self.title_lb = tk.Label(self.header, text="", bg=th["bg_primary"],
                                 fg=th["fg_primary"], font=FONT_BOLD, anchor="w")
        self.title_lb.pack(side=tk.LEFT, padx=(10, 14))

        self.chips = {}
        self._chip("mode", self._cycle_mode)
        self._chip("model", self._open_settings)
        self._chip("workspace", self._workspace_menu)

    def _chip(self, key, command):
        th = self.th
        c = tk.Label(self.header, text="", bg=th["bg_chip"], fg=th["fg_secondary"],
                     font=FONT_SMALL, cursor="hand2", padx=10, pady=3)
        c.pack(side=tk.LEFT, padx=(0, 8))
        c.bind("<Button-1>", lambda e: command())
        self.chips[key] = c

    def _build_chat(self):
        th = self.th
        self._chat_wrap = tk.Frame(self.main, bg=th["bg_primary"])
        self._chat_wrap.pack(fill=tk.BOTH, expand=True, padx=(4, 10))
        self.chat = ChatView(self._chat_wrap, th)
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.on_scroll = self._on_chat_scroll

    def _build_composer(self):
        th = self.th
        self.composer = tk.Frame(self.main, bg=th["bg_primary"])
        self.composer.pack(fill=tk.X, padx=14, pady=(4, 12))

        # 目标条
        self.goal_bar = tk.Frame(self.composer, bg=th["bg_chip"])
        self.goal_entry = tk.Entry(self.goal_bar, font=FONT_SMALL, relief="flat",
                                   bg=th["bg_input"], fg=th["fg_primary"],
                                   insertbackground=th["fg_primary"])

        # 工具栏
        tools = tk.Frame(self.composer, bg=th["bg_primary"])
        tools.pack(fill=tk.X, pady=(0, 6))
        self.tool_btns = {}
        for key in ("mode", "model", "workspace", "goal", "think", "palette"):
            b = RoundButton(tools, "", lambda k=key: self._toolbar(k),
                            th["bg_primary"], th["fg_secondary"], FONT_SMALL,
                            radius=8, padx=8, pady=4)
            b.pack(side=tk.LEFT, padx=(0, 4))
            self.tool_btns[key] = b
        self.btn_attach = RoundButton(tools, "▤ " + self.t["attach"],
                                      self._pick_files,
                                      th["bg_primary"], th["accent"], FONT_SMALL,
                                      radius=8, padx=8, pady=4)
        self.btn_attach.pack(side=tk.RIGHT, padx=(4, 0))

        # 待发送的附件：拖进来的文件显示在这里，发送后自动清空
        self.attach_row = tk.Frame(self.composer, bg=th["bg_primary"])
        self.attach_row.pack(fill=tk.X, pady=(0, 4))
        self._refresh_attach_row()

        # 输入框 + 发送
        box = tk.Frame(self.composer, bg=th["bg_primary"])
        box.pack(fill=tk.X)
        self.input = tk.Text(box, height=3, wrap=tk.WORD, font=FONT, relief="flat",
                             bg=th["bg_input"], fg=th["fg_primary"],
                             insertbackground=th["fg_primary"], padx=10, pady=8,
                             spacing1=2, spacing2=3, spacing3=2,
                             highlightbackground=th["border_input"],
                             highlightthickness=1)
        self.input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.btn_send = RoundButton(box, "", self.on_send_click,
                                    th["accent_brand"], th["fg_on_brand"],
                                    FONT_BOLD, radius=9, padx=16, pady=8)
        self.btn_send.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        # 「打断」：生成中才出现，停掉当前轮（区别于强制发送=排队不打断）
        self.btn_stop = RoundButton(box, self.t["interrupt"], self.on_stop,
                                    th["red"], "#ffffff", FONT_BOLD,
                                    radius=9, padx=12, pady=8)

        # 阶段状态 + 提示
        self.phase_lb = tk.Label(self.composer, text="", bg=th["bg_primary"],
                                 fg=th["fg_tertiary"], font=FONT_TINY, anchor="w")
        self.phase_lb.pack(fill=tk.X, pady=(4, 0))
        self.hint_lb = tk.Label(self.composer, text=self.t["hint"], bg=th["bg_primary"],
                                fg=th["fg_tertiary"], font=FONT_TINY, anchor="w")
        self.hint_lb.pack(fill=tk.X)

        # 输入框快捷键（每次重建 composer 后重新绑定）
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<Shift-Return>", lambda e: None)
        # Ctrl+V：先看剪贴板里有没有文件/图片，有就变附件；纯文本照常粘贴
        self.input.bind("<Control-v>", self._on_paste)
        self.input.bind("<Control-V>", self._on_paste)

    # ------------------------------------------------------------ 附件

    # ---- 附件缩略图 / 预览 ----

    def _clip_dir(self):
        d = os.path.join(DATA_DIR, "clip")
        try:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _attach_photo(self, path, max_side):
        """给附件生成 PhotoImage（Tk 原生只认 png/gif/ppm 等）。失败返回 None。"""
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".gif", ".ppm", ".pgm"):
            return None
        try:
            img = tk.PhotoImage(file=path)
        except Exception:
            return None
        side = max(img.width(), img.height())
        if side > max_side:
            k = int(side / float(max_side)) + 1
            try:
                img = img.subsample(k, k)
            except Exception:
                pass
        return img

    def _refresh_attach_row(self):
        th = self.th
        for w in self.attach_row.winfo_children():
            w.destroy()
        self._preview_destroy()
        if not self._attachments:
            tk.Label(self.attach_row, text=self.t["attach_hint"], bg=th["bg_primary"],
                     fg=th["fg_tertiary"], font=FONT_TINY, anchor="w").pack(fill=tk.X)
            return
        tk.Label(self.attach_row, text=self.t["attach_count"] % len(self._attachments),
                 bg=th["bg_primary"], fg=th["fg_secondary"], font=FONT_TINY,
                 anchor="w").pack(fill=tk.X)
        chips = tk.Frame(self.attach_row, bg=th["bg_primary"])
        chips.pack(fill=tk.X, pady=(2, 0))
        for idx in range(len(self._attachments)):
            path = self._attachments[idx]
            try:
                size = os.path.getsize(path)
                size_txt = ("%dKB" % (size // 1024)) if size >= 1024 else ("%dB" % size)
            except OSError:
                size_txt = "?"
            card = tk.Frame(chips, bg=th["bg_chip"], highlightthickness=1,
                            highlightbackground=th["border"], cursor="hand2")
            card.pack(side=tk.LEFT, padx=(0, 8), pady=2)
            inner = tk.Frame(card, bg=th["bg_chip"])
            inner.pack(padx=5, pady=4)
            thumb = self._attach_photo(path, 56)
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            if thumb is not None:
                lb = tk.Label(inner, image=thumb, bg=th["bg_chip"], width=56, height=56)
                lb.image = thumb            # 防 GC
            else:
                lb = tk.Label(inner, text="[" + (ext or "file").upper() + "]",
                              bg=th["bg_chip"], fg=th["fg_secondary"],
                              font=FONT_TINY, width=8, height=4)
            lb.pack()
            name = os.path.basename(path)
            tk.Label(inner, text=(name[:16] + ("…" if len(name) > 16 else "")),
                     bg=th["bg_chip"], fg=th["fg_primary"], font=FONT_TINY).pack()
            tk.Label(inner, text=size_txt, bg=th["bg_chip"], fg=th["fg_tertiary"],
                     font=FONT_TINY).pack()
            x = tk.Label(card, text="✕", bg=th["bg_chip"], fg=th["fg_tertiary"],
                         font=FONT_TINY, padx=3, pady=0, cursor="hand2")
            x.place(relx=1.0, rely=0.0, anchor="ne")
            x.bind("<Button-1>", lambda e, i=idx: self._remove_file(i))
            for w in (card, inner, lb):
                w.bind("<Enter>", lambda e, pth=path, ww=card: self._preview_show(pth, ww))
                w.bind("<Leave>", lambda e: self._preview_later())
            card.bind("<Button-1>", lambda e, pth=path: self._open_path_safe(pth))

    def _open_path_safe(self, path):
        try:
            os.startfile(path)
        except Exception:
            pass

    # ---- 悬停大图预览 ----
    def _preview_destroy(self):
        try:
            if getattr(self, "_preview_win", None) is not None:
                self._preview_win.destroy()
        except Exception:
            pass
        self._preview_win = None
        self._preview_img = None
        try:
            if getattr(self, "_preview_job", None) is not None:
                self.root.after_cancel(self._preview_job)
        except Exception:
            pass
        self._preview_job = None

    def _preview_later(self):
        """鼠标移开稍等一下再关，避免在卡片之间移动时闪来闪去。"""
        try:
            if getattr(self, "_preview_job", None) is not None:
                self.root.after_cancel(self._preview_job)
        except Exception:
            pass
        self._preview_job = self.root.after(260, self._preview_destroy)

    def _preview_show(self, path, widget):
        try:
            if getattr(self, "_preview_job", None) is not None:
                self.root.after_cancel(self._preview_job)
                self._preview_job = None
            if getattr(self, "_preview_win", None) is not None:
                self._preview_win.destroy()
                self._preview_win = None
            img = self._attach_photo(path, 420)
            if img is None:
                return                       # 非图片：不弹窗，点卡片用系统预
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            try:
                top.attributes("-topmost", True)
            except Exception:
                pass
            th = self.th
            box = tk.Frame(top, bg=th["bg_card"], highlightbackground=th["border"],
                           highlightthickness=1)
            box.pack()
            lb = tk.Label(box, image=img, bg=th["bg_card"])
            lb.image = img
            lb.pack(padx=2, pady=2)
            try:
                size_txt = "%dx%d" % (img.width(), img.height())
            except Exception:
                size_txt = ""
            tk.Label(box, text="%s  %s" % (os.path.basename(path)[:40], size_txt),
                     bg=th["bg_card"], fg=th["fg_secondary"], font=FONT_TINY).pack(
                         fill=tk.X, padx=4, pady=(0, 3))
            top.update_idletasks()
            w = top.winfo_reqwidth()
            h = top.winfo_reqheight()
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() - h - 8
            sw = self.root.winfo_screenwidth()
            if x + w > sw - 8:
                x = sw - w - 8
            if y < 8:
                y = widget.winfo_rooty() + widget.winfo_height() + 8
            top.geometry("+%d+%d" % (max(x, 8), max(y, 8)))
            self._preview_win = top
            self._preview_img = img
        except Exception:
            pass

    # ---- Ctrl+V：粘贴剪贴板里的文件 / 图片 ----
    def _on_paste(self, event=None):
        paths = _clip_files()
        if paths:
            self._add_files(paths)
            return "break"
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out = os.path.join(self._clip_dir(), "clip_%s.png" % ts)
            saved = _clip_image_png(out)
            if saved:
                self._add_files([saved])
                self.chat.note("hint", self.t.get("paste_img", "已粘贴剪贴板图片：%s")
                               % os.path.basename(saved))
                return "break"
        except Exception:
            pass
        return None      # 纯文本：交回默认粘贴

    def _remove_file(self, idx):
        if 0 <= idx < len(self._attachments):
            del self._attachments[idx]
            self._refresh_attach_row()

    def _add_files(self, paths):
        added = 0
        for p in paths:
            if not p or not os.path.isfile(p):
                continue
            if len(self._attachments) >= 10:
                self.chat.note("warn", "▲ " + self.t["attach_too_many"])
                break
            if p not in self._attachments:
                self._attachments.append(p)
                added += 1
        if added:
            self._refresh_attach_row()

    def _pick_files(self):
        try:
            from tkinter import filedialog
            paths = filedialog.askopenfilenames(parent=self.root,
                                                title=self.t["attach_dialog"])
        except Exception:
            paths = ()
        if paths:
            self._add_files(list(paths))

    def _on_files_dropped(self, paths):
        self._add_files(paths)
        try:
            self.root.lift()
            self.input.focus_set()
        except Exception:
            pass

    def _drain_drop_queue(self):
        """拖放路径由窗口过程塞进队列，这里在 Tk 主循环里安全地取出来处理。"""
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        try:
            if _DND["queue"]:
                paths = _DND["queue"][:]
                del _DND["queue"][:]
                self._on_files_dropped(paths)
        except Exception as e:
            self._log_error("drop", e)
        try:
            self.root.after(150, self._drain_drop_queue)
        except Exception:
            pass

    def _log_error(self, tag, exc):
        try:
            with open(os.path.join(DATA_DIR, "crash.log"), "a", encoding="utf-8") as f:
                f.write("[%s] %s: %r\n" % (time.strftime("%H:%M:%S"), tag, exc))
        except Exception:
            pass

    def _on_tk_error(self, exc, val, tb):
        """Tk 回调异常：pythonw 没有控制台，必须自己记下来。"""
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(os.path.join(DATA_DIR, "crash.log"), "a", encoding="utf-8") as f:
                f.write("[%s] Tk 回调异常\n%s\n" % (time.strftime("%H:%M:%S"), text))
        except Exception:
            pass
        try:
            self.chat.note("error", _tr("▲ 内部错误（已写入 crash.log）：%s",
                                         "▲ Internal error (logged to crash.log): %s") % val)
        except Exception:
            pass

    def _on_chat_scroll(self, auto):
        if auto:
            self.chat.hide_latest_button()
        else:
            self.chat.show_latest_button(self.t["scroll_latest"], self._jump_latest)

    def _jump_latest(self):
        self.chat.jump_to_latest()

    # ------------------------------------------------------------ 键盘/导航

    def _bind_keys(self):
        # 根窗口级快捷键（重建界面不会丢失）；输入框快捷键在 _build_composer 里绑
        self.root.bind("<Escape>", lambda e: self.on_stop())
        self.root.bind("<Control-k>", lambda e: self.toggle_palette())

    def _on_enter(self, e):
        if e.state & 0x1:      # Shift+Enter = 换行
            return
        self.on_send_click()
        return "break"


    def _nav(self, key):
        if key == "chat":
            self._show_view("chat")
        elif key == "terminal":
            self._show_view("terminal")
        elif key == "settings":
            self._open_settings()
        elif key == "help":
            self._show_view("help")

    def _show_view(self, name):
        for w in self.main.winfo_children():
            w.pack_forget()
        self.header.pack(fill=tk.X, padx=12, pady=(10, 4))
        if name == "chat":
            self._chat_wrap.pack(fill=tk.BOTH, expand=True, padx=(4, 10))
        elif name == "terminal":
            self._build_terminal_view()
        else:
            self._build_help_view()
        self.composer.pack(fill=tk.X, padx=14, pady=(4, 12))
        for k, b in self.nav_btns.items():
            b.configure(fg=self.th["fg_primary"] if k == name else self.th["fg_secondary"])

    def _build_terminal_view(self):
        th = self.th
        if getattr(self, "_term_view", None):
            self._term_view.pack(fill=tk.BOTH, expand=True, padx=(4, 10))
            return
        self._term_view = tk.Frame(self.main, bg=th["bg_primary"])
        ws = self.cfg.get("agent", "workspace", fallback="").strip() or ROOT
        tk.Label(self._term_view, text=self.t["terminal_hint"] % ws, bg=th["bg_primary"],
                 fg=th["fg_tertiary"], font=FONT_TINY, anchor="w").pack(fill=tk.X)
        self.term_out = tk.Text(self._term_view, wrap=tk.WORD, font=MONO_SMALL,
                                bg=th["bg_terminal"], fg=th["fg_terminal"],
                                relief="flat", borderwidth=0, padx=8, pady=6)
        self.term_out.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        make_copyable(self.term_out)
        row = tk.Frame(self._term_view, bg=th["bg_primary"])
        row.pack(fill=tk.X, pady=(6, 0))
        self.term_in = tk.Entry(row, font=MONO_SMALL, relief="flat", bg=th["bg_input"],
                                fg=th["fg_primary"], insertbackground=th["fg_primary"])
        self.term_in.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.term_in.bind("<Return>", lambda e: self._term_run())
        tk.Button(row, text=self.t["terminal_run"], font=FONT_SMALL, relief="flat",
                  bg=th["accent_brand"], fg=th["fg_on_brand"], cursor="hand2",
                  command=self._term_run).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(row, text=self.t["terminal_clear"], font=FONT_SMALL, relief="flat",
                  bg=th["bg_chip"], fg=th["fg_secondary"], cursor="hand2",
                  command=self._term_clear).pack(side=tk.LEFT, padx=(6, 0))
        self._term_view.pack(fill=tk.BOTH, expand=True, padx=(4, 10))

    def _term_write(self, text):
        self.term_out.configure(state=tk.NORMAL)
        self.term_out.insert("end", text)
        self.term_out.see("end")

    def _term_run(self):
        cmd = self.term_in.get().strip()
        if not cmd:
            return
        self.term_in.delete(0, tk.END)
        ws = self.cfg.get("agent", "workspace", fallback="").strip() or ROOT
        self._term_write("\n> %s\n" % cmd)

        def work():
            try:
                p = subprocess.run(["cmd", "/c", cmd], cwd=ws, capture_output=True,
                                   text=True, timeout=60, **engine.hidden_kwargs())
                out = (p.stdout or "") + (p.stderr or "")
            except Exception as e:
                out = _tr("执行失败：%s", "Failed: %s") % e
            self.queue.put(("term", out))

        threading.Thread(target=work, daemon=True).start()

    def _term_clear(self):
        self.term_out.configure(state=tk.NORMAL)
        self.term_out.delete("1.0", "end")

    def _build_help_view(self):
        th = self.th
        if getattr(self, "_help_view", None):
            self._help_view.pack(fill=tk.BOTH, expand=True, padx=(4, 10))
            return
        self._help_view = tk.Frame(self.main, bg=th["bg_primary"])
        t = tk.Text(self._help_view, wrap=tk.WORD, font=FONT, relief="flat",
                    bg=th["bg_card"], fg=th["fg_primary"], padx=20, pady=16)
        t.pack(fill=tk.BOTH, expand=True)
        if UI_LANG[0] == "en":
            t.insert("end", "MingShu Win7\n", ("h1",))
            t.insert("end", "\nKeyboard\n", ("h2",))
            t.insert("end", "  Enter        Send the message\n"
                            "  Shift+Enter  New line\n"
                            "  Esc          Stop the running task\n"
                            "  Ctrl+K       Command palette\n"
                            "  Ctrl+Alt+Q   Stop from anywhere\n\n")
            t.insert("end", "Modes\n", ("h2",))
            t.insert("end", "  Agent  Full tools: list/read/search files, run commands, write, open, system info, fetch web pages\n"
                            "  Plan   Read only: looks but never changes anything (good for analysis first)\n"
                            "  Ask    Chat only: no tools at all\n\n")
            t.insert("end", "Permissions\n", ("h2",))
            t.insert("end", "  Ask every time: files and commands need your OK first\n"
                            "  Skip confirmation: run straight away (use with care)\n"
                            "  Do not disturb: never ask, dangerous actions are refused\n"
                            "  Anything outside the workspace always asks, no matter what\n\n")
            t.insert("end", "Memory\n", ("h2",))
            t.insert("end", "  Say \"remember: ...\" to store a long-term fact; it is sent with every turn.\n\n")
            t.insert("end", "API\n", ("h2",))
            t.insert("end", "  Any OpenAI-compatible endpoint: DeepSeek / Qwen / Kimi / OpenAI / Ollama.\n"
                            "  Presets live in api.md next to the program, or edit them in Settings.\n")
        else:
            t.insert("end", "明枢Win7\n", ("h1",))
            t.insert("end", "\n快捷键\n", ("h2",))
            t.insert("end", "  Enter        发送消息\n  Shift+Enter  输入换行\n"
                            "  Esc          停止运行中的任务\n  Ctrl+K       命令面板\n"
                            "  Ctrl+Alt+Q   在任意窗口中断当前任务\n\n")
            t.insert("end", "模式\n", ("h2",))
            t.insert("end", "  Agent  全工具：列目录/读文件/搜索/执行命令/写文件/打开文件/系统信息/抓网页\n"
                            "  Plan   只读：只能看，不能改（适合先分析后动手）\n"
                            "  Ask    纯聊天：不调用任何工具\n\n")
            t.insert("end", "权限\n", ("h2",))
            t.insert("end", "  每次询问：执行命令/写文件/打开文件前弹窗问你\n"
                            "  跳过确认：不再询问，直接执行（谨慎）\n"
                            "  免打扰：不询问，直接拒绝危险操作\n"
                            "  工作区之外的操作一律询问，不受档位影响\n\n")
            t.insert("end", "记忆\n", ("h2",))
            t.insert("end", "  对助手说「记住：xxx」写入长期记忆，之后每轮对话都会带上。\n\n")
            t.insert("end", "接口\n", ("h2",))
            t.insert("end", "  任意 OpenAI 兼容接口：DeepSeek / 通义千问 / Kimi / OpenAI / Ollama，\n"
                            "  预设写在程序目录的 api.md 里，也可以在「设置」里改。\n")
        t.tag_configure("h1", font=FONT_TITLE, foreground=th["fg_primary"], spacing3=8)
        t.tag_configure("h2", font=FONT_BOLD, foreground=th["fg_primary"], spacing1=10,
                        spacing3=4)
        make_copyable(t)
        self._help_view.pack(fill=tk.BOTH, expand=True, padx=(4, 10))

    # ------------------------------------------------------------ 会话管理

    def new_session(self):
        s = self.store.create()
        self.switch_session(s["id"])
        self._refresh_sessions()
        self.input.focus_set()

    def switch_session(self, sid):
        s = self.store.get(sid)
        if not s:
            return
        self.cur_session = sid
        self.think_buffer = []
        self.last_tool_card = None
        self.turn_usage = {}
        self.turn_tokens = 0
        self.session_tokens = int(s.get("tokens") or 0)
        self.chat.clear()
        history = self.store.load_history(sid)
        if not history:
            self.chat.note("hint", self.t["empty_chat_hint"])
        else:
            for m in history:
                # 旧版本可能把 DSML 乱码写进了历史，重放前先洗干净
                text = engine.strip_dsml(m.get("content", ""))
                if not text.strip():
                    continue
                if m.get("role") == "user":
                    self.chat.add_user(text)
                elif m.get("role") == "assistant":
                    self.chat.add_assistant(text, self.t["disclaimer"])
        self._refresh_header()
        self._refresh_sessions()
        self.chat.scroll_to_end(force=True)
        save_ui_state(self._state_dict())
        refresh_drop_targets(self.root)

    def _session_memory(self):
        sid = self.cur_session
        max_h = self.cfg.getint("assistant", "max_history", fallback=20)
        m = engine.Memory(max_history=max_h,
                          memory_path=self.store.history_path(sid),
                          facts_path=engine.FACTS_PATH)
        m.apply_config(self.cfg)
        # 外部用记事本改过 记忆.md 的话，这里同步回来
        try:
            m.load_md()
        except Exception:
            pass
        return m

    def _refresh_sessions(self):
        for w in self.session_box.winfo_children():
            w.destroy()
        th = self.th
        kw = (self.search_var.get() or "").strip().lower()
        for s in self.store.list():
            title = s.get("title") or self.t["session_untitled"]
            if kw and kw not in title.lower():
                continue
            cur = s["id"] == self.cur_session
            item = tk.Frame(self.session_box, bg=th["bg_hover"] if cur else th["bg_secondary"],
                            cursor="hand2")
            item.pack(fill=tk.X, pady=1)
            lb = tk.Label(item, text=title[:24], anchor="w", font=FONT_SMALL,
                          bg=th["bg_hover"] if cur else th["bg_secondary"],
                          fg=th["fg_primary"] if cur else th["fg_secondary"])
            lb.pack(fill=tk.X, padx=10, pady=(6, 0))
            tm = tk.Label(item, text=time.strftime("%m-%d %H:%M",
                                                   time.localtime(s.get("updated", 0))),
                          anchor="w", font=FONT_TINY,
                          bg=th["bg_hover"] if cur else th["bg_secondary"],
                          fg=th["fg_tertiary"])
            tm.pack(fill=tk.X, padx=10, pady=(0, 6))
            for w in (item, lb, tm):
                w.bind("<Button-1>", lambda e, i=s["id"]: self.switch_session(i))
                w.bind("<Button-3>", lambda e, i=s["id"]: self._session_menu(e, i))

    def _session_menu(self, e, sid):
        th = self.th
        m = tk.Menu(self.root, tearoff=0, bg=th["bg_card"], fg=th["fg_primary"],
                    font=FONT_SMALL, relief="flat")
        m.add_command(label=self.t["rename"], command=lambda: self._rename_dialog(sid))
        m.add_command(label=self.t["copy_id"], command=lambda: self._copy_text(sid))
        m.add_separator()
        m.add_command(label=self.t["delete"], command=lambda: self._delete_session(sid))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _rename_dialog(self, sid):
        s = self.store.get(sid)
        d = tk.Toplevel(self.root)
        d.title(self.t["rename"])
        d.configure(bg=self.th["bg_primary"])
        d.transient(self.root)
        tk.Label(d, text=self.t["rename"] + ":", bg=self.th["bg_primary"],
                 fg=self.th["fg_secondary"], font=FONT_SMALL).pack(padx=16, pady=(16, 4))
        var = tk.StringVar(value=s.get("title") or "")
        e = tk.Entry(d, textvariable=var, font=FONT, width=36, relief="flat",
                     bg=self.th["bg_input"], fg=self.th["fg_primary"])
        e.pack(padx=16, ipady=4)
        e.focus_set()

        def ok():
            self.store.rename(sid, var.get())
            self._refresh_sessions()
            self._refresh_header()
            d.destroy()

        tk.Button(d, text=self.t["save"], font=FONT_SMALL, relief="flat",
                  bg=self.th["accent_brand"], fg=self.th["fg_on_brand"],
                  command=ok).pack(pady=12)
        e.bind("<Return>", lambda ev: ok())

    def _delete_session(self, sid):
        from tkinter import messagebox
        if not messagebox.askyesno(self.t["delete"], self.t["delete_confirm"],
                                   parent=self.root):
            return
        self.store.delete(sid)          # 删 sessions/<sid>.json（对话历史缓存）
        try:
            # 该对话学到的临时记忆一并带走；全局固定记忆（记忆.md）不受影响。
            # 顺带回收历史版本删会话没清干净的孤儿记忆（sid 已不存在的条目）。
            m = engine.Memory(memory_path=self.store.history_path(sid),
                              facts_path=engine.FACTS_PATH)
            m.forget_session(sid)
            m.purge_orphan_facts([s["id"] for s in self.store.list()])
        except Exception:
            pass
        rest = self.store.list()
        if rest:
            self.switch_session(rest[0]["id"])
        else:
            s = self.store.create()
            self.switch_session(s["id"])
        self._refresh_sessions()

    # ------------------------------------------------------------ 顶栏/工具栏

    def _refresh_header(self):
        s = self.store.get(self.cur_session) or {}
        title = s.get("title") or self.t["session_untitled"]
        self.title_lb.configure(text=title)
        mode_name = {"agent": self.t["mode_agent"], "plan": self.t["mode_plan"],
                     "ask": self.t["mode_ask"]}[self.mode]
        self.chips["mode"].configure(text="◆ " + mode_name)
        model = self.cfg.get("llm", "model", fallback="?")
        self.chips["model"].configure(text="◆ " + model)
        ws = self.cfg.get("agent", "workspace", fallback="").strip()
        self.chips["workspace"].configure(text="▤ " + (ws if ws else self.t["workspace_all"]))
        # 工具按钮
        self.tool_btns["mode"].set_text("◆ " + mode_name)
        self.tool_btns["model"].set_text("◆ " + model)
        self.tool_btns["workspace"].set_text(
            "▤ " + (os.path.basename(ws.rstrip("\\/")) if ws else self.t["workspace"]))
        self.tool_btns["goal"].set_text("◎ " + self.t["goal"])
        self.tool_btns["think"].set_text(
            "◇ " + (self.t["deep_think"] if self.deep_think else self.t["thinking"]))
        self.tool_btns["palette"].set_text("⌘K " + self.t["palette"].split()[-1])
        self.btn_send.set_text(self.t["force_send"] if self.running else self.t["send"])
        # 生成中才显示「打断」按钮：停当前轮；发送键此时是「强制发送」（排队不打断）
        if self.running:
            if not self.btn_stop.winfo_ismapped():
                self.btn_stop.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        else:
            self.btn_stop.pack_forget()
        self.btn_perm.configure(text="⚔ " + {
            "auto": self.t["gear_auto"], "ask": self.t["gear_ask"],
            "strict": self.t["gear_strict"], "locked": self.t["gear_locked"],
        }.get(self.perm_mode, self.t["gear_ask"]))
        if self.perm_waiting:
            self.input.configure(bg=self.th["bg_permission"])

    def _cycle_mode(self):
        order = ["agent", "plan", "ask"]
        self.mode = order[(order.index(self.mode) + 1) % 3]
        self._refresh_header()
        save_ui_state(self._state_dict())

    def _cycle_perm(self):
        order = ["auto", "ask", "strict", "locked"]
        self.perm_mode = order[(order.index(self.perm_mode) + 1) % 4]
        self._refresh_header()
        save_ui_state(self._state_dict())

    def _toolbar(self, key):
        if key == "mode":
            self._cycle_mode()
        elif key == "model":
            self._open_settings()
        elif key == "workspace":
            self._workspace_menu()
        elif key == "goal":
            self._toggle_goal_bar()
        elif key == "think":
            self.deep_think = not self.deep_think
            self._refresh_header()
        elif key == "palette":
            self.toggle_palette()

    def _toggle_sidebar(self):
        if self.sidebar.winfo_ismapped():
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y, before=self.main)

    def _toggle_goal_bar(self):
        s = self.store.get(self.cur_session)
        if self.goal_bar.winfo_ismapped():
            self.goal_bar.pack_forget()
            if s:
                s["goal"] = self.goal_entry.get().strip()
        else:
            self.goal_bar.pack(fill=tk.X, pady=(0, 6), before=self.composer.winfo_children()[0])
            self.goal_entry.delete(0, tk.END)
            if s and s.get("goal"):
                self.goal_entry.insert(0, s["goal"])
            self.goal_entry.configure(bg=self.th["bg_input"], fg=self.th["fg_primary"],
                                      insertbackground=self.th["fg_primary"])
            self.goal_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4,
                                 padx=8, pady=8)
            self._goal_pause_btn = tk.Button(
                self.goal_bar,
                text=("▶ " + self.t["goal_resume"]) if self.goal_paused
                else ("⏸ " + self.t["goal_pause"]),
                font=FONT_SMALL, relief="flat", bg=self.th["bg_chip"],
                fg=self.th["fg_secondary"], cursor="hand2", command=self._goal_pause)
            self._goal_pause_btn.pack(side=tk.RIGHT, padx=(0, 6), pady=8)
            tk.Button(self.goal_bar, text="✕ " + self.t["goal_clear"],
                      font=FONT_SMALL, relief="flat", bg=self.th["bg_chip"],
                      fg=self.th["fg_secondary"], cursor="hand2",
                      command=self._goal_clear).pack(side=tk.RIGHT, padx=(0, 6), pady=8)
            self.goal_entry.focus_set()

    def _goal_pause(self):
        self.goal_paused = not self.goal_paused
        s = self.store.get(self.cur_session)
        if s:
            s["goal_paused"] = self.goal_paused
        if getattr(self, "_goal_pause_btn", None):
            self._goal_pause_btn.configure(
                text=("▶ " + self.t["goal_resume"]) if self.goal_paused
                else ("⏸ " + self.t["goal_pause"]))

    def _goal_clear(self):
        s = self.store.get(self.cur_session)
        if s:
            s["goal"] = ""
            s["goal_paused"] = False
        self.goal_entry.delete(0, tk.END)
        self._toggle_goal_bar()

    def _workspace_menu(self):
        th = self.th
        m = tk.Menu(self.root, tearoff=0, bg=th["bg_card"], fg=th["fg_primary"],
                    font=FONT_SMALL, relief="flat")
        m.add_command(label=self.t["workspace_set"], command=self._set_workspace)
        m.add_command(label=self.t["workspace_clear"], command=self._clear_workspace)
        try:
            x = self.chips["workspace"].winfo_rootx()
            y = self.chips["workspace"].winfo_rooty() + 24
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _set_workspace(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=self.root, title=self.t["workspace_set"])
        if d:
            self.cfg.set("agent", "workspace", d)
            self._save_cfg()
            self._refresh_header()

    def _clear_workspace(self):
        self.cfg.set("agent", "workspace", "")
        self._save_cfg()
        self._refresh_header()

    # ------------------------------------------------------------ 发送/接收

    def on_send_click(self):
        if self.running:
            # 生成中点发送 = 强制发送：消息排队引导，不打断当前任务；
            # 当前轮跑完后自动接上（真正停止用旁边的「打断」按钮或 Esc）
            text = self.input.get("1.0", "end-1c").strip()
            if not text and not self._attachments:
                return
            self.input.delete("1.0", "end")
            self._send(text, with_attachments=True)
            return
        text = self.input.get("1.0", "end-1c").strip()
        if not text and not self._attachments:
            return
        self.input.delete("1.0", "end")
        self._send(text, with_attachments=True)

    def _has_key(self):
        k = self.cfg.get("llm", "api_key", fallback="").strip()
        return bool(k) and not k.startswith("在这里")

    def _send(self, text, with_attachments=False):
        if not self._has_key():
            self.chat.note("error", self.t["need_key"])
            self.chat.scroll_to_end()
            self._open_settings()
            return
        # 附件：内容只在本次请求里发，历史里只留文件名和路径（否则每轮都重发一遍，烧 token）
        attach = []
        if with_attachments and self._attachments:
            attach = list(self._attachments)
            self._attachments = []
            self._refresh_attach_row()
        payload, display, hist = text, text, text
        if attach:
            block, names = engine.build_attachment_text(attach)
            payload = ((text + "\n\n") if text else "") + block
            display = ((text + "\n") if text else "") + "▤ " + "、".join(names)
            hist = ((text + "\n") if text else "") + (
                "（附带 %d 个文件：%s。文件内容只在那一轮的请求里给过；"
                "后面需要再看，可用工具按路径读取。）" % (len(attach), "、".join(attach)))
        if not payload.strip():
            return
        if not self.cur_session:
            s = self.store.create()
            self.switch_session(s["id"])
        if self.running:
            self.pending_msgs.append(payload)
            self.chat.add_user(display + self.t["queued"])
            self.chat.scroll_to_end()
            return
        self.running = True
        self.gen_id += 1              # 世代令牌：本轮输出的身份证
        gen = self.gen_id
        self.turn_tokens = 0
        self.turn_usage = {}
        self.stop_event.clear()
        self.think_buffer = []
        self.last_tool_card = None
        self._refresh_header()
        self.chat.add_user(display)
        self.chat.glide_to_end()   # 平滑滑到用户气泡旁，AI 输出开始后自动跟随
        s = self.store.get(self.cur_session)
        if s and not s.get("title"):
            self.store.rename(self.cur_session, display[:18])
            self._refresh_sessions()
            self._refresh_header()
        threading.Thread(target=self._work, args=(payload, hist, gen),
                         daemon=True).start()

    def _effective_cfg(self):
        import configparser
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read_dict(dict((s, dict(self.cfg.items(s))) for s in self.cfg.sections()))
        base = cfg.get("assistant", "system_prompt",
                       fallback="你是一个得力的中文个人助手。")
        s = self.store.get(self.cur_session) or {}
        goal = s.get("goal", "")
        if goal and not s.get("goal_paused") and not self.goal_paused:
            base += "\n\n【当前目标】%s\n请始终围绕这个目标工作，完成后汇报成果。" % goal
        if self.deep_think:
            base += "\n\n请先在内部充分思考、逐步推理，再给出最终结论。"
        cfg.set("assistant", "system_prompt", base)
        return cfg

    def _work(self, text, hist=None, gen=0):
        # 工作线程切到后台 I/O + 空闲优先级：用户一碰键鼠就先让路，
        # 机械硬盘上这条比优化代码更有效（内核调度，不靠自觉）。
        try:
            engine.limits.begin_worker_thread()
        except Exception:
            pass
        approver = engine.Approver(
            self.perm_mode == "auto" and self.cfg.getboolean(
                "agent", "auto_approve", fallback=False),
            ask_ui=self._ask_ui,
            deny_all=self.perm_mode == "locked",
            cfg=self._effective_cfg())
        self._approver = approver          # 供"高级权限"当场改 auto
        mem = self._session_memory()
        try:
            final = engine.handle_message(
                self._effective_cfg(), mem, text, approver,
                on_event=self._emit,
                plain=(self.mode == "ask"),
                readonly=(self.mode == "plan"),
                stop_event=self.stop_event,
                history_text=hist)
        except Exception as e:
            final = _tr("出错了：%s", "Something went wrong: %s") % e
        self.queue.put(("final", (final, gen)))

    def _emit(self, kind, text):
        self.queue.put((kind, text))

    # ------------------------------------------------------------ 右下角提醒
    #
    # 窗口被挂起（最小化 / 切到别的程序）时，光靠聊天区里的气泡没人看得见。
    # 这里在屏幕右下角弹一个自绘小卡片：左边一个场景图标，右边标题+摘要，
    # 点一下就把主窗口拉回来；确认类提醒不会自动消失，完成类几秒后自己退。

    TOAST_KINDS = {
        "done":  ("✓", "green", "任务完成"),
        "ask":   ("?", "yellow", "需要你的确认"),
        "error": ("!", "red", "出错了"),
        "info":  ("i", "accent", "提示"),
    }

    def _work_area(self):
        """屏幕可用工作区右下角（自动避开 Win7 任务栏）。"""
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
            r = RECT()
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(r), 0)      # SPI_GETWORKAREA
            if ok and r.right > 0 and r.bottom > 0:
                return r.right, r.bottom
        except Exception:
            pass
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _window_inactive(self):
        """窗口是否处于"挂起"状态：最小化、或不是当前前台窗口。"""
        try:
            if self.root.state() == "iconic":
                return True
        except Exception:
            pass
        try:
            import ctypes
            u = ctypes.windll.user32
            u.GetForegroundWindow.restype = ctypes.c_void_p
            u.GetAncestor.restype = ctypes.c_void_p
            hwnd = u.GetAncestor(int(self.root.winfo_id()), 2)   # GA_ROOT
            gw = u.GetForegroundWindow()
            return int(gw or 0) != int(hwnd or 0)
        except Exception:
            try:
                return self.root.focus_displayof() is None
            except Exception:
                return True

    def _toast_reflow(self):
        """把所有提醒沿屏幕右下角往上堆。"""
        sw, sh = self._work_area()
        y = sh - 12
        for w in reversed(getattr(self, "_toasts", [])):
            try:
                if not w.winfo_exists():
                    continue
                h = int(w.winfo_reqheight())
                y -= h
                w.geometry("+%d+%d" % (sw - 352, y))
                y -= 8
            except Exception:
                pass

    def _toast_close(self, win):
        try:
            if win in self._toasts:
                self._toasts.remove(win)
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        self._toast_reflow()

    def _toast_focus(self, win):
        """点提醒：把主窗口拉回前台，并关掉这条提醒。"""
        self._toast_close(win)
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _toast(self, kind, title=None, body="", sticky=False, seconds=6):
        """弹一个右下角提醒。kind: done / ask / error / info。
        sticky=True：不自动消失（用于"需要你确认"这种必须处理的事）。"""
        try:
            if not getattr(self, "_toasts", None):
                self._toasts = []
            sym, color_key, default_title = self.TOAST_KINDS.get(
                kind, self.TOAST_KINDS["info"])
            title = title or default_title
            th = self.th
            color = th.get(color_key, th["accent"])

            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            try:
                win.attributes("-topmost", True)
            except Exception:
                pass
            try:
                win.attributes("-alpha", 0.98)
            except Exception:
                pass
            cv = tk.Canvas(win, width=340, height=86, bg=th["bg_card"],
                           highlightthickness=0, bd=0)
            cv.pack()
            # 圆角底 + 左侧色条
            cv.create_polygon(*_rr_pts(340, 86, 12), fill=th["bg_card"],
                              outline=th["border"], width=1, smooth=True)
            cv.create_polygon(*_rr_pts(5, 86, 3), fill=color, outline="",
                              smooth=True)
            # 场景图标：彩色圆 + 白色符号
            cv.create_oval(18, 26, 52, 60, fill=color, outline="")
            cv.create_text(35, 43, text=sym, fill="#ffffff",
                           font=(FONT[0], -17, "bold"))
            # 标题
            cv.create_text(62, 24, text=title, anchor="w",
                           font=(FONT[0], -14, "bold"), fill=th["fg_primary"])
            # 正文：折成两行，超出截断
            txt = " ".join((body or "").split())
            if len(txt) > 46:
                txt = txt[:45] + "…"
            line1, line2 = txt[:24], txt[24:]
            cv.create_text(62, 46, text=line1, anchor="w",
                           font=FONT_SMALL, fill=th["fg_secondary"])
            if line2:
                cv.create_text(62, 64, text=line2, anchor="w",
                               font=FONT_SMALL, fill=th["fg_secondary"])
            # 关闭按钮
            x = cv.create_text(322, 16, text="✕", fill=th["fg_tertiary"],
                               font=FONT_TINY)
            cv.tag_bind(x, "<Button-1>",
                        lambda e, w=win: self._toast_close(w))
            cv.tag_bind(x, "<Enter>",
                        lambda e: cv.itemconfigure(x, fill=th["red"]))
            cv.tag_bind(x, "<Leave>",
                        lambda e: cv.itemconfigure(x, fill=th["fg_tertiary"]))
            cv.configure(cursor="hand2")
            cv.bind("<Button-1>",
                    lambda e, w=win: self._toast_focus(w))
            win.bind("<Button-1>", lambda e, w=win: self._toast_focus(w))

            self._toasts.append(win)
            if len(self._toasts) > 3:                 # 最多同时 3 条
                self._toast_close(self._toasts[0])
            self._toast_reflow()

            if not sticky:
                def _fade(step=10):
                    try:
                        if not win.winfo_exists():
                            return
                        if step <= 0:
                            self._toast_close(win)
                            return
                        win.attributes("-alpha", max(0.06, step / 10.0))
                        win.after(60, lambda: _fade(step - 1))
                    except Exception:
                        self._toast_close(win)
                win.after(int(seconds * 1000), _fade)
            return win
        except Exception as e:
            print("[toast] failed: %r" % (e,))
            return None

    def _ask_ui(self, desc, level="L2"):
        """工作线程里调用：把审批请求交给界面，阻塞等待用户点按钮。

        L3（动系统）不给你一键放行——必须手动输入「授权」两个汉字，
        防止误点一下就把命令执行/抓包/扫描发出去了。
        """
        ev = threading.Event()
        box = {"ok": False}
        self.queue.put(("perm", desc, ev, box, level))
        ev.wait()
        return box["ok"]

    def _sched_tick(self):
        """定时任务轮询：到点就触发。程序开着才会跑，关闭期间错过的任务不补。"""
        try:
            items = engine._load_schedule()
            now = time.time()
            for it in items:
                if not engine._due(it):
                    continue
                act = (it.get("action") or "").strip()
                name = it.get("name", "?")
                # 先落 last_run，避免同一周期内重复触发（_due 也有一层 30 秒保护）
                it["last_run"] = now
                engine._save_schedule(items)
                low = act.lower()
                if low.startswith("cmd:"):
                    cmd = act[4:].strip()
                    self.chat.note("hint", "◆ 定时任务「%s」到点，执行：%s" % (name, cmd))
                    self._sched_run_cmd(cmd, name)
                elif low.startswith("ask:"):
                    q = act[4:].strip()
                    if not self._has_key():
                        # 没配 Key 时别静默吞掉，用户会以为任务跑了
                        self.chat.note("error", "▲ 定时任务「%s」到点，但还没配 API Key，"
                                               "这次没有执行。去「设置 → 模型接口」填 Key。"
                                       % name)
                        continue
                    self.chat.note("hint", "◆ 定时任务「%s」到点，分析：%s" % (name, q))
                    self._send("[定时任务 %s] %s" % (name, q))
                else:
                    self.chat.note("warn", "▲ 定时任务「%s」的动作看不懂：%s"
                                   % (name, act[:60]))
        except Exception as e:
            print("[sched] tick error: %r" % (e,))
        self.root.after(20 * 1000, self._sched_tick)

    def _sched_run_cmd(self, cmd, name):
        """定时执行的命令：在后台线程跑，结果写进对话，不阻塞界面。"""
        def run():
            try:
                out = engine.tool_run_cmd(cmd)
                self.queue.put(("sched_out", "「%s」%s\n%s" % (name, cmd, out)))
            except Exception as e:
                self.queue.put(("sched_out", _tr("「%s」执行失败：%s",
                                                "Scheduled task \"%s\" failed: %s") % (name, e)))
        threading.Thread(target=run, daemon=True).start()

    def _pump(self):
        n = 0
        try:
            while True:
                item = self.queue.get_nowait()
                n += 1
                if len(item) == 2:
                    self._handle_event(item[0], item[1])
                else:
                    self._handle_event(item[0], item[1:])   # perm 等多元组
                if n >= 40:
                    # 一帧最多处理这么多，剩下的下一轮接着来。
                    # 流式高峰期事件成百上千，全塞进一帧会把键盘输入饿死
                    break
        except queue.Empty:
            pass
        except Exception as e:
            # 单个事件出错不能杀死整个泵，否则界面永久假死
            print("[pump] event error: %r" % (e,))
        # 空闲时慢轮询（120ms）少占 CPU，有事件时快轮询（25ms）保实时
        self.root.after(25 if n else 120, self._pump)

    def _handle_event(self, kind, payload):
        th = self.th
        if kind == "think":
            # 流式思考是一堆小碎片，按组累积；非流式是整段字符串
            if self.think_buffer and isinstance(self.think_buffer[-1], list):
                self.think_buffer[-1].append(payload)
            else:
                self.think_buffer.append([payload])
            self.phase_lb.configure(text=self.t["phase_streaming"])
        elif kind == "delta":
            # 模型正文增量：打进气泡实时显示
            self.chat.stream_append(payload)
            self.phase_lb.configure(text=self.t["phase_streaming"])
        elif kind == "tool":
            folded = self.chat.stream_fold()
            if folded.strip():
                self.think_buffer.append([engine.strip_dsml(folded).strip()])
            self._flush_think()
            name = payload.split(" ", 1)[0]
            args_text = payload.split(" ", 1)[1] if " " in payload else ""
            try:
                args = json.loads(args_text) if args_text.strip().startswith("{") else {}
            except Exception:
                args = {}
            head, body, state, toggle = self.chat.add_tool_card(
                name, tool_body_text(name, args), title=tool_head_text(name, args))
            self.last_tool_card = (head, body, state, toggle)
            if name == "write_file" and not state["open"]:
                toggle()          # 写文件默认展开，直接看到写了什么
            self.phase_lb.configure(text=self.t["phase_tool"])
            self.chat.scroll_to_end()
        elif kind == "result":
            if self.last_tool_card:
                head, body, state, toggle = self.last_tool_card
                body.configure(state=tk.NORMAL)
                body.insert("end", "\n%s\n%s" % (self.t["tool_result"], payload))
                lines = int(body.index("end-1c").split(".")[0])
                body.configure(height=min(max(lines, 1), 20))
                if not state["open"] and lines <= 12:
                    toggle()          # 短结果自动展开
                self.chat.scroll_to_end()
            self.phase_lb.configure(text=self.t["phase_done"])
        elif kind == "error":
            self.chat.stream_discard()
            self.chat.think_finish()
            self.chat.note("warn", "▲ " + payload)
            self.chat.scroll_to_end()
        elif kind == "usage":
            u = payload or {}
            self.turn_usage = dict(u)
            self.turn_tokens = int(u.get("total_tokens") or 0)
            rt = int(u.get("reasoning_tokens") or 0)
            txt = "%s  ·  %s tokens" % (self.t["phase_done"], "{:,}".format(self.turn_tokens))
            if rt:
                txt += _tr("（思考 {:,}）", " (thinking {:,})").format(rt)
            self.phase_lb.configure(text=txt)
        elif kind == "term":
            self._term_write(payload)
        elif kind == "sched_out":
            self.chat.note("hint", payload)
            self.chat.scroll_to_end()
            if self._window_inactive():
                self._toast("info", _tr("定时任务", "Scheduled task"),
                            " ".join((payload or "").split())[:80])
        elif kind == "perm":
            if len(payload) == 4:
                desc, ev, box, level = payload
            else:
                desc, ev, box = payload
                level = "L2"
            self.perm_waiting = True
            self._refresh_header()

            def done(v, always=False):
                box["ok"] = v
                self.perm_waiting = False
                if always:
                    # 高级权限：本轮立即放行 + 永久切到 auto（记住到 ui_state.json）
                    self.perm_mode = "auto"
                    ap = getattr(self, "_approver", None)
                    if ap is not None:
                        ap.auto = True
                    save_ui_state(self._state_dict())
                self._refresh_header()
                ev.set()

            # 所有层级统一走三按钮卡片：同意 / 拒绝 / 以后都同意。
            # 之前 L3 要求手输「授权」两个字，用户嫌太严格，已去掉；
            # 严格/锁死档的拦截仍由引擎 perm_decision 负责，不受影响。
            self.chat.add_permission(desc, self.t["perm_title"],
                                     self.t["perm_allow"],
                                     self.t["perm_deny"], done)
            self.chat.scroll_to_end()
            # 确认类提醒：多等一会儿也要让用户看见，所以不自动消失
            if self._window_inactive():
                self._toast("ask", None, " ".join((desc or "").split())[:80],
                            sticky=True)
        elif kind == "final":
            final, gen = payload if isinstance(payload, tuple) and len(payload) == 2 \
                else (payload, self.gen_id)
            if gen != self.gen_id:
                # 已被打断的旧线程收尾：不渲染内容，只恢复界面
                self.chat.stream_discard()
                self.chat.think_finish()
                self.running = False
                self.phase_lb.configure(text="")
                self._refresh_header()
                refresh_drop_targets(self.root)
                return
            # 流式临时气泡里的文字和最终答复相同，直接收掉，用正式 markdown 气泡渲染
            self.chat.stream_discard()
            self.chat.think_finish()
            u = self.turn_usage or {}
            tot = int(u.get("total_tokens") or 0)
            line = ""
            if tot:
                p = int(u.get("prompt_tokens") or 0)
                c = int(u.get("completion_tokens") or 0)
                r = int(u.get("reasoning_tokens") or 0)
                self.session_tokens = int(getattr(self, "session_tokens", 0)) + tot
                line = _tr("◆ 本次 {:,} tokens｜输入 {:,} · 输出 {:,}",
                        "◆ {:,} tokens this turn | in {:,} / out {:,}").format(tot, p, c)
                if r:
                    line += _tr("（其中思考 {:,}）", " (thinking {:,})").format(r)
                line += _tr("｜本会话累计 {:,}", " | {:,} in this chat").format(self.session_tokens)
                s = self.store.get(self.cur_session)
                if s is not None:
                    s["tokens"] = self.session_tokens
                    s["last_tokens"] = tot
            _, dl = self.chat.add_assistant(final, self.t["disclaimer"], line)
            self.chat.scroll_to_end()
            # 窗口挂起时才提醒，别在用户盯着看的时候弹
            if self._window_inactive():
                summary = " ".join((final or "").split())[:80]
                is_err = summary.startswith(("出错了", "Something went wrong"))
                self._toast("error" if is_err else "done", None, summary)
            self.phase_lb.configure(text="")
            self.running = False
            self.store.touch(self.cur_session)
            self._refresh_sessions()
            self._refresh_header()
            refresh_drop_targets(self.root)
            if self.pending_msgs:
                nxt = self.pending_msgs.pop(0)
                self._pending_after = self.root.after(50, lambda: self._send(nxt))

    def _flush_think(self, keep_if_differs=None):
        if not self.think_buffer:
            return
        # 每组是一段（流式碎片拼回来），组与组之间空一行分开
        text = "\n".join(
            "".join(g) if isinstance(g, list) else g
            for g in self.think_buffer).strip()
        self.think_buffer = []
        if keep_if_differs is not None and text == keep_if_differs.strip():
            return                     # 这段就是最终答复，不作为思考展示
        head, body = self.chat.add_thinking(text)
        head.configure(text="◇ " + self.t["thinking"])
        self.chat.scroll_to_end()

    # ---- 全局中断热键（Ctrl+Alt+Q）----
    # 用户随时可能抢鼠标/切走窗口，界面上那个「打断」按钮来不及点。
    # 用 GetAsyncKeyState 轮询即可，不装全局钩子（杀软对钩子极敏感）。
    def _hotkey_tick(self):
        try:
            import ctypes
            u = ctypes.windll.user32
            down = 0x8000
            if (u.GetAsyncKeyState(0x11) & down) and                (u.GetAsyncKeyState(0x12) & down) and                (u.GetAsyncKeyState(0x51) & down):      # Ctrl + Alt + Q
                if self.running and not getattr(self, "_hk_fired", False):
                    self._hk_fired = True
                    try:
                        self.chat.note("warn", _tr("▲ 已按 Ctrl+Alt+Q 中断当前任务。",
                                        "▲ Stopped the current task (Ctrl+Alt+Q)."))
                    except Exception:
                        pass
                    self.on_stop()
            else:
                self._hk_fired = False
        except Exception:
            pass
        try:
            self.root.after(150, self._hotkey_tick)
        except Exception:
            pass

    def on_stop(self):
        if not self.running:
            return
        self.gen_id += 1              # 立即作废当前线程的输出（final 事件会被丢弃）
        if self._pending_after is not None:
            try:
                self.root.after_cancel(self._pending_after)
            except Exception:
                pass
            self._pending_after = None
        self.pending_msgs = []        # 排队中的消息一并取消
        self.stop_event.set()
        self.phase_lb.configure(text=self.t["phase_stopping"])
        refresh_drop_targets(self.root)

        def _force_recover():
            # 看门狗：连接挂起时 stop_event 收不到（阻塞在 socket 读），
            # 3 秒后强制恢复界面，避免"发送键消失"卡死所有会话（含新会话）。
            if self.running:
                self.running = False
                self.chat.stream_discard()
                self.chat.think_finish()
                self.phase_lb.configure(text="")
                self.chat.note("warn", _tr("▲ 已强制打断（后台连接可能仍然挂起，",
                                        "▲ Force-stopped (a background connection may still be hanging,") +
                                       _tr("不影响继续使用）。", " the app keeps working)."))
                self._refresh_header()
                refresh_drop_targets(self.root)
        self.root.after(3000, _force_recover)

    # ------------------------------------------------------------ 命令面板

    def toggle_palette(self):
        if getattr(self, "_palette", None) and self._palette.winfo_exists():
            self._palette.destroy()
            self._palette = None
            return
        th = self.th
        p = tk.Toplevel(self.root)
        p.overrideredirect(True)
        p.configure(bg=th["bg_card"], highlightbackground=th["border"],
                    highlightthickness=1)
        self._palette = p
        w, h = 460, 320
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + 120
        p.geometry("%dx%d+%d+%d" % (w, h, x, y))
        var = tk.StringVar()
        e = tk.Entry(p, textvariable=var, font=FONT, relief="flat", bg=th["bg_input"],
                     fg=th["fg_primary"], insertbackground=th["fg_primary"])
        e.pack(fill=tk.X, padx=10, pady=10, ipady=4)
        e.focus_set()
        lb = tk.Listbox(p, font=FONT, relief="flat", bg=th["bg_card"],
                        fg=th["fg_primary"], selectbackground=th["accent"],
                        selectforeground="#ffffff", activestyle="none")
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        cmds = [
            (self.t["new_chat"], self.new_session),
            ("◆ " + self.t["mode_agent"], lambda: self._set_mode("agent")),
            ("◆ " + self.t["mode_plan"], lambda: self._set_mode("plan")),
            ("◆ " + self.t["mode_ask"], lambda: self._set_mode("ask")),
            (self.t["settings_title"], self._open_settings),
            (self.t["nav_terminal"], lambda: self._nav("terminal")),
            (self.t["nav_help"], lambda: self._nav("help")),
        ]

        def fill(_a=None):
            lb.delete(0, tk.END)
            kw = var.get().lower()
            self._cmds_filtered = [c for c in cmds if kw in c[0].lower()]
            for c in self._cmds_filtered:
                lb.insert(tk.END, c[0])
            if self._cmds_filtered:
                lb.selection_set(0)

        var.trace("w", fill)
        fill()

        def run(_e=None):
            sel = lb.curselection()
            if sel:
                self._cmds_filtered[sel[0]][1]()
            p.destroy()

        lb.bind("<Double-Button-1>", run)
        lb.bind("<Return>", run)
        e.bind("<Return>", run)
        e.bind("<Escape>", lambda ev: p.destroy())
        p.bind("<Escape>", lambda ev: p.destroy())
        p.grab_set()

    def _set_mode(self, mode):
        self.mode = mode
        self._refresh_header()
        save_ui_state(self._state_dict())

    # ------------------------------------------------------------ 设置面板

    def _open_settings(self):
        th, t = self.th, self.t
        d = tk.Toplevel(self.root)
        d.title(t["settings_title"])
        d.configure(bg=th["bg_primary"])
        d.transient(self.root)
        # 高度按可用屏幕算，768p 的 Win7（扣掉任务栏约 740）也不会超出屏幕
        try:
            avail = d.winfo_screenheight() - 90
            h = min(760, max(560, avail))
        except Exception:
            h = 760
        d.geometry("560x%d" % h)
        # 内容区套 Canvas + 滚动条，保存按钮固定在底部。
        # 以前内容直接 pack 到窗上，字段一多（记忆分组 + 四档）就把
        # 底部保存按钮压成 1px 高——按钮功能是好的，但用户根本点不到。
        outer = tk.Frame(d, bg=th["bg_primary"])
        outer.pack(fill=tk.BOTH, expand=True)
        cv = tk.Canvas(outer, bg=th["bg_primary"], highlightthickness=0)
        sb = tk.Scrollbar(outer, width=10, command=cv.yview,
                          bg=th["scrollbar"], troughcolor=th["scroll_trough"],
                          relief="flat", borderwidth=0)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        nb = tk.Frame(cv, bg=th["bg_primary"], padx=18, pady=6)
        _win = cv.create_window((0, 0), window=nb, anchor="nw")
        nb.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(_win, width=e.width))
        # 滚轮挂在弹窗自身（bind_all 会全局残留，关掉后还和对话区抢事件）；
        # 记忆编辑框这类 Text 让它自己滚自己的内容
        def _dlg_wheel(e):
            if isinstance(e.widget, tk.Text):
                return
            cv.yview_scroll(int(-e.delta / 120), "units")
        d.bind("<MouseWheel>", _dlg_wheel)
        v = {}

        def section(title):
            tk.Label(nb, text=title, bg=th["bg_primary"], fg=th["fg_primary"],
                     font=FONT_BOLD, anchor="w").pack(fill=tk.X, pady=(10, 3))

        def field(key, label, value, mono=False):
            tk.Label(nb, text=label, bg=th["bg_primary"], fg=th["fg_secondary"],
                     font=FONT_SMALL, anchor="w").pack(fill=tk.X)
            var = tk.StringVar(value=value)
            v[key] = var
            tk.Entry(nb, textvariable=var, font=MONO_SMALL if mono else FONT,
                     relief="flat", bg=th["bg_input"], fg=th["fg_primary"],
                     insertbackground=th["fg_primary"]).pack(fill=tk.X, ipady=3)

        section(t["settings_llm"])
        field("base_url", t["settings_base"], self.cfg.get("llm", "base_url", fallback=""), True)
        field("api_key", t["settings_key"], self.cfg.get("llm", "api_key", fallback=""), True)
        field("model", t["settings_model"], self.cfg.get("llm", "model", fallback=""), True)
        field("proxy", t["settings_proxy"], self.cfg.get("llm", "proxy", fallback=""), True)

        # ---- API 预设（api.md 双向同步）+ 连通测试 ----
        tk.Label(nb, text=t["api_md_hint"], bg=th["bg_primary"], fg=th["fg_tertiary"],
                 font=FONT_TINY, anchor="w", justify="left",
                 wraplength=500).pack(fill=tk.X, pady=(4, 2))
        try:
            presets, active = engine.load_api_presets()
        except Exception:
            presets, active = [], ""
        names = [n for n, _ in presets] or ["deepseek"]
        row_api = tk.Frame(nb, bg=th["bg_primary"])
        row_api.pack(fill=tk.X, pady=(2, 0))
        api_var = tk.StringVar(value=active if active in names else names[0])
        v["api_preset"] = api_var
        om = tk.OptionMenu(row_api, api_var, *names)
        om.configure(font=FONT_SMALL, bg=th["bg_input"], fg=th["fg_primary"],
                     relief="flat", highlightthickness=0, activebackground=th["bg_input"])
        om.pack(side=tk.LEFT)

        def _load_preset():
            name = api_var.get()
            for n, d in presets:
                if n == name:
                    v["base_url"].set(d.get("base_url", ""))
                    v["api_key"].set(d.get("api_key", ""))
                    v["model"].set(d.get("model", ""))
                    break

        tk.Button(row_api, text=t["api_load"], font=FONT_SMALL, relief="flat",
                  bg=th["bg_card"], fg=th["fg_primary"], cursor="hand2",
                  command=_load_preset).pack(side=tk.LEFT, padx=(6, 0), ipadx=8, ipady=2)

        test_lb = tk.Label(nb, text="", bg=th["bg_primary"], fg=th["fg_secondary"],
                           font=FONT_TINY, anchor="w", justify="left", wraplength=500)
        test_lb.pack(fill=tk.X, pady=(2, 0))

        def _run_test():
            test_lb.configure(text=t["api_testing"], fg=th["fg_secondary"])
            probe = {"base_url": v["base_url"].get().strip(),
                     "api_key": v["api_key"].get().strip(),
                     "model": v["model"].get().strip(),
                     "proxy": v["proxy"].get().strip()}

            def work():
                ok, msg = engine.test_endpoint(probe)

                def done():
                    try:
                        test_lb.configure(text=("✔ " if ok else "✘ ") + msg,
                                          fg=th["green"] if ok else th["red"])
                    except Exception:
                        pass
                try:
                    d.after(0, done)
                except Exception:
                    pass
            threading.Thread(target=work, daemon=True).start()

        tk.Button(row_api, text=t["api_test"], font=FONT_SMALL, relief="flat",
                  bg=th["bg_card"], fg=th["fg_primary"], cursor="hand2",
                  command=_run_test).pack(side=tk.LEFT, padx=(6, 0), ipadx=8, ipady=2)
        field("max_tokens", t["settings_max_tokens"],
              str(self.cfg.getint("llm", "max_tokens", fallback=1024)))
        tk.Label(nb, text=t["settings_thinking"], bg=th["bg_primary"],
                 fg=th["fg_secondary"], font=FONT_SMALL, anchor="w").pack(fill=tk.X)
        think = tk.StringVar(value=(self.cfg.get("llm", "thinking", fallback="off").strip().lower()
                                    or "off"))
        v["thinking"] = think
        row_t = tk.Frame(nb, bg=th["bg_primary"])
        row_t.pack(fill=tk.X)
        for val in ("off", "low", "high", "max"):
            tk.Radiobutton(row_t, text=t["think_" + val], variable=think, value=val,
                           font=FONT_SMALL, bg=th["bg_primary"], fg=th["fg_secondary"],
                           selectcolor=th["bg_card"],
                           activebackground=th["bg_primary"]).pack(side=tk.LEFT, padx=(0, 12))

        # ---- 两个强制开关（跟在思考档位下面；长期记忆开关在最后）----
        # 这两个是"即点即生效"：勾选立刻写 ini，不用点下面的保存。
        def force_check(label, var, desc=""):
            fr = tk.Frame(nb, bg=th["bg_primary"])
            fr.pack(fill=tk.X, pady=(2, 0))
            cb = tk.Checkbutton(fr, text=label, variable=var, font=FONT_SMALL,
                                bg=th["bg_primary"], fg=th["fg_primary"],
                                selectcolor=th["bg_card"],
                                activebackground=th["bg_primary"], anchor="w")
            cb.pack(side=tk.LEFT)
            if desc:
                tk.Label(fr, text=desc, font=FONT_TINY, bg=th["bg_primary"],
                         fg=th["fg_tertiary"], anchor="w").pack(side=tk.LEFT, padx=(6, 0))
            return cb

        v["skills_enforced"] = tk.BooleanVar(value=self.cfg.getboolean(
            "assistant", "skills_enforced", fallback=True))
        cb_skill = force_check(t["settings_skills_force"], v["skills_enforced"])
        # 强制固定记忆 = 记忆总开关（关掉后不注入也不保存，当轮生效）
        v["mem_enabled"] = tk.BooleanVar(value=self.cfg.getboolean(
            "memory", "enabled", fallback=True))
        cb_mem = force_check(t["settings_mem_force"], v["mem_enabled"])

        force_hint = tk.Label(nb, text=t["force_hint_default"], bg=th["bg_primary"],
                              fg=th["fg_tertiary"], font=FONT_TINY, anchor="w",
                              justify="left", wraplength=500)
        force_hint.pack(fill=tk.X, pady=(2, 0))

        def _apply_force(*_a):
            """勾一下就把设置落盘并用上——不依赖底部的「保存」。"""
            running = bool(getattr(self, "running", False))
            try:
                self.cfg.set("assistant", "skills_enforced",
                             "true" if v["skills_enforced"].get() else "false")
                self.cfg.set("memory", "enabled",
                             "true" if v["mem_enabled"].get() else "false")
                self._save_cfg()
            except Exception as e:
                force_hint.configure(text="✘ %s" % e, fg=th["red"])
                return
            msg = t["force_next_round"] if running else t["force_applied"]
            force_hint.configure(text="✔ " + msg, fg=th["green"])
            try:
                self.chat.note("hint", "✔ " + msg)
            except Exception:
                pass

        for _cb in (cb_skill, cb_mem):
            _cb.configure(command=_apply_force)
        section(t["settings_budget"])
        field("max_history", t["settings_history"],
              str(self.cfg.getint("assistant", "max_history", fallback=8)))
        field("max_steps", t["settings_steps"],
              str(self.cfg.getint("agent", "max_steps", fallback=6)))
        field("tool_output_chars", t["settings_tool_chars"],
              str(self.cfg.getint("agent", "tool_output_chars", fallback=2000)))
        field("workspace", t["settings_ws"], self.cfg.get("agent", "workspace", fallback=""), True)
        section(t["settings_perm"])
        tk.Label(nb, text=t["gear_desc"], bg=th["bg_primary"],
                 fg=th["fg_tertiary"], font=FONT_TINY, anchor="w").pack(fill=tk.X)
        row = tk.Frame(nb, bg=th["bg_primary"])
        row.pack(fill=tk.X, pady=(2, 0))
        perm = tk.StringVar(value=self.perm_mode)
        v["perm"] = perm
        for val, txt in (("auto", t["gear_auto"]), ("ask", t["gear_ask"]),
                         ("strict", t["gear_strict"]), ("locked", t["gear_locked"])):
            tk.Radiobutton(row, text=txt, variable=perm, value=val, font=FONT_SMALL,
                           bg=th["bg_primary"], fg=th["fg_secondary"],
                           selectcolor=th["bg_card"],
                           activebackground=th["bg_primary"]).pack(side=tk.LEFT, padx=(0, 12))

        # ---- 记忆分组（对齐官方 settings.group.memory）----
        # 总开关（强制固定记忆）已挪到思考档位下面，这里只剩自动记忆等细节
        section(t["settings_memory"])
        mem_auto = tk.BooleanVar(value=self.cfg.getboolean("memory", "auto", fallback=False))
        v["mem_auto"] = mem_auto

        def mem_check(label, var, desc=""):
            fr = tk.Frame(nb, bg=th["bg_primary"])
            fr.pack(fill=tk.X, pady=(2, 0))
            tk.Checkbutton(fr, text=label, variable=var, font=FONT_SMALL,
                           bg=th["bg_primary"], fg=th["fg_primary"],
                           selectcolor=th["bg_card"], activebackground=th["bg_primary"],
                           anchor="w").pack(side=tk.LEFT)
            if desc:
                tk.Label(fr, text=desc, font=FONT_TINY, bg=th["bg_primary"],
                         fg=th["fg_tertiary"], anchor="w").pack(side=tk.LEFT, padx=(6, 0))

        mem_check(t["settings_mem_auto"], mem_auto)
        field("mem_inject", t["settings_mem_inject"],
              str(self.cfg.getint("memory", "max_inject", fallback=20)))
        field("mem_keep", t["settings_mem_keep"],
              str(self.cfg.getint("memory", "max_keep", fallback=200)))

        tk.Label(nb, text=t["mem_edit_hint"], bg=th["bg_primary"],
                 fg=th["fg_secondary"], font=FONT_SMALL, anchor="w",
                 justify="left").pack(fill=tk.X, pady=(8, 2))
        mem_box = tk.Text(nb, wrap=tk.WORD, font=FONT_SMALL, bg=th["bg_card"],
                          fg=th["fg_primary"], relief="flat", borderwidth=1,
                          highlightthickness=1, padx=8, pady=6, height=10,
                          insertbackground=th["fg_primary"])
        mem_box.pack(fill=tk.X, pady=(0, 4))

        def _mem_obj():
            m = engine.Memory(facts_path=engine.FACTS_PATH)
            m.apply_config(self.cfg)
            return m

        def _reload():
            mo = _mem_obj()
            mo.load_md()
            mem_box.delete("1.0", tk.END)
            mem_box.insert("1.0", mo.to_md())
            cnt_lb.configure(text=t["mem_count"] % len(mo.facts))
            return mo

        def _save_mem():
            mo = _mem_obj()
            n = mo.set_facts_from_text(mem_box.get("1.0", tk.END))
            cnt_lb.configure(text=t["mem_count"] % n)
            self.chat.note("hint", t["mem_saved"] % n)

        def _clear_mem():
            from tkinter import messagebox
            if not messagebox.askyesno(t["mem_clear"], t["delete_confirm"], parent=d):
                return
            mo = _mem_obj()
            mo.forget_all()
            _reload()
            self.chat.note("hint", t["mem_cleared"])

        row_m = tk.Frame(nb, bg=th["bg_primary"])
        row_m.pack(fill=tk.X, pady=(2, 0))
        for txt, cmd in ((t["mem_save"], _save_mem),
                         (t["mem_reload"], _reload),
                         (t["mem_clear"], _clear_mem)):
            tk.Button(row_m, text=txt, font=FONT_SMALL, relief="flat",
                      bg=th["bg_card"], fg=th["fg_primary"], cursor="hand2",
                      activebackground=th["bg_input"], command=cmd).pack(
                          side=tk.LEFT, padx=(0, 8), ipadx=10, ipady=4)
        cnt_lb = tk.Label(row_m, text="", font=FONT_TINY, bg=th["bg_primary"],
                          fg=th["fg_tertiary"])
        cnt_lb.pack(side=tk.LEFT)
        _reload()

        def _ensure(sec):
            # 老版本 ini 没有 [memory] 段，直接 set 会抛 NoSectionError
            if not self.cfg.has_section(sec):
                self.cfg.add_section(sec)

        def save():
            for key in ("base_url", "api_key", "model", "proxy"):
                self.cfg.set("llm", key, v[key].get().strip())
            self.cfg.set("llm", "thinking", v["thinking"].get() or "off")
            # 两个强制开关：保存后下一轮请求立刻生效（engine 每轮读 ini）
            self.cfg.set("assistant", "skills_enforced",
                         "true" if v["skills_enforced"].get() else "false")
            self.cfg.set("assistant", "lang", getattr(self, "lang", "zh"))
            # api.md 同步：把这次填的值写回所选预设段（手改 api.md 也会被读到）
            try:
                old_presets, _act = engine.load_api_presets()
                name = (v.get("api_preset").get() if v.get("api_preset") else "") or "custom"
                data = [(n, dict(d)) for n, d in old_presets]
                found = False
                for n, d in data:
                    if n == name:
                        found = True
                        d["base_url"] = v["base_url"].get().strip()
                        d["api_key"] = v["api_key"].get().strip()
                        d["model"] = v["model"].get().strip()
                if not found:
                    data.append((name, {"label": name,
                                        "base_url": v["base_url"].get().strip(),
                                        "api_key": v["api_key"].get().strip(),
                                        "model": v["model"].get().strip()}))
                engine.save_api_presets(data, active=name)
            except Exception:
                pass
            for sec, key in (("llm", "max_tokens"), ("assistant", "max_history"),
                             ("agent", "max_steps"), ("agent", "tool_output_chars")):
                val = v[key].get().strip()
                if val.isdigit():
                    self.cfg.set(sec, key, val)
            self.cfg.set("agent", "workspace", v["workspace"].get().strip())
            if not self.cfg.has_option("agent", "auto_approve"):
                self.cfg.set("agent", "auto_approve", "false")
            _ensure("memory")
            self.cfg.set("memory", "enabled", "true" if v["mem_enabled"].get() else "false")
            self.cfg.set("memory", "auto", "true" if v["mem_auto"].get() else "false")
            for key in ("mem_inject", "mem_keep"):
                val = v[key].get().strip()
                if val.isdigit() and int(val) > 0:
                    self.cfg.set("memory", "max_inject" if key == "mem_inject" else "max_keep",
                                 val)
            # 记忆文本框的内容也要跟着存，否则用户改完记忆点"保存"就丢了
            try:
                _save_mem()
            except Exception:
                pass
            self._save_cfg()
            self.perm_mode = v["perm"].get()
            save_ui_state(self._state_dict())
            self._refresh_header()
            d.destroy()

        # 保存按钮固定在窗口底部，不随内容滚动、不被内容挤压
        bar = tk.Frame(d, bg=th["bg_primary"])
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=18, pady=(4, 14))
        tk.Button(bar, text=t["save"], font=FONT_BOLD, relief="flat",
                  bg=th["accent_brand"], fg=th["fg_on_brand"], cursor="hand2",
                  command=save).pack(fill=tk.X, ipady=8)
    def _save_cfg(self):
        try:
            with open(engine.CONFIG_PATH, "w", encoding="utf-8") as f:
                self.cfg.write(f)
        except Exception as e:
            self.chat.note("error", _tr("保存配置失败：%s", "Could not save settings: %s") % e)

    # ------------------------------------------------------------ 主题/语言

    def _state_dict(self):
        return {"mode": self.mode, "perm": self.perm_mode,
                "sidebar": self.sidebar.winfo_ismapped(),
                "last_session": self.cur_session, "lang": getattr(self, "lang", "zh")}




    def _copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ------------------------------------------------------------ 语言切换

    def toggle_lang(self):
        """中英切换：立即重绘界面，并把选择写进 ui_state.json（下次开机沿用）。"""
        if self.running:
            try:
                self.chat.note("warn", "▲ " + self.t.get("lang_busy", ""))
            except Exception:
                pass
            return
        self.lang = "en" if self.lang != "en" else "zh"
        UI_LANG[0] = self.lang
        self.t = TEXT_EN if self.lang == "en" else TEXT
        try:
            self.cfg.set("assistant", "lang", self.lang)
            self._save_cfg()
        except Exception:
            pass
        try:
            save_ui_state(self._state_dict())
        except Exception:
            pass
        self._rebuild_ui()

    def _rebuild_ui(self):
        """把整个界面按当前语言重建（状态都挂在 self 上，不怕重建）。"""
        sid = self.cur_session
        self._preview_destroy()
        try:
            for w in self.root.winfo_children():
                w.destroy()
        except Exception:
            pass
        self.root.configure(bg=self.th["bg_primary"])
        try:
            self.root.title("%s  %s" % (self.t["app_title"], APP_BUILD))
        except Exception:
            pass
        self._build_ui()
        self._bind_keys()
        try:
            refresh_drop_targets(self.root)
        except Exception:
            pass
        if sid:
            try:
                self.switch_session(sid)
            except Exception:
                pass
        self._refresh_header()

    def _on_close(self):
        save_ui_state(self._state_dict())
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# 渲染计时包装（放在类定义之后，避免影响方法内部的 self 调用）
for _m in ("add_assistant", "add_user", "add_tool_card"):
    if hasattr(ChatView, _m):
        setattr(ChatView, _m, _timed_render(getattr(ChatView, _m)))


# 兼容别名（老脚本/测试仍在用）
WorkBuddyApp = MingShuApp


def _enable_dpi_aware():
    """声明 DPI 感知：Win7 用 user32.SetProcessDPIAware（Vista+），
    8.1+ 优先 shcore。不做的话系统会虚拟化拉伸，坐标/截图都会偏移。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    _enable_dpi_aware()
    # 任务栏分组 ID：不设的话 Win7 会把窗口和 python.exe 归一组，
    # 任务栏就显示 Python 图标而不是我们的图标。
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            u"MingShu.Win7.DesktopAgent")
    except Exception:
        pass
    # pythonw 没有控制台，任何原生崩溃（access violation 等）都看不见。
    # faulthandler 会把崩溃时的调用栈写进 fault.log，下次闪退就有据可查。
    fault_file = None
    try:
        import faulthandler
        fault_file = open(os.path.join(DATA_DIR, "fault.log"), "a", encoding="utf-8")
        faulthandler.enable(file=fault_file, all_threads=True)
    except Exception:
        pass

    try:
        app = MingShuApp()
        app.run()
    except SystemExit:
        raise
    except Exception:
        # 任何启动/运行期异常：写 crash.log + 弹窗提示，避免"闪退且无信息"
        import traceback
        tb = traceback.format_exc()
        try:
            with open(os.path.join(DATA_DIR, "crash.log"), "w", encoding="utf-8") as f:
                f.write("MingShu Win7 - crash log\n")
                f.write("python: %s\n" % sys.version)
                f.write(tb)
        except Exception:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror(
                _tr("明枢Win7 启动失败", "MingShu Win7 failed to start"),
                _tr("程序出错了，详细信息已写入程序目录下的 data\\crash.log\n\n",
                    "Something went wrong. Details were written to data\\crash.log\n\n")
                + tb[-1500:])
        except Exception:
            print(tb)
        raise


if __name__ == "__main__":
    main()
