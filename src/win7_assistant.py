# -*- coding: utf-8 -*-
"""
Win7 个人 AI 助手（Agent 版） -- 明枢Win7 的轻量单机版
====================================================================
为什么做这个：
  OpenClaw 需要 Node.js 22+，而 Node 18+ 官方只支持 Win10+；
  主流同类助手（Electron 应用）同样只要 Win10+。
  本程序只用 Python 标准库，Python 3.8.10（Win7 最后一个官方支持版本）
  即可运行，零第三方依赖。

Agent 能力（v2）：
  助手可以自己浏览你的电脑——列目录、读文件、全文搜索、执行命令、
  写文件、打开文件、看系统信息、抓网页——并且多步思考、根据结果
  自主决定下一步，最后用中文汇报（像专业桌面 Agent 那样工作）。
  危险操作（执行命令 / 写文件 / 打开文件）默认弹窗征求你的同意。

三种用法：
    python win7_assistant.py              # 桌面窗口聊天（默认，Agent 模式）
    python win7_assistant.py --cli        # 命令行聊天
    python win7_assistant.py --telegram   # Telegram 机器人（手机随时聊）
    python win7_assistant.py --chat       # 强制纯聊天模式（不用工具）
    python win7_assistant.py --check      # 只自检配置，不启动

支持任意 OpenAI 兼容接口（建议支持 function calling）：
  DeepSeek / 通义千问 / Kimi / OpenAI / Ollama 等。
  即使接口不支持 tools，也可用 ```tool 代码块协议降级工作。

持久记忆：滚动对话历史 memory.json + 长期事实 facts.json。
"""

import argparse
import configparser
import ctypes
import difflib
import fnmatch
import http.client
import json
import os
try:
    import win7_limits as limits
except Exception:            # 极端环境没有 ctypes 也不能崩
    limits = None
import platform
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:                      # winreg 只在 Windows 有；非 Windows 下导入失败不影响其它功能
    import winreg
except ImportError:
    winreg = None

# 目录布局：
#   ROOT/           exe、bat、记忆.md、api.md、assets、skills
#   ROOT/src/       运行代码（源码运行时本文件所在）
#   ROOT/data/      配置、会话、日志、facts 等可写数据
#   ROOT/runtime/   便携 Python
# onefile 运行时 __file__ 在临时解包目录，ROOT 必须取 exe 所在目录。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    ROOT_DIR = BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
try:
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    pass
CONFIG_PATH = os.path.join(DATA_DIR, "assistant.ini")
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
FACTS_PATH = os.path.join(DATA_DIR, "facts.json")
# 给人看的记忆文档：可以直接用记事本编辑，改完下次启动自动同步回来
MEMORY_MD = os.path.join(ROOT_DIR, "记忆.md")

MAX_TOOL_OUTPUT = 2000   # 单个工具结果回传给模型的最大字符数（可在 ini 里改）
TOOL_LIMIT = [MAX_TOOL_OUTPUT]   # 运行时按配置覆盖
LAST_USAGE = {}                  # 最近一次请求的 usage
LAST_FINISH = {}                 # 最近一次请求的 finish_reason
MAX_STEPS = 12           # Agent 单次任务最大行动步数

DEFAULT_INI = """[llm]
# 任意 OpenAI 兼容接口（base_url 结尾带不带斜杠都行）
# DeepSeek（便宜、中文好，支持 function calling，推荐） : https://api.deepseek.com/v1
#   模型 deepseek-flash（快、便宜，日常用这个）/ deepseek-v4-pro（最强，贵）
#   注意：旧名 deepseek-chat / deepseek-reasoner 官方已于 2026-07-24 弃用（现在只是转发别名，随时会关）
# 通义千问（dashscope 兼容模式，支持 function calling）: https://dashscope.aliyuncs.com/compatible-mode/v1   模型 qwen-plus
# Kimi                     : https://api.moonshot.cn/v1         模型 moonshot-v1-8k
# 本地 Ollama              : http://127.0.0.1:11434/v1          key 随意填   模型 qwen2.5:7b
base_url = https://api.deepseek.com/v1
api_key = 在这里填你的APIKey
model = deepseek-flash
# 单次回复最大 token 数（限长=省钱；0 表示不限制）
max_tokens = 1024
# 思考档位：off / low / high / max。仅对 DeepSeek V4 系列等"默认带思考"的模型有效
#   off  = 关闭思考，最快最省（日常问答建议）
#   low  = 少量思考，复杂任务性价比不错
#   high = 默认档（接口不传时的行为）
#   max  = 全力思考，慢且贵，留给难题
# 留空 = 不改接口默认值（DeepSeek 默认 high）。别的厂商不认这个参数，请留空
thinking = off
# Win7 上 HTTPS 抽风时才需要填，例如 http://127.0.0.1:7890 ；平时留空
proxy =
# 备用线路（逗号分隔）。填了就自动并发测一遍延迟，选最快的那条用。
#   例：mirrors = https://api.deepseek.com/v1, https://你的中转站/v1
#   不填 = 只用上面 base_url，也不发任何额外测速请求
mirrors =
# true = 每次启动测一次线路（只发一个 GET /models，不烧 token），结果缓存 30 分钟
auto_pick_fastest = true
# true = 复用 TCP/TLS 连接，省掉每次握手（提速明显；出问题自动退回普通请求）
keepalive = true
# 下载 GitHub 等外网资源时自动挑国内加速镜像（内置 gh-proxy.com 等多个，测速取最快）
#   auto = 自动（默认）/ off = 永远直连
mirror_boost = auto
# 自定义下载镜像前缀（逗号分隔，留空用内置列表）。用法 = 前缀 + 完整原链接
#   例：download_mirrors = https://gh-proxy.com/, https://ghfast.top/
download_mirrors =

[assistant]
system_prompt = 你是一个运行在用户自己电脑上的个人助手，回答简洁、实用，一律用中文。
max_history = 8
# 把文件拖进窗口；万一拖放导致闪退，改成 false（仍可用「▤ 文件」按钮选文件）
enable_drop = true
# 强制执行 Skill：false = 技能库清单不进提示词、load_skill 工具不可用（省 token）
skills_enforced = true

[agent]
# 单个工具结果回传上限（字符），越小越省 token
tool_output_chars = 1500
# 单次任务最大行动步数（越小越省 token）
max_steps = 6
# 单轮最多挂载多少个工具；0 = 全部挂载（默认）
max_tools = 0
# 内存墙（MB）：本程序超过这个内存由内核直接杀掉，不影响用户的其它程序
mem_limit_mb = 300
# 同时最多几个子进程（防失控自我拉起）
max_procs = 4
# CPU 墙：thread = 只把工作线程降到空闲优先级（界面照样流畅，推荐）
#        process = 整个进程 IDLE_PRIORITY_CLASS（最省 CPU，界面点击会略慢）
#        below = 进程 BELOW_NORMAL / off = 不加
cpu_wall = thread
# true = 执行命令/写文件/打开文件不再询问，直接执行（谨慎开启）
auto_approve = false
# 智能权限等级：auto 自动 / ask 询问 / strict 严格 / locked 锁死
#   auto   免打扰到 L1（只读 + 写 logs/），L2/L3 仍会问你
#   ask    免打扰到 L2（再加写你自己的文件、打开程序），L3 需明确授权
#   strict 只放 L0 只读，L2/L3 直接拒绝
#   locked 全部拒绝
perm_gear = ask
# 限制助手只能操作这个目录及其子目录；留空 = 不限制（可操作整台电脑）
# 例如 workspace = C:\\Users\\你的用户名
workspace =

[memory]
# 长期记忆：说「记住：xxx」或让模型调用 remember 存下来的事实，每次任务前会固定注入一遍
enabled = true
# 自动记忆：开启后，模型学到关于用户/环境的持久事实（姓名、偏好、常用路径、项目约定）时
#   会主动调用 remember 存下来；一次性内容不会存
auto = true
# 每次任务注入给模型的记忆条数（越多越占 token）
max_inject = 20
# facts.json 里最多保留多少条，超出自动淘汰最旧的
max_keep = 200

[telegram]
# 找 @BotFather 创建机器人获得 token；allowed_chat_ids 留空表示不限制
bot_token =
allowed_chat_ids =
"""

# 说这些话就把内容存进长期记忆，不调用模型
REMEMBER_PREFIXES = ("记住：", "记住:", "请记住：", "请记住:", "remember:", "remember：")

# 需要用户批准才能执行的工具
DANGEROUS_TOOLS = ("run_cmd", "write_file", "open_path")

# ------------------------------------------------------------ 四级权限模型
#
#   L0 只读   列目录、读文件、看进程、查端口、看注册表      → 随便跑
#   L1 写自己 写日志、写抓包、写报告，只准进 logs/        → 不用问
#   L2 改配置 写用户自己的文件、改预设、打开程序            → 必须先问
#   L3 动系统 执行命令、发包扫描、抓包、改网络设置          → 必须明确授权
#
# 档位（用户可切）：auto=自动(免打扰到 L1) / ask=询问(免打扰到 L2)
#                  strict=严格(只放 L0)  / locked=锁死(全拒)
PERM_GEARS = {
    "auto":   {"max": "L1", "label": "🟢 自动"},
    "ask":    {"max": "L2", "label": "🟡 询问"},
    "strict": {"max": "L0", "label": "🟠 严格"},
    "locked": {"max": None, "label": "🔴 锁死"},
}
PERM_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

TOOL_LEVEL = {
    "list_dir": "L0", "read_file": "L0", "search_files": "L0", "grep_files": "L0",
    "sys_info": "L0", "net_list": "L0", "proc_list": "L0", "reg_query": "L0",
    "compare": "L0", "recall": "L0", "remember": "L0", "schedule_list": "L0",
    "detect_preset": "L0", "load_skill": "L0",
    "web_fetch": "L0",
    "net_sniff": "L3", "run_cmd": "L3", "net_scan": "L3",
    "open_path": "L2", "schedule_add": "L2", "schedule_del": "L2",
    "write_file": "L2",          # 目标在 logs/ 内时降到 L1，见 tool_level()
    "app_launch": "L2",          # 后台启动程序（诊断 GUI 用），要批准
    "proc_kill": "L2",           # 结束进程，要批准
    "restore_file": "L2",        # 从备份恢复（也是覆盖文件），要批准
    "download_file": "L2",       # 下载到 logs/ 内时降到 L1，见 tool_level()
    "proc_windows": "L0",        # 纯数据面查窗口，只读
}

LOGS_DIR = os.path.join(DATA_DIR, "logs")
BACKUP_DIR = os.path.join(LOGS_DIR, "backup")     # write_file 覆盖前的自动备份
APPRUN_DIR = os.path.join(LOGS_DIR, "apprun")     # app_launch 后台启动的输出日志
AUDIT_PATH = os.path.join(LOGS_DIR, "audit.log")

LEVEL_DESC = {
    "L0": "只读", "L1": "写 logs/", "L2": "改配置", "L3": "动系统",
}


def _in_logs(p):
    """路径是否在程序自己的 logs/ 目录里（L1 的唯一合法落点）。"""
    try:
        rp = os.path.realpath(p).lower()
        ld = os.path.realpath(LOGS_DIR).lower()
        return rp == ld or rp.startswith(ld + os.sep)
    except Exception:
        return False


# 只读命令白名单：这些命令只是"看"，不会改任何东西，没必要每次弹权限卡片。
# 判断偏保守——只要命令里出现写操作信号（重定向、删除、写文件、POST…）就整条不算只读。
_RO_BAD = (">", ">>", "out-file", "remove-item", "del ", "rm ", "rmdir", "erase ",
           "new-item", "copy-item", "copy ", "xcopy", "move ", "move-item", "rename",
           "ren ", "mkdir", "md ", "ni ", "set-content", "add-content", "set-item",
           "reg add", "reg delete", "netsh ", "taskkill", "stop-process", "kill ",
           "start-process", "restart", "shutdown", "format", "choco ", "winget ",
           "pip install", "npm i", "npm install", "invoke-expression", "iex ",
           "-method post", "-method put", "-method delete", "-method patch",
           "-outfile", " -o ", "--output", " -d ", "--data", "-infile", "&&", "; ")
_RO_GOOD = ("invoke-webrequest", "invoke-restmethod", "iwr ", "curl", "wget",
            "git status", "git log", "git diff", "git show", "git branch",
            "git ls-remote", "git remote -v", "git config --get",
            "dir", "ls ", "ls\"", "type ", "cat ", "more ", "echo ", "find ",
            "findstr", "select-string", "ipconfig", "getmac", "systeminfo",
            "tasklist", "netstat", "nslookup", "ping ", "tracert", "pathping",
            "arp ", "route print", "reg query", "where ", "which ", "hostname",
            "whoami", "ver", "date /t", "time /t", "wmic ", "get-childitem",
            "get-content", "get-process", "get-service", "get-item", "test-netconnection")


def cmd_is_readonly(command):
    """这条命令是不是纯读取？是就当 L0 放行（只在审计日志里留痕）。"""
    c = (command or "").strip()
    if not c:
        return False
    low = c.lower()
    for bad in _RO_BAD:
        if bad in low:
            return False
    return any(g in low for g in _RO_GOOD)


def tool_level(name, args=None):
    """工具的权限层级。write_file 按目标路径动态分级：logs/ 内 L1，外面 L2。"""
    if name == "write_file":
        p = resolve_path((args or {}).get("path", ""))
        return "L1" if _in_logs(p) else "L2"
    if name == "run_cmd":
        # 纯读取（Invoke-WebRequest / curl / git log / dir / reg query …）不算"动系统"，
        # 按 L0 放行；带写操作信号的仍然走 L3 要批准
        return "L0" if cmd_is_readonly((args or {}).get("command", "")) else "L3"
    if name == "download_file":
        p = resolve_path((args or {}).get("path", ""))
        return "L1" if _in_logs(p) else "L2"
    if name == "net_sniff":
        # 抓包本身是 L3，但把包存进 logs/ 只是写自己的目录，不额外提级
        return "L3"
    return TOOL_LEVEL.get(name, "L2")     # 没登记的工具按最严的 L2 算，宁严勿松


def _gear_of(cfg):
    g = (cfg.get("agent", "perm_gear", fallback="") or "").strip().lower()
    return g if g in PERM_GEARS else "ask"


def perm_decision(cfg, level):
    """返回 (要不要问, 允不允许)。level 是 "L0".."L3"。"""
    gear = _gear_of(cfg)
    lv = PERM_ORDER.get(level, 2)
    top = PERM_GEARS[gear]["max"]
    if top is None:
        return (False, False)                       # 锁死：全部拒绝
    if lv <= PERM_ORDER[top]:
        return (False, True)                        # 在免打扰范围内，直接放行
    if gear == "strict":
        return (False, False)                       # 严格：超出 L0 一律拒绝
    if lv == 3:
        return (True, True)                         # L3：要问，且必须明确授权
    return (True, True)                             # L2：要问


def perm_hint(cfg, name, level):
    """被拒绝时告诉用户该怎么办：切哪个档位。"""
    gear = _gear_of(cfg)
    g = PERM_GEARS[gear]["label"]
    need = {"L0": "任意档位都放行", "L1": "「自动」或「询问」档放行",
            "L2": "「询问」档放行", "L3": "「询问」档 + 明确授权"}[level]
    return ("当前权限档位是 %s，%s（%s）不在免打扰范围内。\n"
            "需要 %s。可在顶栏权限档位一键切换，或这轮先跳过这个操作。"
            % (g, name, LEVEL_DESC.get(level, level), need))


# ------------------------------------------------------------ 审计日志

_AUDIT_LOCK = threading.Lock()


def _audit_args_text(args):
    """把参数压成一行，避免日志被长内容撑爆。"""
    if not isinstance(args, dict):
        return str(args)[:120]
    bits = []
    for k in ("path", "host", "command", "key", "pattern", "keyword", "url",
              "name", "when", "action", "ports", "kind", "filter", "fact", "value"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            bits.append("%s=%s" % (k, v.strip().replace("\n", " ")[:80]))
    if not bits:
        bits.append("(无参数)" if not args else json.dumps(args, ensure_ascii=False)[:100])
    return " ".join(bits)


def audit_log(level, result, tool, args=None, reason="", gear=""):
    """写一行审计日志。

    格式：[时间戳] [P层级] [ALLOW|DENY] [工具] 参数 reason=xxx
    L0/L1 免打扰放行也记——审计要能回答"它到底动过什么"，
    只记危险操作的话，"读过哪些文件"这种问题就无据可查。
    """
    lvl = "P" + level.lstrip("L")
    res = "ALLOW" if result in ("allow", "auto", True) else "DENY"
    if not reason:
        reason = "explicit_auth" if res == "ALLOW" else "user_denied"
    line = "[%s] [%s] [%s] [%s] %s reason=%s%s" % (
        time.strftime("%Y-%m-%dT%H:%M:%S"), lvl, res, tool,
        _audit_args_text(args), reason, (" gear=%s" % gear) if gear else "")
    try:
        with _AUDIT_LOCK:
            d = os.path.dirname(AUDIT_PATH)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(AUDIT_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass                      # 日志写不进去不能影响主流程
    return line


def tool_audit_log(tail=30, tool="", result="", since=""):
    """查看/筛选审计日志。tail=最近 N 行。"""
    if not os.path.isfile(AUDIT_PATH):
        return "还没有审计日志（logs/audit.log）。跑过一次工具之后就会生成。"
    try:
        with open(AUDIT_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = [x.rstrip("\n") for x in f if x.strip()]
    except Exception as e:
        return "审计日志读不了：%s" % e
    if tool:
        lines = [x for x in lines if ("[%s]" % tool) in x]
    if result:
        want = "ALLOW" if result.lower().startswith("a") else "DENY"
        lines = [x for x in lines if ("[%s]" % want) in x]
    if since:
        lines = [x for x in lines if x[1:20] >= since]
    if not lines:
        return "没有符合条件的审计记录。"
    shown = lines[-int(tail):] if tail else lines
    return "共 %d 条，显示最近 %d 条：\n%s" % (len(lines), len(shown), "\n".join(shown))


# 极域协议常量（与 app\jy_autodetect.py 一致）：
#   主通道组播固定 224.50.50.42:4705，不分频道；
#   会话组播随频道变化：组 225.2.(channel+1).1，端口 5000 + channel*512
JY_MAIN_GROUP, JY_MAIN_PORT = "224.50.50.42", 4705
S_BASE, S_STRIDE = 5000, 0x200
MAX_CHANNEL = 32

JY_REG_KEYS = [
    (r'SOFTWARE\WOW6432Node\TopDomain\e-Learning Class\Student', "student"),
    (r'SOFTWARE\TopDomain\e-Learning Class\Student', "student32"),
    (r'SOFTWARE\WOW6432Node\TopDomain\e-Learning Class V6.0', "product"),
    (r'SOFTWARE\TopDomain\e-Learning Class V6.0', "product32"),
    (r'SOFTWARE\WOW6432Node\TopDomain\e-Learning Class Standard\1.00', "setup"),
]


def _reg_read_tree(path):
    """读注册表某个键下的全部值，失败返回 None。"""
    if winreg is None:
        return None
    try:
        h = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except Exception:
        return None
    out = {}
    try:
        for i in range(winreg.QueryInfoKey(h)[1]):
            try:
                nm, vd, _ = winreg.EnumValue(h, i)
                out[nm] = ("<%d 字节>" % len(vd)) if isinstance(vd, bytes) else vd
            except OSError:
                continue
    finally:
        try:
            winreg.CloseKey(h)
        except Exception:
            pass
    return out


def _nic_list():
    """枚举本机 IPv4 网卡：别名、IP、前缀长度、网关。

    优先用 .NET（和模拟器本体同一套来源）；拿不到就退回 ipconfig 解析。
    """
    nics = []
    if os.name == "nt":
        ps = (
            "$ErrorActionPreference='Stop'; "
            "foreach($nic in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) { "
            "if($nic.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up) { continue }; "
            "$props=$nic.GetIPProperties(); $gateway=''; "
            "foreach($gw in $props.GatewayAddresses) { "
            "if($gw.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) { "
            "$gateway=$gw.Address.IPAddressToString; break } }; "
            "foreach($addr in $props.UnicastAddresses) { "
            "if($addr.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }; "
            "\"{0}`t{1}`t{2}`t{3}\" -f "
            "$addr.Address.IPAddressToString,$nic.Name,$gateway,$addr.PrefixLength } }"
        )
        try:
            p = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, timeout=15, **hidden_kwargs())
            for line in _decode_stream(p.stdout).splitlines():
                parts = line.strip().split("\t")
                if len(parts) != 4:
                    continue
                ip, alias, gw, prefix = parts
                if not ip or ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                try:
                    nics.append({"alias": alias, "ip": ip,
                                 "prefix": int(prefix), "gateway": gw or "0.0.0.0"})
                except ValueError:
                    continue
        except Exception:
            pass
    return nics


def _channel_of_group(g):
    """225.2.X.1 -> 频道 X-1。模拟器里会话组是 225.2.(channel+1).1。"""
    if not g or not g.startswith("225.2."):
        return None
    parts = g.split(".")
    if len(parts) != 4:
        return None
    try:
        ch = int(parts[2]) - 1
    except ValueError:
        return None
    return ch if 1 <= ch <= MAX_CHANNEL else None


def _mcast_scan(seconds=2):
    """逐个加入频道对应的会话组播组并监听，返回有流量的组。

    会话组 = 225.2.(ch+1).1 : 5000 + ch*512，不需要管理员权限。
    """
    import socket
    import struct
    import select
    socks = []
    for ch in range(1, MAX_CHANNEL + 1):
        group = "225.2.%d.1" % (ch + 1)
        port = S_BASE + ch * S_STRIDE
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4s4s", socket.inet_aton(group),
                                     socket.inet_aton("0.0.0.0")))
            s.setblocking(False)
            socks.append((s, group, port))
        except Exception:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    if not socks:
        return []
    counts, srcs = {}, {}
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            try:
                rr, _, _ = select.select([x[0] for x in socks], [], [], 0.2)
            except Exception:
                break
            for s in rr:
                try:
                    _data, addr = s.recvfrom(2048)
                except Exception:
                    continue
                grp = None
                for ss, g, _p in socks:
                    if ss is s:
                        grp = g
                        break
                if not grp:
                    continue
                counts[grp] = counts.get(grp, 0) + 1
                srcs.setdefault(grp, set()).add(addr[0])
    finally:
        for s, _g, _p in socks:
            try:
                s.close()
            except Exception:
                pass
    out = [(g, counts[g], sorted(srcs.get(g, []))) for g in counts]
    out.sort(key=lambda x: -x[1])
    return out


def _port_owners(ports):
    """查这些端口现在被谁占着。"""
    owners = dict((p, None) for p in ports)
    try:
        p = subprocess.run("netstat -ano", shell=True, capture_output=True,
                           timeout=30, **hidden_kwargs())
        names = _pid_names()
        for line in _decode_stream(p.stdout).splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            local, pid = parts[1], parts[-1]
            if ":" not in local:
                continue
            try:
                port = int(local.rsplit(":", 1)[1])
            except ValueError:
                continue
            if port in owners and owners[port] is None:
                who = names.get(int(pid), "") if pid.isdigit() else ""
                owners[port] = ("%s (PID %s)" % (who, pid)) if who else ("PID %s" % pid)
    except Exception:
        pass
    return [(p, owners[p]) for p in ports]


def tool_detect_preset(seconds=2, scan_all=False):
    """自动探测极域教师端模拟器需要的预设值，换台机器不用手填。

    读注册表、找学生端进程、枚举网卡、查端口占用；scan_all=true 时
    还会逐个试听 32 个频道的会话组播组，直接告诉你真教师在哪个频道。
    """
    try:
        seconds = max(1, min(10, int(seconds)))
    except Exception:
        seconds = 2

    lines = ["【本机预设探测】"]
    found_channel = None
    where = ""

    # 1) 注册表：学生端/产品配置里可能直接写着频道
    for path, tag in JY_REG_KEYS:
        tree = _reg_read_tree(path)
        if not tree:
            continue
        lines.append("")
        lines.append("注册表 %s：" % tag)
        for k, v in tree.items():
            lines.append("  %-24s = %s" % (k, v))
            if k.lower() in ("channel", "classchannel", "教室频道"):
                try:
                    c = int(v)
                    if 1 <= c <= MAX_CHANNEL:
                        found_channel, where = c, "注册表 %s" % tag
                except Exception:
                    pass

    # 2) 学生端进程
    pids = []
    try:
        p = subprocess.run("tasklist /fo csv /nh", shell=True, capture_output=True,
                           timeout=30, **hidden_kwargs())
        for line in _decode_stream(p.stdout).splitlines():
            f = line.split('","')
            if len(f) < 2:
                continue
            nm = f[0].lstrip('"').strip()
            if "student" in nm.lower():
                pids.append("%s(%s)" % (nm, f[1].strip().strip('"')))
    except Exception:
        pass
    lines.append("")
    lines.append("学生端进程：%s" % ("、".join(pids) if pids else "未发现"))

    # 3) 网卡
    nics = _nic_list()
    if nics:
        lines.append("")
        lines.append("本机网卡：")
        for n in nics:
            best = n["gateway"] and n["gateway"] != "0.0.0.0"
            lines.append("  %-18s %-15s/%-2d 网关=%-15s%s" % (
                n["alias"], n["ip"], n["prefix"], n["gateway"],
                "  <-- 推荐" if best else ""))

    # 4) 频道组播试听（可选，最有说服力）
    if scan_all:
        hits = _mcast_scan(seconds)
        if hits:
            lines.append("")
            lines.append("【频道扫描】这些会话组有流量：")
            for g, cnt, src in hits:
                ch = _channel_of_group(g)
                lines.append("  %-16s %4d 个包  来自 %s%s" % (
                    g, cnt, ",".join(src[:3]),
                    "  → 频道 %d" % ch if ch else ""))
            top_ch = _channel_of_group(hits[0][0])
            if top_ch:
                found_channel, where = top_ch, "组播试听 %s" % hits[0][0]
        else:
            lines.append("")
            lines.append("（频道扫描：%d 秒没听到任何会话组流量，"
                         "可能现在没人上课，或需要管理员权限）" % seconds)

    # 5) 端口占用
    lines.append("")
    lines.append("关键端口占用：")
    for port, owner in _port_owners([4705, 4806, 5512, 16264]):
        lines.append("  %-7d %s" % (port, owner or "空闲"))

    rec = [n for n in nics if n.get("gateway") and n["gateway"] != "0.0.0.0"] or nics
    if rec:
        lines.append("")
        lines.append("【建议写入 preset.bat】")
        lines.append('  set "TEACHER_IP=%s"' % rec[0]["ip"])
        if found_channel is not None:
            lines.append('  set "TEACHER_CHANNEL=%d"   （来源：%s）' % (found_channel, where))
        else:
            lines.append("  （频道未确定：注册表没读到，可再跑一次带 scan_all=true 的探测）")
    return "\n".join(lines)

def write_default_config():
    with open(CONFIG_PATH, "w", encoding="utf-8-sig") as f:
        f.write(DEFAULT_INI)
    print("已生成配置文件：%s" % CONFIG_PATH)
    print("请用记事本打开它，把 [llm] 里的 api_key 改成你的真实 Key，保存后重新运行。")


def read_config():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding="utf-8-sig")
    return cfg


def _merge_default_ini():
    """启动时把 DEFAULT_INI 里用户缺的配置项自动补进 assistant.ini。

    只补缺失项；已有的项（尤其 api_key）一律不动，注释全保留（ini_merge 负责）。
    这样升级后新功能需要的配置项不用用户手动加，也不会再发生整文件覆盖冲掉 Key。
    """
    try:
        import ini_merge
        dst = ini_merge.read_text(CONFIG_PATH)
        merged = ini_merge.merge_ini(dst, DEFAULT_INI)
        if merged != dst:
            ini_merge.write_text(CONFIG_PATH, merged)
            return True
    except Exception as e:
        try:
            print("[ini] 自动合并跳过：%r" % (e,))
        except Exception:
            pass
    return False


# ---------------------------------------------------------------- API 预设（api.md）
# 根目录 api.md 是人可编辑的模型清单，设置面板与它双向同步：
#   设置里保存 -> 写回当前预设段；手改 api.md -> 设置面板打开时读到最新。
API_MD = os.path.join(ROOT_DIR, "api.md")

DEFAULT_API_MD = u"""[deepseek]
label = DeepSeek（推荐，便宜）
base_url = https://api.deepseek.com/v1
api_key =
model = deepseek-flash

[qwen]
label = 通义千问
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
api_key =
model = qwen-plus
"""


def load_api_presets(path=None):
    """解析 api.md，返回 ([(name, dict), ...], active_name)。
    格式：[预设名] 开头，段内 key = value；# 开头是注释（预留其他模型）。"""
    path = path or API_MD
    presets, order, cur = {}, [], None
    active = ""
    try:
        if not os.path.isfile(path):
            return [], ""
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    if "当前使用" in line:
                        active = line.split("：")[-1].split(":")[-1].strip()
                    continue
                if line.startswith("[") and line.endswith("]"):
                    cur = line[1:-1].strip()
                    if cur:
                        presets[cur] = {"name": cur}
                        order.append(cur)
                    continue
                if "=" in line and cur:
                    k, v = line.split("=", 1)
                    presets[cur][k.strip()] = v.strip()
    except Exception:
        return [], active
    return [(n, presets[n]) for n in order], active


def save_api_presets(presets, active=None, path=None):
    """把预设写回 api.md（人工可读，按固定字段顺序）。"""
    path = path or API_MD
    lines = [u"# 明枢Win7 — 模型接口预设（这个文件可以手改，设置面板会跟着同步）",
             u"# 用法：[预设名] 开头一段，段内写 label / base_url / api_key / model",
             u"# 想预留别的模型，用 # 把整段注释掉即可，随时解开就能用",
             u"# 当前使用：%s" % (active or (presets[0][0] if presets else "")),
             u""]
    for name, data in presets:
        lines.append(u"[%s]" % name)
        for k in ("label", "base_url", "api_key", "model"):
            lines.append(u"%s = %s" % (k, data.get(k, "") or ""))
        lines.append(u"")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(u"\n".join(lines))
        return True
    except Exception:
        return False


def test_endpoint(cfg_like):
    """连通性测试：发一个 max_tokens=1 的最小请求，返回 (ok, 人话)。"""
    base = (cfg_like.get("base_url") or "").rstrip("/")
    key = cfg_like.get("api_key") or ""
    model = cfg_like.get("model") or ""
    if not base:
        return False, "base_url 是空的。"
    if not key:
        return False, "api_key 是空的。"
    t0 = time.time()
    proxy = (cfg_like.get("proxy") or "").strip()
    try:
        payload = {"model": model or "deepseek-flash",
                   "messages": [{"role": "user", "content": "ping"}],
                   "max_tokens": 1, "stream": False}
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        else:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=20) as resp:
            resp.read(200)
        return True, "连通正常，用时 %.1f 秒。" % (time.time() - t0)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        return False, "接口返回 %d：%s%s" % (e.code, body, _http_hint(e.code, body))
    except Exception as e:
        return False, _net_error_text(e)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        write_default_config()
    else:
        _merge_default_ini()
    cfg = read_config()
    key = cfg.get("llm", "api_key", fallback="").strip()
    if (not key) or ("在这里填" in key):
        print("还没有填 API Key。请编辑 %s ，填入真实 Key 后再运行。" % CONFIG_PATH)
        sys.exit(1)
    return cfg


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _fact_text(f):
    """facts 条目兼容两种形态：旧版纯字符串 / 新版 {"text","sid"}。"""
    if isinstance(f, dict):
        return f.get("text", "")
    return f


def _fact_sid(f):
    if isinstance(f, dict):
        return f.get("sid") or ""
    return ""


class Memory(object):
    """滚动对话历史 + 长期事实记忆。"""

    def __init__(self, max_history=20, memory_path=None, facts_path=None):
        self.max_history = max_history
        self.memory_path = memory_path or MEMORY_PATH
        self.facts_path = facts_path or FACTS_PATH
        self.history = load_json(self.memory_path, [])
        self.facts = load_json(self.facts_path, [])
        self.mem_cfg = {"enabled": True, "auto": True, "max_inject": 20, "max_keep": 200}
        # 会话标记：GUI 每个会话一个 memory_path（sessions/<sid>.json），
        # 从文件名反推 sid，remember 时把事实打上来源会话——
        # 删除会话时就能把它学到的那些记忆一起带走（用户要求）。
        self.sid = os.path.splitext(os.path.basename(self.memory_path))[0]

    def apply_config(self, cfg):
        """从 ini 读记忆设置。agent_run 每轮任务开始前调用一次，
        保证开关/条数改动当轮就生效，不需要重启。"""
        # fallback 必须和 DEFAULT_INI 保持一致，否则新装的和升级的用户行为不同
        self.mem_cfg["enabled"] = cfg.getboolean("memory", "enabled", fallback=True)
        self.mem_cfg["auto"] = cfg.getboolean("memory", "auto", fallback=True)
        self.mem_cfg["max_inject"] = max(1, cfg.getint("memory", "max_inject", fallback=20))
        # 地板只放到 1：设多少就认多少。之前这里写 max(10, ...)，
        # 用户在设置里填 5 会被静默改成 10，等于配置项说谎。
        self.mem_cfg["max_keep"] = max(1, cfg.getint("memory", "max_keep", fallback=200))
        # 超量的旧记忆淘汰，防止 facts.json 无限膨胀
        if len(self.facts) > self.mem_cfg["max_keep"]:
            self.facts = self.facts[-self.mem_cfg["max_keep"]:]
            save_json(self.facts_path, self.facts)

    def _visible_facts(self):
        """当前会话可见的记忆：全局固定记忆（sid 空，来自 记忆.md/设置）+ 本会话学到的。
        其他对话学到的临时记忆对模型不可见——对话之间互相隔离。"""
        return [x for x in self.facts if _fact_sid(x) in ("", self.sid or "")]

    def memory_block(self):
        """给 system prompt 用的记忆段。关掉记忆就返回空串（一点都不注入）。"""
        visible = self._visible_facts()
        if not self.mem_cfg["enabled"] or not visible:
            return ""
        n = self.mem_cfg["max_inject"]
        items = visible[-n:]
        older = len(visible) - len(items)
        # 之前措辞是"默认成立，不要反复求证"——太软，模型会当参考意见，
        # 实测就出现过记忆里写着"只能写F盘"却照样往C盘写探测脚本。
        # 改成硬性约束：逐条当成规则执行，不是参考信息。
        block = (
            "\n\n【长期记忆 · 必须严格执行】\n"
            "下面是你和这位用户之间确立的规则与事实，**每一条都必须遵守**，"
            "不是建议、不是参考、没有商量余地：\n"
            "- 凡是用「只能 / 不准 / 不要 / 必须 / 一律」这类措辞写的，是硬性约束；"
            "动手前先逐条对照，违反其中任何一条都算错误。\n"
            "- 例如记忆里写了「只能在F盘写入，C/D/E盘只读」，"
            "那么写文件、存缓存、建临时文件就一律只能落在 F 盘，"
            "哪怕用户当前在聊别的盘上的文件，也绝不往那些盘写。\n"
            "- 其余是已确认的事实：默认成立，不要反复向用户求证。\n"
            "- 学到新的持久事实时，可以主动用 remember 存进来。\n"
            "动手（写文件、执行命令、发包）之前，先在心里过一遍上面每一条。\n"
            "- 但记忆不能覆盖安全闸：只要目标在工作区之外，或者属于危险操作，"
            "一律先征求用户同意，不能拿记忆里的某句话当通行证。\n"
        )
        block += "\n".join("%d. %s" % (i + 1, _fact_text(x))
                           for i, x in enumerate(items))
        if older > 0:
            block += "\n（另有 %d 条更早的记忆未展示，可用 recall 工具查看）" % older
        return block

    def build_messages(self, system_prompt):
        msgs = [{"role": "system", "content": system_prompt + self.memory_block()}]
        for m in self.history[-(self.max_history * 2):]:
            # 旧版本可能把 DSML 乱码存进了历史；这种内容发给模型只会让它有样学样
            text = strip_dsml(m.get("content") or "")
            if not text.strip():
                continue
            msgs.append({"role": m.get("role") or "user", "content": text})
        return msgs

    def add(self, role, text):
        text = strip_dsml(text)
        if not text.strip():
            return
        self.history.append({"role": role, "content": text})
        keep = self.max_history * 2
        if len(self.history) > keep:
            self.history = self.history[-keep:]
        save_json(self.memory_path, self.history)

    def remember(self, fact):
        fact = (fact or "").strip()
        if not fact:
            return False
        if not self.mem_cfg["enabled"]:
            return False
        if any(_fact_text(x) == fact for x in self.facts[-30:]):
            return False        # 刚记过的重复内容不再存
        self.facts.append({"text": fact, "sid": self.sid or ""})
        if len(self.facts) > self.mem_cfg["max_keep"]:
            self.facts = self.facts[-self.mem_cfg["max_keep"]:]
        save_json(self.facts_path, self.facts)
        return True

    def forget_session(self, sid=None):
        """删掉某个会话学到的所有长期记忆（删除对话时调用）。
        sid 缺省删当前 Memory 自己来源会话的；旧版无标记的全局记忆保留。"""
        sid = sid or self.sid
        kept = [x for x in self.facts if _fact_sid(x) != sid]
        removed = len(self.facts) - len(kept)
        if removed:
            self.facts = kept
            save_json(self.facts_path, self.facts)
            self.save_md()
        return removed

    def forget_all(self):
        """清空长期记忆（设置面板的按钮用）。"""
        self.facts = []
        save_json(self.facts_path, self.facts)
        self.save_md()

    def purge_orphan_facts(self, valid_sids):
        """回收孤儿记忆：删掉 sid 不在 valid_sids 里的会话记忆。
        会话被删后残留的临时记忆靠这里兜底清掉（含历史版本删会话没清干净的）；
        sid 为空的是全局固定记忆（记忆.md），永远保留。"""
        valid = set(valid_sids or [])
        kept = [x for x in self.facts if _fact_sid(x) == "" or _fact_sid(x) in valid]
        removed = len(self.facts) - len(kept)
        if removed:
            self.facts = kept
            save_json(self.facts_path, self.facts)
            self.save_md()
        return removed

    # ---- 本地 md 记忆文档 ----

    def load_md(self):
        """从 记忆.md 读回事实。文件不存在就以当前 facts 为准并创建它。

        这样外部用记事本改过的记忆，下次启动能自动同步回来。
        """
        if not os.path.isfile(MEMORY_MD):
            self.save_md()
            return False
        try:
            with open(MEMORY_MD, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return False
        items = self.parse_md(text)
        if items:
            # md 是文本，不带来源会话；同名事实沿用 facts.json 里已有的标记，
            # 没有的当全局记忆（sid 空），保证删会话清理语义不丢
            sidmap = {}
            for x in self.facts:
                t = _fact_text(x)
                if t and t not in sidmap:
                    sidmap[t] = _fact_sid(x)
            self.facts = [{"text": t, "sid": sidmap.get(t, "")} for t in items]
            save_json(self.facts_path, self.facts)
        return True

    @staticmethod
    def parse_md(text):
        """把 md 文本解析成事实列表。

        兼容三种写法：`1. xxx`（编号，推荐）、`- xxx`（列表）、纯文本行。
        空行和以 # 开头的说明行跳过。
        """
        out = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            else:
                # 去掉 1. / 1、 / 1) 这类编号前缀
                m = re.match(r"^\d+\s*[.、)）]\s*(.+)$", line)
                if m:
                    line = m.group(1).strip()
            if line:
                out.append(line)
        return out

    def to_md(self):
        """把当前事实渲染成 md 文档：1. 2. 3. 编号，直观好改。

        空态提示也用 # 开头——之前写成普通文字，用户在空模板下写记忆时，
        占位行会被 parse_md 当成一条真实记忆存进去（实际发生过）。
        """
        head = ("# 长期记忆\n\n"
                "# 一条一行（1. 2. 3. 编号）。改完保存，下次启动自动生效，\n"
                "# 或点设置里的「保存记忆」。以 # 开头的行是说明，不会被记住。\n\n")
        if not self.facts:
            return head + "# （还没记过任何东西。可以手写，或对它说「记住：xxx」）\n"
        return head + "\n".join("%d. %s" % (i + 1, _fact_text(x))
                                for i, x in enumerate(self.facts)) + "\n"

    def save_md(self):
        try:
            with open(MEMORY_MD, "w", encoding="utf-8") as f:
                f.write(self.to_md())
            return True
        except Exception:
            return False

    def set_facts_from_text(self, text):
        """设置面板编辑框点保存时用：把文本框内容整体替换掉现有记忆。
        编辑框里只有文字没有来源标记——同名事实沿用原有 sid（手写新行=全局）。"""
        items = self.parse_md(text)[:self.mem_cfg.get("max_keep", 200)]
        sidmap = {}
        for x in self.facts:
            t = _fact_text(x)
            if t and t not in sidmap:
                sidmap[t] = _fact_sid(x)
        self.facts = [{"text": t, "sid": sidmap.get(t, "")} for t in items]
        save_json(self.facts_path, self.facts)
        self.save_md()
        return len(self.facts)


# ------------------------------------------------------------ 模型调用

_RETRY_CODES = (429, 500, 502, 503, 504)


# ------------------------------------------------ HTTP 连接复用（keep-alive）
#
# urllib 每次请求都重新握手 TCP + TLS，光握手就上百毫秒，一问一答能明显感到"转圈"。
# 这里按 (协议, 主机, 端口) 缓存 http.client 连接复用。只在直连（没配代理）时启用，
# 出任何岔子都退回 urllib，功能不受影响。

_CONNS = {}
_CONN_LOCK = threading.Lock()
_HTTP_STATS = {"new": 0, "reused": 0, "fallback": 0}


class _HTTPErr(Exception):
    """统一 HTTP 错误：自维护连接和 urllib 都抛这个，重试逻辑只写一份。"""

    def __init__(self, code, body="", reason=""):
        Exception.__init__(self, "HTTP %d" % code)
        self.code = code
        self.body = body or ""
        self.reason = reason or ""


def _conn_key(base):
    u = urllib.parse.urlparse(base)
    scheme = (u.scheme or "http").lower()
    host = u.hostname or ""
    port = u.port or (443 if scheme == "https" else 80)
    return scheme, host, port


def _conn_new(scheme, host, port, timeout):
    if scheme == "https":
        import ssl
        try:
            ctx = ssl.create_default_context()
            # 显式要求 TLS 1.2+：老 Win7 机器 / 老 OpenSSL 组合下，
            # 不写这行会在握手阶段直接失败，而且报错完全看不出原因。
            try:
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            except Exception:
                pass
        except Exception:
            ctx = None
        return http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _conn_take(base):
    try:
        with _CONN_LOCK:
            return _CONNS.pop(_conn_key(base), None)
    except Exception:
        return None


def _conn_give(base, conn):
    try:
        with _CONN_LOCK:
            _CONNS[_conn_key(base)] = conn
    except Exception:
        _conn_drop(conn)


def _conn_drop(conn):
    try:
        conn.close()
    except Exception:
        pass


def _conn_request(base, method, path, body, headers, timeout):
    """用缓存连接发一次请求，返回 (code, text)。失败抛 _HTTPErr / OSError。"""
    conn = _conn_take(base)
    for attempt in (0, 1):
        if conn is None:
            conn = _conn_new(*(_conn_key(base) + (timeout,)))
            _HTTP_STATS["new"] += 1
        else:
            _HTTP_STATS["reused"] += 1
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            code = int(resp.status)
            txt = ""
            try:
                txt = resp.read().decode("utf-8", "replace")
            except Exception:
                pass
            if code >= 400:
                # 5xx / 429 是临时的，连接可能还活着，还回去下次接着用
                _conn_give(base, conn) if code in _RETRY_CODES else _conn_drop(conn)
                raise _HTTPErr(code, txt)
            _conn_give(base, conn)
            return code, txt
        except _HTTPErr:
            raise
        except Exception:
            _conn_drop(conn)
            conn = None
            if attempt == 1:
                raise
    raise OSError("keep-alive request failed")


def _conn_stream_lines(base, path, body, headers, timeout):
    """keep-alive 的 SSE：一行行产出 bytes；结束/出错后把连接还回池子。"""
    conn = _conn_take(base)
    if conn is None:
        conn = _conn_new(*(_conn_key(base) + (timeout,)))
        _HTTP_STATS["new"] += 1
    else:
        _HTTP_STATS["reused"] += 1
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        if int(resp.status) >= 400:
            txt = ""
            try:
                txt = resp.read(4000).decode("utf-8", "replace")
            except Exception:
                pass
            code = int(resp.status)
            _conn_give(base, conn) if code in _RETRY_CODES else _conn_drop(conn)
            raise _HTTPErr(code, txt)
    except _HTTPErr:
        raise
    except Exception:
        _conn_drop(conn)
        raise
    try:
        for raw in resp:
            yield raw
        try:
            resp.read()          # 尾巴读完连接才能继续复用
        except Exception:
            pass
        _conn_give(base, conn)
    except GeneratorExit:
        _conn_drop(conn)
        raise
    except Exception:
        _conn_drop(conn)


# ------------------------------------------------ 线路测速（自动选最快的一条）
#
# 官方站 / 国内镜像 / 中转站延迟能差好几倍。配了 mirrors 就并发各发一个
# GET /models（不烧 token），选最快那条，结果缓存 30 分钟。

BASE_SPEED_CACHE = os.path.join(LOGS_DIR, "base_speed.json")
BASE_TTL = 30 * 60


def _probe_one(base, key, timeout):
    """测单个线路的端到端耗时（毫秒）。返回 (ms, err)。"""
    headers = {"Authorization": "Bearer " + key, "Connection": "keep-alive"}
    t0 = time.time()
    try:
        code, _txt = _conn_request(base, "GET", "/models", None, headers, timeout)
        if code >= 400:
            return None, "HTTP %d" % code
        return int((time.time() - t0) * 1000), ""
    except Exception as e:
        return None, str(e)[:80]


def probe_bases(cfg, timeout=5):
    """并发测所有候选线路，返回 [(url, ms或None, err)]，快的排前面。"""
    key = cfg.get("llm", "api_key", fallback="").strip()
    main = cfg.get("llm", "base_url", fallback="").strip().rstrip("/")
    mirrors = [x.strip().rstrip("/") for x in
               (cfg.get("llm", "mirrors", fallback="") or "").split(",") if x.strip()]
    cands = []
    for u in [main] + mirrors:
        if u and u not in cands:
            cands.append(u)
    out = [None] * len(cands)

    def go(i, u):
        try:
            ms, err = _probe_one(u, key, timeout)
            out[i] = (u, ms, err)
        except Exception as e:
            out[i] = (u, None, str(e)[:80])

    ths = [threading.Thread(target=go, args=(i, u), daemon=True)
           for i, u in enumerate(cands)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout + 2)
    res = [x for x in out if x]
    return sorted([x for x in res if x[1] is not None], key=lambda x: x[1]) \
        + [x for x in res if x[1] is None]


def pick_base(cfg, force=False):
    """选最快的线路。没配 mirrors 就直接用主线路（不做任何额外请求）。"""
    main = cfg.get("llm", "base_url", fallback="").strip().rstrip("/")
    mirrors = [x.strip().rstrip("/") for x in
               (cfg.get("llm", "mirrors", fallback="") or "").split(",") if x.strip()]
    auto = cfg.getboolean("llm", "auto_pick_fastest", fallback=True)
    if not main:
        return main, []
    if not mirrors or not auto:
        return main, []
    cache = load_json(BASE_SPEED_CACHE, {}) or {}
    if not force and cache.get("best") \
            and (time.time() - float(cache.get("ts") or 0)) < BASE_TTL:
        return cache.get("best") or main, cache.get("results") or []
    res = probe_bases(cfg)
    best = res[0][0] if res and res[0][1] is not None else main
    try:
        if not os.path.isdir(LOGS_DIR):
            os.makedirs(LOGS_DIR)
        save_json(BASE_SPEED_CACHE, {"ts": time.time(), "best": best,
                                     "results": [[u, ms, e] for u, ms, e in res]})
    except Exception:
        pass
    return best, res


class UserStop(Exception):
    """用户在流式生成中途按了停止——chat_raw 抛出，agent_run 捕获后优雅收尾。"""


def _parse_sse(lines, on_delta, sent, stop_event=None):
    """读 SSE 流式响应，拼装出 assistant 消息 dict；usage 写进 LAST_USAGE。

    reasoning_content -> on_delta("reason", ...)，content -> on_delta("content", ...)。
    sent[0] 收到过任何增量就置 True（调用方据此决定还能不能安全重试）。
    stop_event 置位时立即抛 UserStop——否则长回答中途按停止要等整段生成完才生效。
    """
    content_parts, reason_parts = [], []
    calls = {}                                # index -> {"id","name","args"}
    finish = None
    if True:
        for raw in lines:
            if stop_event is not None and stop_event.is_set():
                raise UserStop()
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except Exception:
                continue
            usage = chunk.get("usage")
            if usage:
                try:
                    u = dict(usage)
                    det = usage.get("completion_tokens_details") or {}
                    u["reasoning_tokens"] = int(det.get("reasoning_tokens") or 0)
                    LAST_USAGE.clear()
                    LAST_USAGE.update(u)
                except Exception:
                    pass
            choices = chunk.get("choices") or []
            if not choices:
                continue
            ch = choices[0]
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
            delta = ch.get("delta") or {}
            rc = delta.get("reasoning_content")
            if rc:
                sent[0] = True
                reason_parts.append(rc)
                try:
                    on_delta("reason", rc)
                except Exception:
                    pass
            ct = delta.get("content")
            if ct:
                sent[0] = True
                content_parts.append(ct)
                try:
                    on_delta("content", ct)
                except Exception:
                    pass
            for tc in delta.get("tool_calls") or []:
                sent[0] = True
                try:
                    idx = int(tc.get("index") or 0)
                except Exception:
                    idx = 0
                slot = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
    LAST_FINISH["reason"] = finish
    msg = {"role": "assistant", "content": "".join(content_parts)}
    if reason_parts:
        msg["reasoning_content"] = "".join(reason_parts)
    if calls:
        msg["tool_calls"] = [{"id": s["id"] or ("call_%d" % i), "type": "function",
                              "function": {"name": s["name"], "arguments": s["args"]}}
                             for i, s in sorted(calls.items())]
    return msg


def _http_hint(code, detail):
    low = (detail or "").lower()
    if code in (400, 404, 422) and "model" in low:
        return ("（模型名可能已失效：旧名 deepseek-chat / deepseek-reasoner 已于 2026-07-24 "
                "弃用，请到「设置」改成 deepseek-flash 或 deepseek-v4-pro）")
    if code == 401:
        return "（API Key 无效或已过期，请到「设置」重新填写）"
    if code == 402:
        return "（账户余额不足）"
    if code == 429:
        return "（请求太频繁，等几秒再试）"
    return ""


def _net_error_text(e):
    """把 TLS/网络异常翻译成人话 + 下一步建议。
    静默失败和 0x80070005 式的天书，是这类产品最大的信任杀手。"""
    txt = str(e) or repr(e)
    low = txt.lower()
    try:
        import ssl as _ssl
    except Exception:
        _ssl = None
    cert_err = getattr(_ssl, "SSLCertVerificationError", None) if _ssl else None
    ssl_err = getattr(_ssl, "SSLError", None) if _ssl else None
    if ("certificate verify failed" in low or "certverify" in low
            or "self signed" in low or "unable to get local issuer" in low
            or (cert_err and isinstance(e, cert_err))):
        return ("证书校验失败：目标站点的证书链在本机验不过。\n"
                "  1) 先看系统时间是否准确（差几分钟就会失败）：右下角时间 -> 同步；\n"
                "  2) Win7 的受信任根证书列表停更了，装一次「根证书更新」(KB931125)；\n"
                "  3) 内网自签证书可把该 CA 导入「受信任的根证书颁发机构」。")
    if (ssl_err and isinstance(e, ssl_err)) or "ssl" in low or "tls" in low:
        return ("TLS 握手失败：服务器要求 TLS 1.2 以上，而本机没能协商成功。\n"
                "  1) 本程序已显式要求 TLS 1.2，通常是系统根证书太旧或时间不准；\n"
                "  2) 老 Win7 需要打补丁启用 TLS 1.2（KB3140245），或改用别的线路；\n"
                "  3) 走代理时确认代理支持 HTTPS CONNECT。")
    if "timed out" in low or "timeout" in low:
        return "连接超时：网络慢或被墙/被防火墙拦。可换线路（设置里填 mirrors）或稍后重试。"
    if "connection reset" in low or "10054" in low or "eof occurred" in low:
        return ("连接被对方重置：多半是代理/防火墙/杀软拦截，或接口线路临时抽风。\n"
                "  换个线路或关掉代理再试；开了杀软的把本程序加入白名单。")
    if "getaddrinfo" in low or "name or service not known" in low:
        return "域名解析失败：检查网络连接、DNS 设置，或 base_url 是否写错。"
    return "网络错误：%s" % txt


def _chat_raw_impl(cfg, messages, tools=None, on_delta=None, stop_event=None):
    """调用任意 OpenAI 兼容 /chat/completions，返回 assistant 消息 dict。

    on_delta 不为空时走 SSE 流式，边收边吐字（界面即时显示）。
    stop_event 置位时流式中途立刻抛 UserStop（用户点「打断」立即生效）。
    网络抖动/429/5xx 自动重试 2 次（间隔 1.5s、3s）；流式一旦吐过字就不再重试，
    避免界面出现重复内容。个别网关不认识 stream_options 时自动降级重发。
    """
    base, _res = pick_base(cfg)
    key = cfg.get("llm", "api_key", fallback="").strip()
    model = cfg.get("llm", "model", fallback="").strip()
    if not base:
        raise RuntimeError("assistant.ini 里没有配 base_url")
    payload = {"model": model, "messages": messages, "temperature": 0.3}
    mt = cfg.getint("llm", "max_tokens", fallback=0)
    if mt > 0:
        payload["max_tokens"] = mt
    # 思考档位：DeepSeek V4 系列默认开启思考（且默认 high），同一个问题的 token
    # 能差几倍到几十倍。off 用 thinking 开关关掉，low/high/max 用 reasoning_effort。
    effort = cfg.get("llm", "thinking", fallback="").strip().lower()
    if effort in ("off", "false", "0", "no", "none"):
        payload["thinking"] = {"type": "disabled"}
    elif effort in ("low", "high", "max"):
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if on_delta:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    proxy = cfg.get("llm", "proxy", fallback="").strip()
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener()
    # 配了代理就没法复用直连连接，退回 urllib
    use_ka = (not proxy) and cfg.getboolean("llm", "keepalive", fallback=True)

    def _headers():
        return {"Content-Type": "application/json", "Authorization": "Bearer " + key,
                "Accept": "text/event-stream" if on_delta else "application/json",
                "Connection": "keep-alive"}

    def _body():
        return json.dumps(payload).encode("utf-8")

    attempt = 0
    sent = [False]                    # 本次响应是否已经向界面吐过字
    while True:
        try:
            if use_ka:
                try:
                    if on_delta:
                        return _parse_sse(
                            _conn_stream_lines(base, "/chat/completions", _body(),
                                               _headers(), 120), on_delta, sent,
                            stop_event)
                    _code, txt = _conn_request(base, "POST", "/chat/completions",
                                               _body(), _headers(), 120)
                    data = json.loads(txt)
                    break
                except _HTTPErr:
                    raise
                except Exception:
                    # keep-alive 这条路出岔子：还没吐字就退回 urllib 再来一次
                    if sent[0]:
                        raise
                    _HTTP_STATS["fallback"] += 1
                    use_ka = False
                    continue
            req = urllib.request.Request(
                base + "/chat/completions", data=_body(), headers=_headers(), method="POST")
            if on_delta:
                with opener.open(req, timeout=120) as resp:
                    return _parse_sse(resp, on_delta, sent, stop_event)
            with opener.open(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if e.code == 400 and "stream_options" in payload \
                    and "stream_option" in detail.lower():
                # 个别 OpenAI 兼容网关不认识 stream_options，去掉再发一次
                payload.pop("stream_options", None)
                continue
            if e.code in _RETRY_CODES and attempt < 2 and not sent[0]:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError("接口返回 %d：%s%s"
                               % (e.code, detail or e.reason, _http_hint(e.code, detail)))
        except _HTTPErr as e:
            detail = e.body[:300]
            if e.code == 400 and "stream_options" in payload \
                    and "stream_option" in detail.lower():
                payload.pop("stream_options", None)
                continue
            if e.code in _RETRY_CODES and attempt < 2 and not sent[0]:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError("接口返回 %d：%s%s"
                               % (e.code, detail, _http_hint(e.code, detail)))
        except OSError as e:
            # URLError / socket.timeout / TLS 握手失败 / 连接被重置都在这里
            if attempt < 2 and not sent[0]:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError("网络请求失败（已重试）：\n%s" % _net_error_text(e))
    try:
        usage = dict(data.get("usage") or {})
        det = usage.get("completion_tokens_details") or {}
        usage["reasoning_tokens"] = int(det.get("reasoning_tokens") or 0)
        LAST_USAGE.clear()
        LAST_USAGE.update(usage)
        LAST_FINISH["reason"] = data["choices"][0].get("finish_reason")
    except Exception:
        pass
    return data["choices"][0]["message"]




# ------------------------------------------------------------ 工具实现

TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出某个目录下的文件和子目录（含大小、修改时间），用来了解用户电脑里有什么",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径，如 C:\\Users\\用户名\\Desktop 或 ~ 表示用户主目录"}}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文件内容（超长自动截断）。支持文本/代码；"
                       "docx/pptx/xlsx 精确提取文字，doc/xls 启发式提取",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_chars": {"type": "integer", "description": "最多读取的字符数，默认 8000"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "按文件名通配符搜索文件，如 *.docx、*报表*、*.txt",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "文件名通配符，如 *.pdf"},
            "path": {"type": "string", "description": "从哪个目录开始找，默认用户主目录"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "grep_files",
        "description": "在目录内的文本文件里搜索关键字，返回所在文件和行号",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "要搜索的关键字"},
            "path": {"type": "string", "description": "从哪个目录开始找，默认用户主目录"},
            "ext": {"type": "string", "description": "只搜这些扩展名，如 .txt,.md,.py"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "run_cmd",
        "description": "在 Windows 上执行一条 cmd 命令（会先请求用户批准）",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令，如 dir C:\\ 或 tasklist"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "把内容写入一个文件（会先请求用户批准），可用于整理清单、写报告",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "open_path",
        "description": "用系统默认程序打开一个文件或文件夹（会先请求用户批准）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件或文件夹路径"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "sys_info",
        "description": "查看系统信息：Windows 版本、内存、C 盘空间、CPU",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "net_list",
        "description": "列出本机的 TCP/UDP 连接和监听端口（含本地/远端地址、状态、进程 ID 与进程名），"
                       "用来分析本机开了哪些端口、哪个程序在连外面",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "description": "all/listen/est，默认 all；listen 只看监听，est 只看已建立连接"}}}}},
    {"type": "function", "function": {
        "name": "net_scan",
        "description": "扫描一台主机的开放端口（会先请求用户批准）。可扫本机 127.0.0.1，也可扫局域网/IP 地址",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "目标主机，如 127.0.0.1 或 192.168.1.1"},
            "ports": {"type": "string", "description": "端口，支持 80、1-1024、80,443,3389 三种写法，默认常用端口"},
            "timeout": {"type": "number", "description": "单端口超时秒数，默认 0.4"}}, "required": ["host"]}}},
    {"type": "function", "function": {
        "name": "net_sniff",
        "description": "抓一段时间的数据包并按协议/地址/端口汇总（会先请求用户批准）。"
                       "Windows 上需要管理员权限，否则会返回权限提示。"
                       "会解出 HTTP 的 Host/URI 和 DNS 的查询名，并可把原始包存成 pcap 文件",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "integer", "description": "抓多少秒，默认 5，最长 30"},
            "max_packets": {"type": "integer", "description": "最多抓多少个包，默认 200"},
            "save_pcap": {"type": "string", "description": "把抓到的原始包存成 pcap 文件的路径（可用 Wireshark 打开），如 F:\\cap.pcap；留空则不存"}}}}},
    {"type": "function", "function": {
        "name": "compare",
        "description": "比对两份快照并给出结论，而不是把数据堆给用户。"
                       "可用来：抓包前后对比、两个目录对比、两个文件对比、"
                       "同一台主机两次扫描结果对比。返回「新增 / 消失 / 变化」三类结论",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "description": "ports / dirs / files / text"},
            "left": {"type": "string", "description": "第一份：快照文本、目录路径或文件路径"},
            "right": {"type": "string", "description": "第二份：同上"}}, "required": ["kind", "left", "right"]}}},
    {"type": "function", "function": {
        "name": "proc_list",
        "description": "列出本机进程：PID、名称、内存占用、可执行文件完整路径。可按名称关键字过滤，"
                       "用来查「是谁在跑」「这个可疑程序装在哪」",
        "parameters": {"type": "object", "properties": {
            "filter": {"type": "string", "description": "按名称过滤的关键字，如 chrome、java；留空列全部"}}}}},
    {"type": "function", "function": {
        "name": "reg_query",
        "description": "查询 Windows 注册表：列出某个键下的所有值名、类型和数据（只读，不需要批准）",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "完整键路径，如 HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run 或 HKLM\\SOFTWARE\\Microsoft"},
            "value": {"type": "string", "description": "只看某一个值名；留空则列出该键下全部"}}, "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "schedule_add",
        "description": "添加一个定时任务：到点自动执行一条命令，或自动向你汇报一次状态。"
                       "存在程序目录的 schedule.json，重启后仍然有效（程序开着才会触发）",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "任务名，如「每日巡检」"},
            "when": {"type": "string", "description": "什么时候跑：daily HH:MM 每天 / weekly 1,3,5 HH:MM 周一三五 / interval 分钟数，如 interval 30"},
            "action": {"type": "string", "description": "cmd:要执行的命令，或 ask:想让助手分析汇报的一句话"}}, "required": ["name", "when", "action"]}}},
    {"type": "function", "function": {
        "name": "schedule_list",
        "description": "查看当前所有的定时任务",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "schedule_del",
        "description": "删除一个定时任务",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "要删的任务名"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "detect_preset",
        "description": "自动探测极域教师端模拟器需要的预设值，换台机器不用手填："
                       "读注册表频道、找学生端进程、枚举本机网卡与网关、查关键端口占用。"
                       "scan_all=true 时还会逐个试听 32 个频道的会话组播组，"
                       "直接判断真教师在哪个频道（不需要管理员权限）",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "integer", "description": "每个频道监听几秒，默认 2，最长 10"},
            "scan_all": {"type": "boolean", "description": "要不要逐个试听全部频道组播组，默认 false"}}}}},
    {"type": "function", "function": {
        "name": "audit_log",
        "description": "查看审计日志：每一次工具调用（含只读的）都记了时间、权限层级、"
                       "允许还是拒绝、工具名、参数和原因。可用来回答"
                       "「最近动过什么」「哪些操作被拒最多」「这个任务为什么失败」",
        "parameters": {"type": "object", "properties": {
            "tail": {"type": "integer", "description": "看最近多少条，默认 30"},
            "tool": {"type": "string", "description": "只看某个工具，如 run_cmd"},
            "result": {"type": "string", "description": "allow 或 deny"},
            "since": {"type": "string", "description": "起始时间，如 2026-10-24T01:00"}}}}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "抓取一个网页的正文文字（去掉了 HTML 标签）",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "网页地址"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "app_launch",
        "description": "后台启动一个程序（不卡住对话），stdout/stderr 自动记录到 logs/apprun/ 的日志文件。"
                       "用于诊断带窗口的 GUI 程序跑不起来：启动后用 read_file 读日志看报错，"
                       "用 proc_windows 看窗口有没有真的弹出来",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "启动命令，如 python xxx.py 或 C:\\path\\app.exe"},
            "workdir": {"type": "string", "description": "工作目录，默认用户主目录"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "proc_windows",
        "description": "查一个进程（PID 或名称关键字）有没有可见窗口，列出窗口标题。"
                       "用于判断「程序是起来了还是崩了」（纯数据查询，不截图）",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "PID（纯数字）或进程名关键字，如 1234 或 python"}}, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "proc_kill",
        "description": "结束一个进程（按 PID 或进程名，会先请求用户批准）。用于处理卡死的程序或多余的实例",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "PID（纯数字）或进程名，如 python、notepad.exe"}}, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "restore_file",
        "description": "把某个文件恢复到最近一次修改前的备份（每次 write_file 覆盖已有文件前都会自动备份到 "
                       "logs/backup/）。改坏了代码/配置可以用它回滚",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "要恢复的文件路径"},
            "stamp": {"type": "string", "description": "备份时间戳 YYYYMMDD-HHMMSS；留空取最新一份"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "download_file",
        "description": "多线程分段下载文件（会真正存成本地文件，所以要用户批准）。"
                       "服务器支持断点续传时自动分 4 段并发拉，比单线程快；不支持就退回单线程。"
                       "GitHub 系外网资源会自动测速挑国内加速镜像（慢站自动绕开）",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "要下载的完整网址"},
            "path": {"type": "string", "description": "保存到本地的路径，如 ~\\Downloads\\a.zip"},
            "threads": {"type": "integer", "description": "并发段数，1-8，默认 4"}}, "required": ["url", "path"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "把一条重要信息存入长期记忆，以后每次对话都会带上",
        "parameters": {"type": "object", "properties": {
            "fact": {"type": "string", "description": "要记住的内容"}}, "required": ["fact"]}}},
    {"type": "function", "function": {
        "name": "recall",
        "description": "查看当前长期记忆里都有什么",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "load_skill",
        "description": "加载一个用户自定义技能的完整说明书（SKILL.md）。"
                       "系统提示里的【技能库】只列了名字和触发描述（第一层常驻清单）；"
                       "当用户消息命中某技能的描述、或用户点名要用某个技能（如「用 xx 技能做」——优先级最高）时，"
                       "用本工具把全文拉进来。同一会话已加载过的技能不要重复加载",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "技能名（技能库清单里写的名字，支持目录名/大小写不敏感）"}},
            "required": ["name"]}}},
]


def resolve_path(p):
    p = (p or "").strip() or "~"
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(os.path.expanduser("~"), p)
    return os.path.normpath(p)


def guard_path(p, workspace):
    """workspace 为空则不限制；否则只允许 workspace 内部。"""
    if not workspace:
        return True
    try:
        rp = os.path.realpath(p).lower()
        wr = os.path.realpath(workspace).lower()
        return rp == wr or rp.startswith(wr + os.sep)
    except Exception:
        return False


def _cap(text):
    text = text if isinstance(text, str) else str(text)
    lim = TOOL_LIMIT[0]
    if len(text) <= lim:
        return text
    # 头尾都留：读文档时最关键的往往是开头（标题/开头段）和结尾（结论/结尾段），
    # 旧实现纯头部砍，等于把后半本直接扔掉。
    head = int(lim * 0.6)
    tail = lim - head - 60
    if tail <= 0:
        return text[:lim] + "\n……（内容过长，已截断）"
    return "%s\n……（中间省略 %d 字符，保留头尾）……\n%s" % (
        text[:head], len(text) - head - tail, text[-tail:])


NL = chr(10)              # 统一换行常量（补丁生成时用到的占位符）
_DIR_CACHE = {}          # path -> (ts, text)，3 秒 TTL：模型常连着两轮看同一个目录
_DIR_TTL = 3.0


def tool_list_dir(path):
    p = resolve_path(path)
    if not os.path.isdir(p):
        return "目录不存在：%s" % p
    now = time.time()
    hit = _DIR_CACHE.get(p)
    if hit and (now - hit[0]) < _DIR_TTL:
        return hit[1]
    rows = []
    try:
        # scandir：一次系统调用拿全 name/is_dir/stat，比 os.listdir + 逐个 stat 快 2~5 倍
        with os.scandir(p) as it:
            for e in it:
                try:
                    st = e.stat()
                    is_dir = e.is_dir()
                    size = "<目录>" if is_dir else "%d B" % st.st_size
                    rows.append("%-6s %10s  %s  %s" % (
                        "[目录]" if is_dir else "[文件]",
                        size,
                        time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                        e.name))
                except OSError:
                    continue
    except OSError as e:
        return "打不开这个目录：%s" % e
    if not rows:
        text = "(空目录) %s" % p
    else:
        text = p + NL + NL.join(sorted(rows)[:500])
    if len(_DIR_CACHE) > 80:
        _DIR_CACHE.clear()
    _DIR_CACHE[p] = (now, text)
    return text


def _office_text(p, max_chars):
    """从办公文档提取可读文本，纯标准库：
    docx/pptx/xlsx 是 zip+xml，精确提取；doc/xls 是老二进制格式，启发式扫描。"""
    import zipfile
    ext = os.path.splitext(p)[1].lower()

    def strip_tags(xml, para_tag):
        xml = re.sub(r"</%s>" % para_tag, "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)

    try:
        if ext == ".docx":
            with zipfile.ZipFile(p) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            text = strip_tags(xml, "w:p")
        elif ext == ".pptx":
            parts = []
            with zipfile.ZipFile(p) as z:
                names = sorted((n for n in z.namelist()
                                if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                               key=lambda s: int(re.search(r"(\d+)", s).group(1)))
                for name in names:
                    xml = z.read(name).decode("utf-8", "replace")
                    parts.append(strip_tags(xml, "a:p").strip())
            text = "\n".join("--- 第 %d 页 ---\n%s" % (i + 1, t)
                             for i, t in enumerate(parts) if t)
        elif ext == ".xlsx":
            parts = []
            with zipfile.ZipFile(p) as z:
                shared = []
                if "xl/sharedStrings.xml" in z.namelist():
                    s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                    shared = [strip_tags(m, "si") for m in
                              re.findall(r"<si>.*?</si>", s, re.S)]
                sheet_names = sorted(n for n in z.namelist()
                                     if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
                for name in sheet_names:
                    s = z.read(name).decode("utf-8", "replace")
                    rows = []
                    for row in re.findall(r"<row[^>]*>(.*?)</row>", s, re.S):
                        cells = []
                        for m in re.finditer(r"<c[^>]*?(?: t=\"(\w+)\")?[^>]*>(.*?)</c>",
                                             row, re.S):
                            ttype, body = m.group(1), m.group(2)
                            v = re.search(r"<v>(.*?)</v>", body, re.S)
                            if not v:
                                cells.append(re.sub(r"<[^>]+>", "", body).strip())
                                continue
                            val = v.group(1)
                            if ttype == "s" and val.isdigit():
                                idx = int(val)
                                cells.append(shared[idx] if idx < len(shared) else val)
                            else:
                                cells.append(val)
                        if any(c for c in cells):
                            rows.append(" | ".join(cells))
                    parts.append("\n".join(rows))
            text = "\n".join(p2 for p2 in parts if p2)
        else:
            # .doc / .xls：老二进制（OLE）。正文多为 UTF-16LE 存放，
            # 没有第三方库解不了 OLE 结构，按可读字符段启发式提取
            with open(p, "rb") as f:
                data = f.read()
            buf, out = [], []
            for i in range(0, len(data) - 1, 2):
                ch = data[i] | (data[i + 1] << 8)
                if (0x20 <= ch <= 0x7E) or (0x4E00 <= ch <= 0x9FFF) or ch in (0x3001, 0x3002, 0xFF0C, 0xFF1A):
                    buf.append(chr(ch))
                else:
                    if len(buf) >= 4:
                        out.append("".join(buf))
                    buf = []
            if len(buf) >= 4:
                out.append("".join(buf))
            text = "\n".join(out)
            if len(text) < 30:
                return ("这是老版二进制 Office 文档（%s），启发式提取没读到正文。"
                        "建议先用 Office/WPS 打开另存为 .docx/.xlsx 再让我读。" % ext)
            text = "（启发式提取，可能有少量乱码）\n" + text
        text = re.sub(r"[ \t]+\n", "\n", text).strip()
    except Exception as e:
        return "读取办公文档失败：%s" % e
    if len(text) > int(max_chars):
        text = text[:int(max_chars)] + "\n……（已截断）"
    return text or "（文档里没提取到文字）"


_TEXT_CACHE = {}         # (path, mtime, size) -> text（只缓存 256KB 以内的小文件）
_TEXT_CACHE_MAX = 60
_TEXT_CACHE_LIMIT = 256 * 1024


def read_text_file(path, max_chars=8000):
    """读文本：小文件走缓存，大文件只读到需要的那一段，编码按前缀猜。
    返回 (text, note)。读不了时 text 为 None。"""
    p = path
    try:
        st = os.stat(p)
    except OSError as e:
        return None, "读不到文件：%s" % e
    size = st.st_size
    key = (p, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)), size)
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        text = cached
    else:
        # 按字符数估算字节（中文 UTF-8 3 字节 / GBK 2 字节，取 4 留余量）
        want = int(max_chars) * 4 + 4096
        try:
            with open(p, "rb") as f:
                raw = f.read(min(size, want) if size > want else size)
        except OSError as e:
            return None, "读不到文件：%s" % e
        text, enc = _decode_bytes(raw)
        if size <= _TEXT_CACHE_LIMIT:
            if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
                _TEXT_CACHE.clear()
            _TEXT_CACHE[key] = text
    note = ""
    if len(text) > int(max_chars):
        text = text[:int(max_chars)]
        note = (NL + "……（已截断，文件共 %.1f KB）" % (size / 1024.0))
    return text, note


def tool_read_file(path, max_chars=8000, workspace=""):
    p = resolve_path(path)
    if not os.path.isfile(p):
        return _locate_missing(p, workspace)
    size = os.path.getsize(p)
    if size > 50 * 1024 * 1024:
        return "文件太大（%.1f MB），不支持直接读取。" % (size / 1048576.0)
    ext = os.path.splitext(p)[1].lower()
    if ext in (".docx", ".pptx", ".xlsx", ".doc", ".xls"):
        return "文件：%s" % p + NL + _office_text(p, max_chars)
    text, note = read_text_file(p, max_chars)
    if text is None:
        return note
    return "文件：%s" % p + NL + text + note


def tool_search_files(pattern, path="~", max_depth=3):
    """按名字找文件。默认只下钻 3 层（桌面/文档/下载这类常用位置足够），
    全盘搜索要么把 path 指到具体盘符并显式要更深层，要么等它超时——
    Win7 索引服务默认关闭，全盘 walk 扫几分钟很正常，不能让它默认扫全盘。"""
    base = resolve_path(path)
    if not os.path.isdir(base):
        return "目录不存在：%s" % base
    try:
        depth_limit = int(max_depth) if str(max_depth).strip() else 3
    except Exception:
        depth_limit = 3
    if depth_limit <= 0 or depth_limit > 12:
        depth_limit = 3
    hits, dirs_seen, t0 = [], 0, time.time()
    truncated = ""
    for root, dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= depth_limit:
            dirs[:] = []
        dirs_seen += 1
        for fn in files:
            if fnmatch.fnmatch(fn, pattern):
                hits.append(os.path.join(root, fn))
                if len(hits) >= 100:
                    return ("在 %s 下找到 100 个以上（仅显示前 100 个，"
                            "可以把 path 指到更具体的目录）：" % base) + NL + NL.join(hits)
        if dirs_seen > 5000 or (time.time() - t0) > 20:
            truncated = NL + "……（范围过大或超时，结果可能不完整）"
            break
    if not hits:
        return "在 %s 下（%d 层内）没找到匹配 %s 的文件。%s" % (
            base, depth_limit, pattern, truncated)
    return "在 %s 下（%d 层内）找到 %d 个：%s%s" % (
        base, depth_limit, len(hits), NL + NL.join(hits), truncated)


# 文件被移动后按名字自动定位：搜索时跳过这些系统/垃圾目录（省时间也不误报）
_LOC_SKIP = {"windows", "program files", "program files (x86)",
             "programdata", "$recycle.bin", "system volume information",
             "appdata", "node_modules", "__pycache__", ".git",
             "recovery", "perflogs", "winexclude"}


def _locate_missing(p, workspace="", budget=8.0, extra_roots=None):
    """路径不存在时按文件名在常用位置搜同名文件。

    用户经常移动/重命名文件，与其甩一句「文件不存在」让用户自己翻，
    不如把新位置直接列给模型，它下一轮就能用新路径继续干活。
    workspace 非空时只搜 workspace 内（尊重目录限制，不越界窥探）。
    extra_roots 仅测试注入用。
    """
    fname = os.path.basename(str(p or "").replace("/", "\\").rstrip("\\"))
    if not fname:
        return "文件不存在：%s（not found：这看起来是盘符或目录，不是文件）" % p
    fname_l = fname.lower()
    stem = os.path.splitext(fname_l)[0]
    ext = os.path.splitext(fname_l)[1]

    roots = []
    if workspace and os.path.isdir(workspace):
        roots = [workspace]
    elif extra_roots:
        roots = [r for r in extra_roots if os.path.isdir(r)]
    else:
        home = os.path.expanduser("~")
        for d in ("Desktop", "Documents", "Downloads"):
            q = os.path.join(home, d)
            if os.path.isdir(q):
                roots.append(q)
        parent = os.path.dirname(os.path.abspath(p))
        if os.path.isdir(parent):
            roots.append(parent)
        if os.path.isdir(home):
            roots.append(home)
        for drv in ("C:\\", "D:\\", "E:\\", "F:\\"):
            if os.path.isdir(drv):
                roots.append(drv)

    exact, loose = [], []
    t0 = time.time()
    seen = 0
    for root in roots:
        for cur, dirs, files in os.walk(root):
            if (time.time() - t0) > budget:
                break
            # 跳过系统/垃圾目录；不跟隐藏的 $ 目录
            dirs[:] = [d for d in dirs
                       if d.lower() not in _LOC_SKIP and not d.startswith("$")]
            seen += 1
            if seen > 4000:
                break
            for fn in files:
                low = fn.lower()
                full = os.path.join(cur, fn)
                if low == fname_l:
                    if full not in exact:
                        exact.append(full)
                elif stem and stem in low and (not ext or low.endswith(ext)):
                    if full not in loose:
                        loose.append(full)
            if len(exact) >= 20:
                break
        if len(exact) >= 20 or (time.time() - t0) > budget:
            break

    if exact:
        msg = ("文件不在了：%s" + NL
               + "按名字找到这些同名文件（直接用新路径重试，不要问用户）：" + NL
               + NL.join(exact[:20])) % p
        if loose:
            msg += NL + "名字相近的还有：" + NL + NL.join(loose[:10])
        return msg
    if loose:
        return ("文件不在了：%s" + NL
                + "没找到完全同名的，但这些名字相近：" + NL
                + NL.join(loose[:10]) + NL
                + "都不对的话，可以用 search_files 在指定目录里再找一次。") % p
    return ("文件不在了：%s" + NL
            + "在桌面/文档/下载/上级目录/各盘根下都没找到同名文件。" + NL
            + "建议：让用户确认路径，或用 search_files 指定目录再搜。") % p


def tool_grep_files(keyword, path="~", ext=""):
    base = resolve_path(path)
    if not os.path.isdir(base):
        return "目录不存在：%s" % base
    exts = [x.strip().lower() for x in (ext or "").split(",") if x.strip()]
    kw = keyword.lower()
    t0 = time.time()
    # 先收集候选文件（walk 本身带目录数/超时保护）
    files, dirs_seen = [], 0
    for root, dirs, fns in os.walk(base):
        dirs_seen += 1
        for fn in fns:
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            files.append(os.path.join(root, fn))
            if len(files) >= 20000:
                break
        if dirs_seen > 5000 or len(files) >= 20000 or (time.time() - t0) > 25:
            break
    if not files:
        return "在 %s 下没找到可搜索的文件。" % base

    def _scan(fp):
        """扫一个文件，返回命中行列表。"""
        out = []
        try:
            if os.path.getsize(fp) > 1024 * 1024:
                return out
            txt, _note = read_text_file(fp, 200000)
            if txt is None:
                return out
            for i, line in enumerate(txt.splitlines(), 1):
                    if kw in line.lower():
                        out.append("%s:%d: %s" % (fp, i, line.strip()[:200]))
                        if len(out) >= 50:
                            break
        except OSError:
            pass
        except Exception:
            pass                  # 编码炸了/怪文件跳过，不拖垮整体
        return out

    # 并发扫描：读文件是 I/O 密集，机械盘/网络盘上线程池提升明显。
    # 分批 256 个文件、按批保持结果顺序，凑够 50 处或超时立即收手。
    hits = []
    from concurrent.futures import ThreadPoolExecutor
    workers = min(8, (os.cpu_count() or 2) * 2)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for s in range(0, len(files), 256):
                batch = files[s:s + 256]
                for out in ex.map(_scan, batch):
                    hits.extend(out)
                if len(hits) >= 50 or (time.time() - t0) > 25:
                    break
    except Exception:
        # 极端环境线程池起不来，退回串行
        for fp in files:
            hits.extend(_scan(fp))
            if len(hits) >= 50 or (time.time() - t0) > 25:
                break
    if not hits:
        return "在 %s 下没找到包含「%s」的内容。" % (base, keyword)
    head = hits[:50]
    extra = "\n……（命中超过 50 处，只显示前 50 处）" if len(hits) > 50 else ""
    return "在 %s 下找到 %d 处：\n%s%s" % (base, len(hits), "\n".join(head), extra)


def hidden_kwargs():
    """让子进程不出黑框：CREATE_NO_WINDOW + 启动信息里把窗口藏起来。
    程序是用 pythonw 跑的（没有控制台），shell=True 会顺手开一个 cmd 黑框。"""
    kw = {}
    if os.name != "nt":
        return kw
    kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0          # SW_HIDE
        kw["startupinfo"] = si
    except Exception:
        pass
    return kw


def _decode_stream(data):
    """解码子进程输出。Windows 控制台是 GBK(cp936)，而 text=True 会按
    locale/UTF-8 模式解码，中文提示全变乱码（用户看到乱码就以为命令没跑）。
    改成拿字节自己按  utf-8-sig / utf-8 / gbk / utf-16 依次试。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return _decode_bytes(data)[0]


def tool_run_cmd(command):
    try:
        p = subprocess.run(
            command, shell=True, cwd=os.path.expanduser("~"),
            capture_output=True, timeout=60, **hidden_kwargs()
        )
    except subprocess.TimeoutExpired:
        return "命令执行超时（60 秒），已被终止：%s" % command
    except Exception as e:
        # shell=True 在极端环境（找不到 cmd.exe / 权限被拦）会抛 OSError，
        # 以前这层没有兜底，异常会一路逃到 execute_tool 变成一句"工具执行出错"。
        return "命令没能启动：%s（%s）" % (command, e)
    out = _decode_stream(p.stdout)
    err = _decode_stream(p.stderr)
    if err:
        out += (("\n" if out else "") + "[stderr]\n" + err)
    return "命令：%s\n退出码：%d\n%s" % (command, p.returncode, out.strip() or "(无输出)")


def _backup_file(p):
    """覆盖已有文件前备份到 logs/backup/。返回备份路径；原文件不存在返回空串。"""
    if not os.path.isfile(p):
        return ""
    try:
        if not os.path.isdir(BACKUP_DIR):
            os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.basename(p)
        dst = os.path.join(BACKUP_DIR, "%s.%s.bak" % (base, stamp))
        n = 1
        while os.path.exists(dst):     # 同一秒多次写，加序号防覆盖
            dst = os.path.join(BACKUP_DIR, "%s.%s-%d.bak" % (base, stamp, n))
            n += 1
        shutil.copy2(p, dst)
        return dst
    except Exception:
        return ""                      # 备份失败不挡主流程，但要让人知道


def tool_write_file(path, content):
    p = resolve_path(path)
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    bak = _backup_file(p)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    if bak:
        return "已写入：%s（%d 字符）\n原文件已备份到：%s（改坏了可用 restore_file 回滚）" % (
            p, len(content), bak)
    return "已写入：%s（%d 字符）" % (p, len(content))


def tool_restore_file(path, stamp=""):
    """从 logs/backup/ 恢复某文件的备份。stamp 留空取最新一份。"""
    p = resolve_path(path)
    base = os.path.basename(p)
    if not os.path.isdir(BACKUP_DIR):
        return "还没有任何备份（logs/backup/ 不存在），没东西可恢复。"
    cands = [fn for fn in os.listdir(BACKUP_DIR)
             if fn.endswith(".bak") and (fn == base or fn.startswith(base + "."))]
    if not cands:
        return "没有找到 %s 的备份。" % base
    if stamp:
        match = [fn for fn in cands if stamp in fn]
        if not match:
            return "没有匹配「%s」的备份。可用的备份：\n%s" % (
                stamp, "\n".join(sorted(cands)[-10:]))
        cands = match
    cands.sort()
    src = os.path.join(BACKUP_DIR, cands[-1])
    cur_bak = _backup_file(p)          # 恢复前把当前版本也留一份，防止恢复错
    shutil.copy2(src, p)
    extra = "（恢复前的当前版本也备份了一份：%s）" % cur_bak if cur_bak else ""
    return "已恢复：%s\n来源：%s%s" % (p, src, extra)


# GitHub 系外网资源下载加速：镜像站支持「前缀 + 完整原链接」直链代理。
# 2026-10 实测可用；哪天失效了不用改代码，往 assistant.ini 的 download_mirrors 里换
_DL_MIRRORS_DEFAULT = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://mirror.houlang.cloud/",
    "https://cors.isteed.cc/",
]
_DL_GH_HOSTS = ("github.com", "raw.githubusercontent.com", "gist.githubusercontent.com",
                "objects.githubusercontent.com", "codeload.github.com")


def _pick_download_url(cfg, url):
    """外网直链慢时自动挑最快的下载镜像。返回 (最终url, 是否走了镜像)。

    只对 GitHub 系域名做镜像测速（其他站没有通用镜像）。策略：给每个候选
    （直连 + 各镜像）发一个 64KB 的 Range 试读，2 秒内谁吐的字节多谁赢；
    全都失败就退回直连。
    """
    mode = "auto"
    if cfg is not None:
        try:
            mode = (cfg.get("llm", "mirror_boost", fallback="auto") or "auto").strip().lower()
        except Exception:
            mode = "auto"
    if mode in ("off", "false", "0", "no"):
        return url, False
    try:
        host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    except Exception:
        return url, False
    if not any(host == h or host.endswith("." + h) for h in _DL_GH_HOSTS):
        return url, False
    mirrors = []
    if cfg is not None:
        try:
            raw = cfg.get("llm", "download_mirrors", fallback="") or ""
        except Exception:
            raw = ""
        mirrors = [x.strip() for x in raw.split(",") if x.strip()]
    if not mirrors:
        mirrors = list(_DL_MIRRORS_DEFAULT)
    cands = [url] + [m + url for m in mirrors]
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win7Assistant) Chrome/60.0",
          "Range": "bytes=0-65535"}
    best_url, best_speed = url, -1.0
    for u in cands:
        speed = 0.0
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(u, headers=ua),
                                        timeout=5) as r:
                got = 0
                while got < 65536 and time.time() - t0 < 2.0:
                    b = r.read(16384)
                    if not b:
                        break
                    got += len(b)
            speed = got / max(time.time() - t0, 0.05)
        except Exception:
            speed = 0.0
        if speed > best_speed:
            best_url, best_speed = u, speed
    return best_url, best_url != url


def tool_download_file(url, path, threads=4, cfg=None):
    """多线程分段下载：服务器支持断点续传就分 N 段并发拉（抢带宽），不支持就单线程。

    GitHub 系外网资源会先自动测速挑国内加速镜像（mirror_boost=auto 时），
    真·提速点——单条 TCP 连接往往跑不满你的带宽，多段并发能把剩余带宽吃满。
    """
    final_url, via = _pick_download_url(cfg, url)
    if via:
        url = final_url
    tail = "，经国内镜像加速" if via else ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    p = resolve_path(path)
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception as e:
            return "建目录失败：%s" % e
    try:
        threads = int(threads)
    except Exception:
        threads = 4
    threads = max(1, min(8, threads))
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win7Assistant) Chrome/60.0"}
    total, can_range = 0, False
    try:
        req = urllib.request.Request(url, headers=ua, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            total = int(r.headers.get("Content-Length") or 0)
            can_range = (r.headers.get("Accept-Ranges") or "").lower() == "bytes"
    except Exception:
        total, can_range = 0, False

    t0 = time.time()
    try:
        if not (can_range and total > 512 * 1024 and threads > 1):
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=ua), timeout=120) as r, \
                    open(p, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            got = os.path.getsize(p)
            return "已下载：%s\n大小 %s，用时 %.1f 秒（单线程，服务器不支持分段%s）" % (
                p, _hsize(got), time.time() - t0, tail)
        # 预分配文件，各线程写自己那段
        with open(p, "wb") as f:
            f.truncate(total)
        n = min(threads, 8)
        step = total // n
        spans = []
        for i in range(n):
            a = i * step
            b = total - 1 if i == n - 1 else (a + step - 1)
            spans.append((a, b))
        errs = []
        lock = threading.Lock()

        def pull(a, b):
            fh = open(p, "r+b")
            try:
                fh.seek(a)
                h = dict(ua)
                h["Range"] = "bytes=%d-%d" % (a, b)
                with urllib.request.urlopen(
                        urllib.request.Request(url, headers=h), timeout=120) as r:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
            except Exception as e:
                with lock:
                    errs.append(str(e)[:120])
            finally:
                try:
                    fh.close()
                except Exception:
                    pass

        ths = [threading.Thread(target=pull, args=s, daemon=True) for s in spans]
        for t in ths:
            t.start()
        for t in ths:
            t.join(150)
        got = os.path.getsize(p)
        sec = max(time.time() - t0, 0.1)
        if errs:
            return "下载中断：%s\n已拿到 %s / %s" % (
                "；".join(errs[:2]), _hsize(got), _hsize(total))
        if got != total:
            return "大小对不上（%s / 期望 %s），文件可能不完整：%s" % (
                _hsize(got), _hsize(total), p)
        return "已下载：%s\n大小 %s，用时 %.1f 秒，%.0f KB/s（%d 段并发%s）" % (
            p, _hsize(got), sec, got / 1024.0 / sec, n, tail)
    except Exception as e:
        return "下载失败：%s" % e


def _hsize(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%d%s" % (int(n), unit)
        n /= 1024.0
    return "%.1fGB" % n


def tool_app_launch(command, workdir=""):
    """后台启动一个程序，stdout/stderr 落盘到 logs/apprun/。
    专为诊断带窗口的 GUI 程序设计：崩溃 traceback 会进日志文件，
    不会像 run_cmd 那样等 GUI 程序退出等到超时。"""
    cmd = (command or "").strip()
    if not cmd:
        return "没给启动命令。"
    if not os.path.isdir(APPRUN_DIR):
        os.makedirs(APPRUN_DIR, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9\-_]+", "_", os.path.basename(cmd.split()[0]))[:24] or "app"
    log_path = os.path.join(APPRUN_DIR, "%s_%s.log" % (
        tag, time.strftime("%Y%m%d-%H%M%S")))
    kw = {}
    if os.name == "nt":
        # 只藏 shell 自身的控制台；GUI 程序自己的窗口照常弹出
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        lf = open(log_path, "ab")
        proc = subprocess.Popen(cmd, shell=True,
                                cwd=workdir or os.path.expanduser("~"),
                                stdout=lf, stderr=subprocess.STDOUT, **kw)
    except Exception as e:
        return "启动失败：%s（%s）" % (cmd, e)
    time.sleep(0.5)                    # 稍等半秒，import 秒崩立刻能从日志看出
    alive = proc.poll() is None
    err_head = ""
    try:
        if os.path.getsize(log_path) > 0:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                err_head = f.read(2000)
    except Exception:
        pass
    lines = ["已在后台启动：%s" % cmd,
             "shell PID：%d（真实子进程的 PID 用 proc_list 按名称查）" % proc.pid,
             "输出/报错日志：%s" % log_path,
             "状态：%s" % ("运行中" if alive else "已退出（退出码 %s）" % proc.poll())]
    if err_head:
        lines.append("日志前段：\n" + err_head)
    lines.append("下一步：等几秒用 read_file 读上面的日志文件看完整报错；"
                 "用 proc_windows 查真实进程有没有弹出可见窗口。")
    return "\n".join(lines)


def tool_proc_windows(target):
    """查一个进程（PID 或名称关键字）有没有可见窗口，列窗口标题。
    纯数据面查询（EnumWindows），不截图、不看屏幕内容。"""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return "这个工具只在 Windows 上可用。"
    target = str(target or "").strip()
    if not target:
        return "没给要查的 PID 或进程名。"
    # tasklist 建 PID -> 进程名 映射（顺带确认进程是否还活着）
    pid_names = {}
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=20, **hidden_kwargs()).stdout
        for line in _decode_stream(out).splitlines():
            parts = [x.strip().strip('"') for x in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pid_names[int(parts[1])] = parts[0]
    except Exception:
        pass
    if str(target).isdigit():
        wanted = {int(target)}
        alive = int(target) in pid_names
    else:
        kw_l = target.lower()
        wanted = set(pid for pid, nm in pid_names.items() if kw_l in nm.lower())
        alive = bool(wanted)
    if not alive:
        return ("没找到存活的进程：%s（可能已经退出了；用 proc_list 确认，"
                "或用 app_launch 的日志看崩溃原因）" % target)
    # EnumWindows：只取可见 + 有标题的顶层窗口
    user32 = ctypes.windll.user32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    # 64 位下句柄/指针必须声明 argtypes，否则会被截断出各种怪问题
    user32.EnumWindows.argtypes = [WNDPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    wins = []

    def _cb(hwnd, _lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in wanted and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value.strip()
                if title:
                    wins.append("%s  (pid %d)" % (title, pid.value))
        return True

    try:
        user32.EnumWindows(WNDPROC(_cb), 0)
    except Exception as e:
        return "枚举窗口失败：%s" % e
    names = sorted(set(pid_names.get(p, "?") for p in wanted))
    if wins:
        return "进程 %s 存活，有 %d 个可见窗口：\n%s" % (
            "/".join(names), len(wins), "\n".join(wins[:20]))
    return ("进程 %s 存活，但目前没有任何可见窗口——"
            "可能还在启动、窗口创建失败（看 app_launch 的日志）或本身是控制台程序。"
            % "/".join(names))


def tool_proc_kill(target):
    """结束一个进程（taskkill）。target 是 PID 或进程名。"""
    t = str(target or "").strip()
    if not t:
        return "没给要结束的 PID 或进程名。"
    if t.isdigit():
        cmd = ["taskkill", "/F", "/PID", t]
    else:
        name = t if t.lower().endswith(".exe") else t + ".exe"
        cmd = ["taskkill", "/F", "/IM", name]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=20, **hidden_kwargs())
    except Exception as e:
        return "taskkill 没能执行：%s" % e
    out = _decode_stream(p.stdout)
    err = _decode_stream(p.stderr)
    return "taskkill 退出码 %d\n%s%s" % (p.returncode, out, ("\n" + err) if err else "")


def tool_open_path(path):
    p = resolve_path(path)
    if not os.path.exists(p):
        return "路径不存在：%s" % p
    os.startfile(p)
    return "已打开：%s" % p


def tool_sys_info():
    lines = [
        "操作系统 : %s" % platform.platform(),
        "Python   : %s" % sys.version.split()[0],
        "CPU 核心 : %d" % (os.cpu_count() or 0),
    ]
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            lines.append("内存     : 共 %.1f GB，可用 %.1f GB（占用 %d%%）" % (
                st.ullTotalPhys / 2 ** 30, st.ullAvailPhys / 2 ** 30, st.dwMemoryLoad))
        free, total = ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p("C:\\"), None, ctypes.byref(total), ctypes.byref(free)):
            lines.append("C 盘     : 共 %.1f GB，剩余 %.1f GB" % (
                total.value / 2 ** 30, free.value / 2 ** 30))
    except Exception as e:
        lines.append("(内存/磁盘信息获取失败：%s)" % e)
    return "\n".join(lines)


def tool_web_fetch(url):
    """抓网页转纯文本。GitHub 系地址直连大概率超时，自动先走国内镜像；
    超时收紧到 10 秒，快速失败快速换路，不在死线路上耗着。"""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win7Assistant) Chrome/60.0"}
    try:
        host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    except Exception:
        host = ""
    is_gh = any(host == h or host.endswith("." + h) for h in _DL_GH_HOSTS)
    if is_gh:
        # 镜像在前（直连大概率被墙），全挂了再试直连
        candidates = [m + url for m in _DL_MIRRORS_DEFAULT] + [url]
    else:
        candidates = [url]

    raw, via = None, ""
    for i, u in enumerate(candidates):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=ua),
                                        timeout=10) as resp:
                raw = resp.read(200000).decode("utf-8", "replace")
            if u != url:
                via = "（经国内镜像加速）"
            break
        except urllib.error.HTTPError:
            # 镜像可能不支持这类资源（如 api），换下一个候选；最后一个再抛
            if i == len(candidates) - 1:
                raise
            continue
        except OSError:
            if i == len(candidates) - 1:
                raise
            continue
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return _cap("网页：%s%s\n%s" % (url, via, text))


# ------------------------------------------------------------ 网络诊断

def _pid_names():
    """跑一次 tasklist，拿 {pid: 进程名}。失败就返回空表（net_list 仍可用，只是没进程名）。"""
    names = {}
    try:
        p = subprocess.run("tasklist /fo csv /nh", shell=True, capture_output=True,
                           timeout=20, **hidden_kwargs())
        for line in _decode_stream(p.stdout).splitlines():
            # "映像名,PID,会话名,会话#,内存使用"
            parts = line.split('","')
            if len(parts) >= 2:
                nm = parts[0].lstrip('"').strip()
                pid = parts[1].strip().strip('"')
                if pid.isdigit():
                    names[int(pid)] = nm
    except Exception:
        pass
    return names


def tool_net_list(kind="all"):
    """本机 TCP/UDP 连接与监听端口，带进程名。"""
    kind = (kind or "all").strip().lower()
    if kind not in ("all", "listen", "est"):
        kind = "all"
    try:
        p = subprocess.run("netstat -ano", shell=True, capture_output=True,
                           timeout=30, **hidden_kwargs())
    except Exception as e:
        return "netstat 跑不起来：%s" % e
    names = _pid_names()
    rows = []
    for line in _decode_stream(p.stdout).splitlines():
        line = line.strip()
        if not line or line.upper().startswith("活动连接") or line.startswith("Proto"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        proto, local, remote, state = parts[0], parts[1], parts[2], parts[3]
        pid = parts[4] if len(parts) > 4 else ""
        is_tcp = proto.upper().startswith("TCP")
        if kind == "listen" and state.upper() != "LISTENING":
            continue
        if kind == "est" and state.upper() != "ESTABLISHED":
            continue
        # 端口高亮：本地地址里的 :端口
        def _hl(addr):
            if ":" not in addr:
                return addr
            host, port = addr.rsplit(":", 1)
            return "%s:%s" % (host, port)
        who = names.get(int(pid), "") if pid.isdigit() else ""
        rows.append("%-5s %-24s %-24s %-13s %s" % (
            proto, _hl(local), _hl(remote), state, ("%s (PID %s)" % (who, pid)) if who else pid))
    if not rows:
        return "没有符合条件的连接（kind=%s）。" % kind
    title = {"all": "全部连接", "listen": "监听中的端口", "est": "已建立的连接"}[kind]
    listen_n = sum(1 for r in rows if "LISTENING" in r)
    return "【%s】共 %d 条，其中监听 %d 个：\n%s" % (title, len(rows), listen_n, "\n".join(rows))


def _parse_ports(spec):
    """'80' / '1-1024' / '80,443,3389' -> [int]，去重排序。"""
    spec = (spec or "").strip()
    if not spec:
        return [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 3306, 3389,
                5432, 5900, 6379, 8080, 8443, 9200]
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            out.extend(range(max(1, lo), min(65535, hi) + 1))
        else:
            try:
                v = int(chunk)
            except ValueError:
                continue
            if 1 <= v <= 65535:
                out.append(v)
    return sorted(set(out))


def tool_net_scan(host, ports="", timeout=0.4):
    """并发 connect 扫描。只报告"能连上"的端口。"""
    import socket
    host = (host or "").strip() or "127.0.0.1"
    try:
        timeout = max(0.1, min(3.0, float(timeout)))
    except Exception:
        timeout = 0.4
    plist = _parse_ports(ports)
    if not plist:
        return "没解析出有效端口：%s" % ports
    if len(plist) > 4096:
        plist = plist[:4096]
    open_ports = []
    lock = threading.Lock()

    def probe(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            if s.connect_ex((host, port)) == 0:
                with lock:
                    open_ports.append(port)
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass

    workers = [threading.Thread(target=probe, args=(p,), daemon=True) for p in plist]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout + 1.0)
    if not open_ports:
        return "扫描 %s 的 %d 个端口：没有发现开放的。" % (host, len(plist))
    lines = []
    for port in sorted(open_ports):
        try:
            banner = socket.getservbyport(port, "tcp")
        except Exception:
            banner = ""
        lines.append("  开放  %-6d %s" % (port, banner))
    return "扫描 %s 的 %d 个端口，开放 %d 个：\n%s" % (
        host, len(plist), len(open_ports), "\n".join(lines))


_PROTO = {1: "ICMP", 6: "TCP", 17: "UDP"}


def _parse_pkt(data):
    """解 IP 头 + TCP/UDP 头，返回一行摘要。解不动就返回 None。"""
    if len(data) < 20:
        return None
    ihl = (data[0] & 0x0F) * 4
    if ihl < 20 or len(data) < ihl:
        return None
    proto = data[9]
    src = ".".join(str(b) for b in data[12:16])
    dst = ".".join(str(b) for b in data[16:20])
    total = (data[2] << 8) | data[3]
    name = _PROTO.get(proto, "proto%d" % proto)
    if proto == 6 and len(data) >= ihl + 20:
        tcp = data[ihl:]
        sport = (tcp[0] << 8) | tcp[1]
        dport = (tcp[2] << 8) | tcp[3]
        flags = tcp[13]
        fl = "".join(n for bit, n in ((0x02, "S"), (0x10, "A"), (0x08, "P"),
                                      (0x01, "F"), (0x04, "R")) if flags & bit)
        return "%s %s:%d -> %s:%d  [%s]  %dB" % (name, src, sport, dst, dport, fl or "-", total)
    if proto == 17 and len(data) >= ihl + 8:
        udp = data[ihl:]
        sport = (udp[0] << 8) | udp[1]
        dport = (udp[2] << 8) | udp[3]
        return "%s %s:%d -> %s:%d  %dB" % (name, src, sport, dst, dport, total)
    if proto == 1:
        return "%s %s -> %s  %dB" % (name, src, dst, total)
    return "%s %s -> %s  %dB" % (name, src, dst, total)


def _parse_app(proto, ihl, data):
    """解应用层关键字段：HTTP 的 Host+URI、DNS 的查询名。
    只取最能说明问题的部分，不做完整协议解析。"""
    body = data[ihl:]
    try:
        if proto == 6:
            if len(body) < 20:
                return ""
            doff = (body[12] >> 4) * 4
            if doff < 20 or len(body) < doff:
                return ""
            payload = body[doff:]
            if not payload:
                return ""
            head = payload[:400]
            low = head[:8].lower()
            if low.startswith((b"get ", b"post ", b"put ", b"head ", b"delete ",
                               b"options ", b"patch ")):
                line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                host = ""
                for ln in head.split(b"\r\n"):
                    if ln[:5].lower() == b"host:":
                        host = ln[5:].strip().decode("latin-1", "replace")
                        break
                return "HTTP %s%s" % (host + " " if host else "", line.split(" ", 1)[-1]
                                      if " " in line else line)
            if b"HTTP/" in head[:20]:
                line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                return "HTTP 响应 %s" % line
            return ""
        if proto == 17:
            if len(body) < 8:
                return ""
            sport = (body[0] << 8) | body[1]
            dport = (body[2] << 8) | body[3]
            if sport != 53 and dport != 53:
                return ""
            dns = body[8:]
            if len(dns) < 12 or dns[2] & 0x80:      # QR=1 是响应，只记查询
                return "DNS 响应"
            qd = (dns[4] << 8) | dns[5]
            if qd < 1:
                return ""
            i, names = 12, []
            while i < len(dns):
                n = dns[i]
                if n == 0:
                    break
                if n & 0xC0:
                    break
                names.append(dns[i + 1:i + 1 + n].decode("latin-1", "replace"))
                i += 1 + n
            return "DNS 查询 %s" % ".".join(x for x in names if x)
    except Exception:
        return ""
    return ""


def _write_pcap(path, packets):
    """把原始 IP 包写成标准 pcap（LINKTYPE_RAW=101），可用 Wireshark 打开。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 101))
        for ts, data in packets:
            f.write(struct.pack("<IIII", int(ts), int((ts % 1) * 1e6),
                                len(data), len(data)))
            f.write(data)


def tool_net_sniff(seconds=5, max_packets=200, save_pcap=""):
    """raw socket 抓包。Windows 需要管理员；SIO_RCVALL 拿不到就返回明确提示。"""
    import socket
    try:
        seconds = max(1, min(30, int(seconds)))
    except Exception:
        seconds = 5
    try:
        max_packets = max(1, min(2000, int(max_packets)))
    except Exception:
        max_packets = 200
    if os.name != "nt":
        return "抓包目前只实现了 Windows 路径（SIO_RCVALL），当前不是 Windows。"
    try:
        host = socket.gethostbyname(socket.gethostname())
    except Exception:
        host = "127.0.0.1"
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        s.bind((host, 0))
        # 打开混杂模式；非管理员会在这里抛 WSAEACCES(10013)
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
    except Exception as e:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass
        return ("抓包需要管理员权限（Windows 的 SIO_RCVALL 不给普通进程用）：%s\n"
                "解决办法：右键 start-gui.bat → 以管理员身份运行，然后重试。"
                "不抓包也可以用 net_list 看本机端口和连接。" % e)
    rows, stats, raw_pkts, hosts = [], {}, [], {}
    t0 = time.time()
    try:
        while len(rows) < max_packets and (time.time() - t0) < seconds:
            try:
                s.settimeout(max(0.2, seconds - (time.time() - t0)))
                data, _addr = s.recvfrom(65535)
            except socket.timeout:
                break
            except Exception:
                break
            raw_pkts.append((time.time(), data))
            line = _parse_pkt(data)
            if line:
                app = ""
                if len(data) >= 20:
                    ihl = (data[0] & 0x0F) * 4
                    app = _parse_app(data[9], ihl, data)
                if app:
                    line += "\n        └ %s" % app
                    # 统计对外联系最多的目标，这是抓包最想得到的结论
                    if " -> " in line:
                        dst = line.split(" -> ")[1].split()[0]
                        key = "%s %s" % (dst, app.split(" 查询 ")[-1].split(" ")[0]
                                         if app.startswith("DNS") else "")
                        hosts[key] = hosts.get(key, 0) + 1
                rows.append(line)
                key = line.split()[0]
                stats[key] = stats.get(key, 0) + 1
    finally:
        try:
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
    if not rows:
        return "抓了 %.1f 秒没收到包（网卡 %s）。可以换个时间再试，或先用 net_list 看端口。" % (
            time.time() - t0, host)
    summary = "、".join("%s %d 个" % (k, v) for k, v in sorted(stats.items(), key=lambda x: -x[1]))
    out = ["在 %s 上抓了 %.1f 秒，共 %d 个包（%s）" % (
        host, time.time() - t0, len(rows), summary)]
    if hosts:
        top = sorted(hosts.items(), key=lambda x: -x[1])[:8]
        out.append("\n【对外联系排行】")
        out += ["  %-28s %d 次" % (k, v) for k, v in top]
    out.append("\n【前 80 个包】")
    out += rows[:80]
    saved = ""
    if save_pcap:
        try:
            p = resolve_path(save_pcap)
            _write_pcap(p, raw_pkts)
            saved = "\n\n已存成 pcap：%s（可用 Wireshark 打开，共 %d 个原始包）" % (p, len(raw_pkts))
        except Exception as e:
            saved = "\n\npcap 保存失败：%s" % e
    return "\n".join(out) + saved


# ------------------------------------------------------------ 比对 / 进程 / 注册表 / 计划

def _line_set(text):
    return set(x.strip() for x in (text or "").splitlines() if x.strip())


def tool_compare(kind, left, right):
    """比对两份快照，输出「新增 / 消失 / 变化」的结论，而不是堆数据。"""
    kind = (kind or "").strip().lower()
    L, R = (left or "").strip(), (right or "").strip()

    if kind == "dirs":
        def snap(p):
            d = resolve_path(p)
            if not os.path.isdir(d):
                return None, "目录不存在：%s" % d
            out = []
            for root, dirs, files in os.walk(d):
                for fn in files:
                    fp = os.path.join(root, fn)
                    try:
                        out.append("%s|%d" % (os.path.relpath(fp, d), os.path.getsize(fp)))
                    except OSError:
                        pass
                if len(out) > 5000:
                    break
            return set(out), None
        a, ea = snap(L)
        if ea:
            return ea
        b, eb = snap(R)
        if eb:
            return eb
    elif kind == "files":
        def rd(p):
            f = resolve_path(p)
            if not os.path.isfile(f):
                return None, "文件不存在：%s" % f
            try:
                return open(f, "r", encoding="utf-8", errors="replace").read(), None
            except OSError as e:
                return None, "读不了：%s" % e
        ta, ea = rd(L)
        if ea:
            return ea
        tb, eb = rd(R)
        if eb:
            return eb
        if ta == tb:
            return "两个文件内容完全一致（%d 字符）。" % len(ta)
        la, lb = ta.splitlines(), tb.splitlines()
        diff = list(difflib.unified_diff(la, lb, fromfile=L, tofile=R, lineterm="", n=1))
        changed = sum(1 for x in diff if x[:1] in "+-" and x[:3] not in ("+++", "---"))
        return ("两个文件不同：左 %d 行 / 右 %d 行，差异行 %d。\n%s" % (
            len(la), len(lb), changed, "\n".join(diff[:120]) or "(无)"))
    else:
        # ports / text：按行集合比对
        a, b = _line_set(L), _line_set(R)

    added, gone = sorted(b - a), sorted(a - b)
    same = len(a & b)
    if not added and not gone:
        return "两份快照完全一致（%d 项），没有任何变化。" % same
    out = ["比对结果：相同 %d 项，新增 %d 项，消失 %d 项。" % (same, len(added), len(gone))]
    if added:
        out.append("\n【新增】")
        out += ["  + " + x for x in added[:40]]
    if gone:
        out.append("\n【消失】")
        out += ["  - " + x for x in gone[:40]]
    if len(added) > 40 or len(gone) > 40:
        out.append("\n（仅显示前 40 条）")
    return "\n".join(out)


def tool_proc_list(filter_kw=""):
    """列出进程：PID / 名称 / 内存 / 可执行文件路径。"""
    kw = (filter_kw or "").strip().lower()
    rows = []
    # wmic 在 Win7 SP1 上可用，能拿到完整路径；失败则退回 tasklist（没有路径）
    try:
        p = subprocess.run(
            'wmic process get Name,ProcessId,WorkingSetSize,ExecutablePath /format:csv',
            shell=True, capture_output=True, timeout=40, **hidden_kwargs())
        for line in _decode_stream(p.stdout).splitlines():
            parts = [x for x in line.split(",") if x != ""]
            if len(parts) < 3:
                continue
            path = parts[0].strip()
            pid = parts[-2].strip() if len(parts) >= 4 else ""
            mem = parts[-1].strip()
            name = os.path.basename(path) if path else (parts[1].strip() if len(parts) > 1 else "")
            if not pid.isdigit():
                continue
            rows.append((int(pid), name, mem, path))
    except Exception:
        rows = []
    if not rows:
        try:
            p = subprocess.run("tasklist /fo csv /nh", shell=True, capture_output=True,
                               timeout=30, **hidden_kwargs())
            for line in _decode_stream(p.stdout).splitlines():
                f = line.split('","')
                if len(f) < 5:
                    continue
                name = f[0].lstrip('"').strip()
                pid = f[1].strip().strip('"')
                mem = f[4].strip().strip('"')
                if not pid.isdigit():
                    continue
                rows.append((int(pid), name, mem, ""))
        except Exception as e:
            return "进程列表拿不到：%s" % e
    if kw:
        rows = [r for r in rows if kw in r[1].lower() or kw in (r[3] or "").lower()]
    if not rows:
        return "没有匹配「%s」的进程。" % kw
    rows.sort(key=lambda r: -r[0])
    total_mem = 0
    lines = []
    for pid, name, mem, path in rows[:300]:
        try:
            mb = int(mem) / 1048576.0
            total_mem += mb
            mems = "%.1f MB" % mb
        except Exception:
            mems = mem or "?"
        lines.append("PID %-7d %-28s %10s  %s" % (pid, name, mems, path or "(路径未知)"))
    return "共 %d 个进程%s，内存合计约 %.0f MB：\n%s" % (
        len(rows), "（已按「%s」过滤）" % kw if kw else "", total_mem, "\n".join(lines))


_REG_ROOTS = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKU": winreg.HKEY_USERS, "HKEY_USERS": winreg.HKEY_USERS,
    "HKCR": winreg.HKEY_CLASSES_ROOT, "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKCC": winreg.HKEY_CURRENT_CONFIG, "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
} if winreg else {}
_REG_TYPES = {winreg.REG_SZ: "REG_SZ", winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
              winreg.REG_BINARY: "REG_BINARY", winreg.REG_DWORD: "REG_DWORD",
              winreg.REG_MULTI_SZ: "REG_MULTI_SZ", winreg.REG_QWORD: "REG_QWORD"}


def tool_reg_query(key, value=""):
    """查询注册表：列出键下所有值，或只看某一个。"""
    import winreg
    key = (key or "").strip()
    if "\\" not in key:
        return "键路径不完整，比如 HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft"
    head, _, sub = key.partition("\\")
    root = _REG_ROOTS.get(head.upper())
    if root is None:
        return "不认识的根键：%s（可用 HKLM / HKCU / HKU / HKCR / HKCC）" % head
    try:
        h = winreg.OpenKey(root, sub)
    except Exception as e:
        return "打不开这个键：%s（%s）" % (key, e)
    try:
        want = (value or "").strip()
        if want:
            v, t = winreg.QueryValueEx(h, want)
            return "%s\\%s\n  类型：%s\n  值：%s" % (
                key, want, _REG_TYPES.get(t, str(t)),
                ("%d 字节" % len(v)) if t == winreg.REG_BINARY else v)
        n = 0
        out = ["%s 下的值：" % key]
        while True:
            try:
                name, v, t = winreg.EnumValue(h, n)
            except OSError:
                break
            shown = ("<%d 字节>" % len(v)) if t == winreg.REG_BINARY else v
            out.append("  %-34s %-14s %s" % (name or "(默认)", _REG_TYPES.get(t, str(t)), shown))
            n += 1
        if n == 0:
            return "%s 下面没有任何值（可能只有子键）。" % key
        out.append("\n共 %d 个值。" % n)
        return "\n".join(out)
    finally:
        winreg.CloseKey(h)


# ------------------------------------------------------------ 定时自动化

SCHEDULE_PATH = os.path.join(DATA_DIR, "schedule.json")


def _load_schedule():
    return load_json(SCHEDULE_PATH, [])


def _save_schedule(items):
    save_json(SCHEDULE_PATH, items)


def _parse_when(spec):
    """'daily 09:00' / 'weekly 1,3,5 09:30' / 'interval 30' -> dict，失败返回 None。"""
    parts = (spec or "").strip().split()
    if not parts:
        return None
    kind = parts[0].lower()
    if kind == "interval" and len(parts) >= 2:
        try:
            mins = max(1, int(float(parts[1])))
        except Exception:
            return None
        return {"kind": "interval", "minutes": mins}
    if kind in ("daily", "weekly") and len(parts) >= 2:
        hhmm = parts[1]
        if ":" not in hhmm:
            return None
        h, _, m = hhmm.partition(":")
        try:
            hour, minute = int(h), int(m)
        except Exception:
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        if kind == "daily":
            return {"kind": "daily", "hour": hour, "minute": minute}
        days = []
        for d in (parts[2].split(",") if len(parts) > 2 else []):
            try:
                v = int(d)
            except Exception:
                continue
            if 1 <= v <= 7:
                days.append(v)
        return {"kind": "weekly", "hour": hour, "minute": minute, "days": days or [1, 2, 3, 4, 5]}
    return None


def _due(item, now=None):
    """到点了吗？同一个周期内只触发一次（靠 last_run 去重）。"""
    now = now or time.localtime()
    w = item.get("when") or {}
    last = item.get("last_run") or 0
    if time.time() - last < 30:
        return False
    if w.get("kind") == "interval":
        return time.time() - last >= int(w.get("minutes", 30)) * 60
    hh, mm = int(w.get("hour", 0)), int(w.get("minute", 0))
    cur = now.tm_hour * 60 + now.tm_min
    tgt = hh * 60 + mm
    if not (tgt <= cur < tgt + 2):          # 给 2 分钟窗口，轮询不会漏
        return False
    if w.get("kind") == "weekly":
        wd = (now.tm_wday + 1) % 7 or 7      # 周一=1 … 周日=7
        if wd not in (w.get("days") or [1, 2, 3, 4, 5]):
            return False
    return True


def tool_schedule_add(name, when, action):
    name = (name or "").strip()
    action = (action or "").strip()
    if not name or not action:
        return "任务名和执行内容都不能空。"
    w = _parse_when(when)
    if w is None:
        return ("时间格式没看懂：%s\n支持：daily 09:00（每天）/ "
                "weekly 1,3,5 09:30（周一三五）/ interval 30（每 30 分钟）" % when)
    items = _load_schedule()
    items = [x for x in items if x.get("name") != name]
    items.append({"name": name, "when": w, "action": action,
                  "created": time.strftime("%Y-%m-%d %H:%M:%S"), "last_run": 0})
    _save_schedule(items)
    if w["kind"] == "daily":
        pretty = "每天 %02d:%02d" % (w["hour"], w["minute"])
    elif w["kind"] == "weekly":
        pretty = "每周%s %02d:%02d" % (",".join(str(d) for d in w["days"]),
                                     w["hour"], w["minute"])
    else:
        pretty = "每 %d 分钟" % w["minutes"]
    return "已添加定时任务「%s」：%s → %s\n（程序开着才会触发；共 %d 个任务）" % (
        name, pretty, action[:60], len(items))


def tool_schedule_list():
    items = _load_schedule()
    if not items:
        return "还没有定时任务。"
    out = ["共 %d 个定时任务：" % len(items)]
    for x in items:
        w = x.get("when") or {}
        pretty = {"daily": "每天 %02d:%02d" % (w.get("hour", 0), w.get("minute", 0)),
                  "weekly": "每周%s %02d:%02d" % (",".join(str(d) for d in w.get("days", [])),
                                                w.get("hour", 0), w.get("minute", 0)),
                  "interval": "每 %d 分钟" % w.get("minutes", 30)}.get(w.get("kind"), "?")
        last = x.get("last_run") or 0
        out.append("  %-16s %-18s %s%s" % (
            x.get("name", "?"), pretty, (x.get("action", "") or "")[:44],
            "（上次 %s）" % time.strftime("%m-%d %H:%M", time.localtime(last)) if last else ""))
    return "\n".join(out)


def tool_schedule_del(name):
    items = _load_schedule()
    left = [x for x in items if x.get("name") != (name or "").strip()]
    if len(left) == len(items):
        return "没找到叫「%s」的任务。" % name
    _save_schedule(left)
    return "已删除「%s」，还剩 %d 个任务。" % (name, len(left))


class Approver(object):
    """危险操作审批。auto=True 直接放行；deny_all=True 一律拒绝；
    没有询问界面（如 Telegram）时默认拒绝。

    层级语义（perm_decision 已算好要不要问）：
      need=False, ok=True   免打扰，直接放行
      need=False, ok=False  档位不允许，直接拒绝（不弹窗）
      need=True,  ok=True   要问；L3 走"明确授权"（用户得打字确认）
    """

    def __init__(self, auto_approve, ask_ui, deny_all=False, cfg=None):
        self.auto = bool(auto_approve)
        self.ask_ui = ask_ui
        self.deny_all = bool(deny_all)
        self.cfg = cfg

    def ask(self, desc, level="L2", force=False):
        # 老接口（不传层级）保持"弹卡片"行为，CLI/Telegram 那边照样能用。
        # force=True：工作区之外的越界操作，必须问人，auto/免打扰都不算数。
        if self.deny_all:
            return False
        if self.auto and not force:
            return True
        if not self.ask_ui:
            return False
        if force:
            try:
                return bool(self.ask_ui(desc, level="L3"))
            except TypeError:
                return bool(self.ask_ui(desc))
            except Exception:
                return False
        if self.cfg is not None:
            need, ok = perm_decision(self.cfg, level)
            if not ok:
                return False
            if not need:
                return True
            if PERM_ORDER.get(level, 2) == 3:
                # L3 动系统：必须明确授权，不能一键放行
                try:
                    return bool(self.ask_ui(desc, level="L3"))
                except TypeError:
                    return bool(self.ask_ui(desc))
                except Exception:
                    return False
        try:
            return bool(self.ask_ui(desc))
        except Exception:
            return False


def _tool_main_path(name, args):
    """取工具的主要目标路径（判断是否越出工作区用）。"""
    if not isinstance(args, dict):
        return ""
    for k in ("path", "dst", "target", "save_to", "out"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _execute_tool_impl(name, args, cfg, mem, approver, on_event):
    """执行一个工具，返回给模型的文本结果。"""
    workspace = cfg.get("agent", "workspace", fallback="").strip()
    level = tool_level(name, args)
    gear = _gear_of(cfg)
    denied = ("操作被权限档位拦下了。\n" + perm_hint(cfg, name, level))

    # ---- 工作区越界：一律按最高风险问人 ----
    # 配了 workspace 就代表"只许在这里动手"；越界一律弹窗，auto/免打扰
    # 都不算数，也不能被长期记忆里的"随便操作"一句话带过去。
    outside_ok = False
    target = _tool_main_path(name, args)
    if workspace and target:
        try:
            if not guard_path(resolve_path(target), workspace):
                level = "L3"
                desc = ("【工作区之外】%s 的目标不在允许范围内：%s\n"
                        "允许范围：%s\n访问/修改工作区以外的位置需要你明确同意。"
                        % (name, target, workspace))
                r = approver.ask(desc, level="L3", force=True)
                audit_log("L3", "allow" if r else "deny", name, args,
                          reason=("outside_approved" if r else "outside_denied"),
                          gear=gear)
                if not r:
                    return ("用户拒绝了这次工作区之外的访问（%s）。\n"
                            "建议：把目标文件复制到工作区 %s 下再操作，"
                            "或者请用户在设置里把工作区改成包含它的目录。"
                            % (target, workspace))
                outside_ok = True
        except Exception:
            outside_ok = False

    def ok(desc):
        r = approver.ask(desc, level=level, force=outside_ok)
        audit_log(level, "allow" if r else "deny", name, args,
                  reason=("explicit_auth" if r else "user_denied"), gear=gear)
        return r

    def free():
        """L0/L1 免打扰也记一笔，审计才答得上"它动过什么"。"""
        audit_log(level, "allow", name, args, reason="no_prompt", gear=gear)

    try:
        if name == "list_dir":
            free()
            return _cap(tool_list_dir(args.get("path", "~")))
        if name == "read_file":
            p = resolve_path(args.get("path", ""))
            if not outside_ok and not guard_path(p, workspace):
                return "不在允许操作的目录范围内（workspace 限制）。"
            free()
            return _cap(tool_read_file(p, args.get("max_chars", 8000),
                                       workspace=workspace))
        if name == "search_files":
            free()
            return _cap(tool_search_files(args.get("pattern", "*"), args.get("path", "~")))
        if name == "grep_files":
            free()
            return _cap(tool_grep_files(args.get("keyword", ""), args.get("path", "~"),
                                        args.get("ext", "")))
        if name == "run_cmd":
            cmd = args.get("command", "")
            if not ok("助手请求执行命令：\n%s\n\n允许执行吗？" % cmd):
                return denied if level == "L3" else "用户拒绝了执行这条命令。请换别的方式完成，或向用户说明原因。"
            return _cap(tool_run_cmd(cmd))
        if name == "write_file":
            p = resolve_path(args.get("path", ""))
            if not outside_ok and not guard_path(p, workspace) and not _in_logs(p):
                return "不在允许操作的目录范围内（workspace 限制）。"
            content = args.get("content", "")
            if not ok("助手请求写入文件：\n%s\n\n内容前 200 字：\n%s\n\n允许写入吗？"
                      % (p, content[:200])):
                return denied if level == "L2" else "用户拒绝了写入这个文件。"
            return _cap(tool_write_file(p, content))
        if name == "download_file":
            p = resolve_path(args.get("path", ""))
            if not outside_ok and not guard_path(p, workspace) and not _in_logs(p):
                return "不在允许操作的目录范围内（workspace 限制）。"
            if not ok("助手请求下载文件：\n%s\n\n保存到：\n%s\n\n允许吗？"
                      % (args.get("url", ""), p)):
                return denied if level == "L2" else "用户拒绝了下载这个文件。"
            free()
            return _cap(tool_download_file(args.get("url", ""), p,
                                           args.get("threads", 4), cfg))
        if name == "open_path":
            p = resolve_path(args.get("path", ""))
            if not ok("助手请求打开：\n%s\n\n允许吗？" % p):
                return denied if level == "L2" else "用户拒绝了打开这个路径。"
            return _cap(tool_open_path(p))
        if name == "app_launch":
            cmd = args.get("command", "")
            wd = args.get("workdir", "") or ""
            if not ok("助手请求在后台启动程序：\n%s\n工作目录：%s\n（输出/报错记录到 logs/apprun/，窗口会正常弹出）\n\n允许吗？"
                      % (cmd, wd or "（默认）")):
                return denied
            return _cap(tool_app_launch(cmd, wd))
        if name == "proc_windows":
            free()
            return _cap(tool_proc_windows(args.get("target", "")))
        if name == "proc_kill":
            t = str(args.get("target", "") or "")
            if not ok("助手请求结束进程：\n%s\n\n允许吗？" % t):
                return denied
            return _cap(tool_proc_kill(t))
        if name == "restore_file":
            p = resolve_path(args.get("path", ""))
            if not outside_ok and not guard_path(p, workspace) and not _in_logs(p):
                return "不在允许操作的目录范围内（workspace 限制）。"
            if not ok("助手请求从备份恢复文件：\n%s\n（恢复前当前版本也会先备份一份）\n\n允许吗？" % p):
                return denied
            return _cap(tool_restore_file(p, args.get("stamp", "")))
        if name == "sys_info":
            free()
            return _cap(tool_sys_info())
        if name == "net_list":
            free()
            return _cap(tool_net_list(args.get("kind", "all")))
        if name == "net_scan":
            host = (args.get("host", "") or "").strip()
            if not host:
                return "没给要扫的主机。"
            if not ok("助手请求扫描网络端口：\n目标：%s\n端口：%s\n\n允许执行吗？"
                      % (host, args.get("ports", "") or "常用端口")):
                return denied
            return _cap(tool_net_scan(host, args.get("ports", ""), args.get("timeout", 0.4)))
        if name == "net_sniff":
            if not ok("助手请求抓取网络数据包（需要管理员权限）：\n"
                      "时长：%s 秒\n\n允许执行吗？" % args.get("seconds", 5)):
                return denied
            return _cap(tool_net_sniff(args.get("seconds", 5),
                                       args.get("max_packets", 200),
                                       args.get("save_pcap", "")))
        if name == "compare":
            free()
            return _cap(tool_compare(args.get("kind", ""), args.get("left", ""),
                                     args.get("right", "")))
        if name == "proc_list":
            free()
            return _cap(tool_proc_list(args.get("filter", "")))
        if name == "reg_query":
            free()
            return _cap(tool_reg_query(args.get("key", ""), args.get("value", "")))
        if name == "schedule_add":
            if not ok("助手请求添加定时任务：\n%s\n\n允许吗？"
                      % (args.get("name", "") or "")):
                return denied
            return tool_schedule_add(args.get("name", ""), args.get("when", ""),
                                     args.get("action", ""))
        if name == "detect_preset":
            free()
            return _cap(tool_detect_preset(args.get("seconds", 2),
                                          bool(args.get("scan_all", False))))
        if name == "schedule_list":
            free()
            return tool_schedule_list()
        if name == "schedule_del":
            if not ok("助手请求删除定时任务：\n%s\n\n允许吗？"
                      % (args.get("name", "") or "")):
                return denied
            return tool_schedule_del(args.get("name", ""))
        if name == "web_fetch":
            free()
            return _cap(tool_web_fetch(args.get("url", "")))
        if name == "remember":
            free()
            fact = args.get("fact", "").strip()
            if not fact:
                return "没有提供要记住的内容。"
            if not mem.mem_cfg.get("enabled", True):
                return "长期记忆已在设置里关掉，这条没有保存。需要的话去「设置 → 记忆」打开。"
            if mem.remember(fact):
                return "已存入长期记忆：%s（以后每次对话都会带上）" % fact
            return "这条和最近记过的内容重复，没有重复保存。"
        if name == "recall":
            free()
            if not mem.mem_cfg.get("enabled", True):
                return "长期记忆已在设置里关掉。"
            visible = mem._visible_facts()
            if not visible:
                return "长期记忆为空。说「记住：xxx」就能存一条。"
            return "长期记忆（共 %d 条，最近的在后面）：\n%s" % (
                len(visible),
                "\n".join("- " + _fact_text(x) for x in visible[-50:]))
        if name == "load_skill":
            free()
            if not cfg.getboolean("assistant", "skills_enforced", fallback=True):
                return "技能库已被用户在设置里关闭，无法加载。"
            return _cap(tool_load_skill(args.get("name", "")))
        if name == "audit_log":
            free()
            return _cap(tool_audit_log(args.get("tail", 30), args.get("tool", ""),
                                       args.get("result", ""), args.get("since", "")))
        return "未知工具：%s" % name
    except Exception as e:
        return "工具执行出错：%s" % e


# ------------------------------------------------------------ Agent 循环

AGENT_INSTRUCTIONS = """你运行在用户自己的 Windows 电脑上，可以调用工具真正完成任务。

1. 先理解任务，必要时拆成几步；
2. 不确定电脑里有什么就先查（列目录/读文件/搜索），别猜路径；
3. 每步根据工具结果决定下一步，直到完成；
4. 最后用简洁中文汇报：做了什么、发现了什么、结论。

读类工具随便用；write_file / open_path / app_launch / proc_kill / restore_file / download_file 会向用户申请批准，被拒就换方式并说明。

【文件路径失效（被移动/重命名）——自动定位】
read_file 报"文件不存在"时，返回结果里已带"按文件名自动搜索"的候选路径列表：
1. 候选里就是原文件的，直接用新路径重试 read_file，不要再问用户"文件去哪了"；
2. 只有"名字相近的"候选时，先比对大小/修改时间或读开头几行确认是同一类文件再用；
3. 候选里完全没有时，才用 search_files 换个范围找，或问用户文件现在的位置。

【选工具的第一原则：能用只读工具就别用命令】
想"看"东西时优先用 read_file / list_dir / grep_files / web_fetch / net_list / proc_list / reg_query 这些只读工具（免批准、不会弹卡片）。
读办公文档（docx/pptx/xlsx/doc/xls）直接用 read_file，不用让用户转格式；老版 .doc/.xls 提取效果差时再建议另存为 .docx/.xlsx。
web_fetch 抓 GitHub 的页面/raw 文件会自动走国内镜像；打不开普通网址也会在 10 秒内快速报错，不会干等。
不要为了"取个网页内容/查个信息"去 run_cmd 里跑 powershell Invoke-WebRequest、curl、wget——那是执行命令，会被权限拦下来。
run_cmd 只在没有现成只读工具可用时才用；纯读取的命令（curl/Invoke-WebRequest/git log/dir/reg query 等）系统会自动放行。
工具接口不可用时，可写 ```tool {"tool":"list_dir","args":{"path":"C:\\"}} ``` 这样的代码块，系统会代替执行。

【下载外网资源】
GitHub 的 release/raw/archive 用 download_file 下载即可，它会自动测速挑国内加速镜像。
git clone 仓库慢或超时，就在仓库地址前拼镜像前缀重试，例如：
  git clone https://gh-proxy.com/https://github.com/用户名/仓库名.git
其他镜像前缀（失效就换）：https://ghfast.top/ https://ghproxy.net/
【诊断程序"跑不起来"的标准流程】
1. 不要用 run_cmd 跑带窗口的 GUI 程序（会一直等到超时）——用 app_launch 后台启动，它把 stdout/stderr 记到 logs/apprun/ 日志；
2. read_file 读那份日志看完整 traceback；
3. proc_windows 查真实进程有没有弹出可见窗口（分清"崩了"还是"起了但窗口失败"）；
4. 定位到代码/配置问题后，先改（write_file 覆盖前会自动备份原文件），再 app_launch 复跑验证；
5. 改坏了用 restore_file 一键回滚到备份版本；卡死的进程用 proc_kill 结束后重试。

【权限分级】你的工具按四级权限管理，档位由用户控制：
- L0 只读（列目录/读文件/看进程/查端口/看注册表）：随时可用
- L1 写自己（写日志、存抓包，只能进 logs/ 目录）：随时可用
- L2 改配置（写用户自己的文件、改预设、打开程序、后台启动程序、结束进程、恢复备份）：需要用户同意
- L3 动系统（执行命令、发包扫描、抓包、改网络设置）：需要用户明确授权
如果某个操作被档位拦下，就明确告诉用户当前档位不允许，建议他切档位或换个方式，不要反复重试同一个被拦的操作。

【何时停止 —— 重要】
用户最反感"事情做完了还在不停弹卡片要权限"。严格遵守：
1. 目标一达成，立刻写最终答复，**停止调用任何工具**；
2. 不要做多余确认：写文件后不必再读一遍验证，查到结果就够了，别重复查同一个东西；
3. 不要为了探测环境去写临时脚本（比如 _probe.py、test.py），能用现成工具查到的就直接查；
4. 需要批准的操作（run_cmd / write_file / net_scan / net_sniff）尤其要省——每多一步就多弹一次卡片；
5. 如果发现自己在做"验证/确认/再试一次"性质的事，说明已经在绕圈子，停下来直接汇报已有结果；
6. 一步能查完的事，不要拆成多步。"""


CHAT_INSTRUCTIONS = """你当前是【纯聊天模式】：这次请求没有给你任何工具。
你无法读取用户电脑里的文件、无法执行命令、无法上网，也拿不到任何真实的本机信息。

硬性要求：
1. 不要假装看过任何文件、目录或系统信息，也不要编造扫描结果；
2. 不要输出任何工具调用格式（包括 <|DSML| > 标记或代码块）；
3. 用户若想让你看文件/执行命令，直接说明需要切换到 Agent 模式再发一次。"""


# ------------------------------------------------------------ 三层技能库
# 第一层·常驻：技能清单（名字+一句话描述）每轮注入系统提示；
# 第二层·命中才拉：用户消息命中描述或模型判断相关时，用 load_skill 拉 SKILL.md 全文；
# 第三层·点名直载：用户说「用 xx 技能做」直接加载，优先级最高，跳过匹配。
# SKILL.md 里挂的 references/、scripts/ 等附属文件是第三层之外"用到才读"。

SKILLS_DIR = os.path.join(ROOT_DIR, "skills")
SKILL_BODY_LIMIT = 20000        # 单个技能全文塞进对话的上限（字符）
SKILL_LIST_LIMIT = 10000        # 常驻清单的上限（字符），装太多也不爆上下文

_SKILL_STATE = {"loaded": set()}   # 本轮 agent_run 已加载的技能（目录名）


def _parse_skill_md(path):
    """解析 SKILL.md：返回 (meta, body)。frontmatter 用简易 key: value 解析，
    不引第三方 yaml——保持纯标准库。"""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return {}, "（读取失败：%s）" % e
    meta, body = {}, text
    if text.startswith("---"):
        m = re.match(r"---\s*\n(.*?)\n---\s*\n?", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition(":")
                    k = k.strip().lower()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        meta[k] = v
            body = text[m.end():]
    return meta, body


def scan_skills():
    """扫描 skills/ 目录：每个子目录里有 SKILL.md 就算一个技能。
    返回 [{name, dir, description, path}]，按目录名排序。"""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    try:
        names = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return out
    for d in names:
        sdir = os.path.join(SKILLS_DIR, d)
        sp = os.path.join(sdir, "SKILL.md")
        if not os.path.isdir(sdir) or not os.path.isfile(sp):
            continue
        meta, _ = _parse_skill_md(sp)
        out.append({
            "name": meta.get("name") or d,
            "dir": d,
            "description": meta.get("description", ""),
            "path": sp,
        })
    return out


def skills_block():
    """第一层常驻清单：注入系统提示。技能很多时截断清单，防止挤爆上下文。"""
    skills = scan_skills()
    if not skills:
        return ""
    lines = [
        "【技能库 · 强制执行】用户自定义技能（三层加载，清单是第一层常驻项）：",
        "- 【必须】用户消息命中某技能的触发描述、或你判断某技能明显适用时，"
        "先调 load_skill 拉全文，再按技能说明书干活——禁止跳过技能凭已有知识直接回答；",
        "- 【最高优先级】用户点名要用某个技能（如「用 xx 技能做」）→ 直接 load_skill，不用犹豫；",
        "- 清单里标了【已加载】的不要再拉一遍；技能提到的 references/、scripts/ 附属文件用到才用 read_file 读。",
        "可用技能：",
    ]
    for s in skills:
        mark = "【已加载】" if s["dir"] in _SKILL_STATE["loaded"] else ""
        lines.append("- %s：%s%s" % (s["name"], mark, s["description"]))
    block = "\n".join(lines)
    if len(block) > SKILL_LIST_LIMIT:
        block = block[:SKILL_LIST_LIMIT] + "\n……（技能太多，清单已截断；可用 load_skill 按名字加载）"
    return block


def tool_load_skill(name):
    """第二/三层入口：把 SKILL.md 全文返回给模型。已加载过则提示复用。"""
    skills = scan_skills()
    want = (name or "").strip()
    if not want:
        return "参数错误：要加载的技能名不能为空。可用技能：" + \
            ", ".join(s["name"] for s in skills)
    hit = None
    wl = want.lower()
    for s in skills:
        if s["name"].lower() == wl or s["dir"].lower() == wl:
            hit = s
            break
    if hit is None:
        for s in skills:                        # 宽松匹配：名字包含
            if wl in s["name"].lower() or wl in s["dir"].lower():
                hit = s
                break
    if hit is None:
        return ("没有叫 %s 的技能。可用技能：%s"
                % (want, ", ".join(s["name"] for s in skills) or "（技能库是空的）"))
    if hit["dir"] in _SKILL_STATE["loaded"]:
        return ("技能 %s 本会话已加载过，全文就在上面，直接用即可，不要重复加载。"
                % hit["name"])
    meta, body = _parse_skill_md(hit["path"])
    _SKILL_STATE["loaded"].add(hit["dir"])
    body = body.strip() or "（SKILL.md 没有正文）"
    if len(body) > SKILL_BODY_LIMIT:
        body = body[:SKILL_BODY_LIMIT] + "\n……（超长已截断，附属细节可用 read_file 读原文件）"
    refs = [n for n in sorted(os.listdir(os.path.dirname(hit["path"])))
            if n != "SKILL.md"] if os.path.isdir(os.path.dirname(hit["path"])) else []
    head = "【技能已加载：%s｜路径：%s】\n" % (hit["name"], hit["path"])
    if refs:
        head += "附属文件（用到才 read_file 读）：%s\n" % ", ".join(refs)
    return head + body


def build_system_prompt(cfg, plain=False, readonly=False):
    base = cfg.get("assistant", "system_prompt", fallback="你是一个得力的中文个人助手。")
    env_info = "\n【环境信息】\n日期：%s\n系统：%s\n用户目录：%s" % (
        time.strftime("%Y-%m-%d %A"), platform.platform(), os.path.expanduser("~"))
    if plain:
        rules = CHAT_INSTRUCTIONS
        mode_line = "【当前模式】Ask 纯聊天：本次没有挂载任何工具。"
    elif readonly:
        rules = AGENT_INSTRUCTIONS
        mode_line = ("【当前模式】Plan 只读：可用列目录/读文件/搜索/系统信息/抓网页；"
                     "执行命令、写文件、打开文件会被系统直接拦下。")
    else:
        rules = AGENT_INSTRUCTIONS
        mode_line = ("【当前模式】Agent 全权限：本次请求已经挂载了全部工具，"
                     "你真的可以读写用户的文件、执行命令。")
    anti = ""
    if not plain:
        anti = ("\n注意：如果历史对话里你曾说自己「纯聊天模式」「不能读写文件」「没有工具」，"
                "那是旧模式下的旧回答，已经作废。请以【当前模式】和工具列表为准，不要重复那种说法。")
    # 自动记忆：让模型自己决定什么时候该记，不额外花一次请求
    if not plain and cfg.getboolean("memory", "auto", fallback=True):
        anti += ("\n【自动记忆已开启】当你从对话里学到关于用户或这台电脑的持久事实时"
                 "（姓名、习惯偏好、常用目录、项目约定、明确说「以后都这样」的要求），"
                 "主动调用 remember 工具记下来，下次对话就能用上；一次性的、只对当前任务有用的"
                 "信息不要记。")
    # 第一层技能库常驻清单（Ask 纯聊天不注入——没有工具就加载不了；
    # 设置里「强制执行 Skill」关掉后整个技能库不进提示词，一点不占 token）
    if not plain and cfg.getboolean("assistant", "skills_enforced", fallback=True):
        sb = skills_block()
        if sb:
            anti += "\n" + sb
    # 输出语言：界面切英文时，模型回答也用英文（自然口语，不用生僻词）
    if (cfg.get("assistant", "lang", fallback="zh") or "zh").strip().lower() == "en":
        anti += ("\n【Output language】Always reply in clear, natural English "
                 "(plain everyday wording, no jargon). Keep tool arguments unchanged.")
    else:
        anti += "\n【输出语言】一律用简体中文回答。"
    # 会话边界：明确告诉模型每个对话从零开始，别的对话的记忆不可见
    anti += ("\n【会话边界】每个对话完全独立、从零开始：你只能看到当前对话里的"
             "历史消息、当前会话学到的临时记忆和上方的固定记忆。"
             "其他对话的内容对你不存在，不要提及或暗示任何其他对话。")
    return base + "\n\n" + mode_line + "\n" + rules + anti + env_info


def parse_tool_blocks(text):
    """降级协议：从助手纯文本里解析 ```tool {"tool":...,"args":...} ``` 块。"""
    calls = []
    for m in re.finditer(r"```(?:tool|json)?\s*\n(\{.*?\})\s*\n?```", text or "", re.S):
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("tool"):
            calls.append((obj["tool"], obj.get("args") or {}))
    return calls


# ------------------------------------------------------------ 附件

ATTACH_PER_FILE = 12000      # 单个附件最多塞进对话的字符数
ATTACH_TOTAL = 24000        # 一次性附件总量上限


def _decode_bytes(data):
    # 只用前 64KB 判断编码，命中后全文只解一次；
    # 不能把 gbk 放最前——GBK 几乎不会解码失败，会把 UTF-8 文件整篇解成乱码。
    head = data[:65536]
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            head.decode(enc)
            return data.decode(enc, "replace"), enc
        except Exception:
            continue
    return data.decode("latin-1", "replace"), "latin-1"


def file_to_prompt(path, limit=ATTACH_PER_FILE):
    """把文件转成能塞进对话的文本块。
    返回 dict: name / size / kind(text|binary|error) / sent(实际字符数) / block(给模型看的)。"""
    name = os.path.basename(path) or path
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return {"name": name, "size": 0, "kind": "error", "sent": 0,
                "block": "【附件：%s】读取失败：%s\n路径：%s" % (name, e, path)}
    try:
        with open(path, "rb") as f:
            raw = f.read(limit * 6 + 8192)
    except OSError as e:
        return {"name": name, "size": size, "kind": "error", "sent": 0,
                "block": "【附件：%s】读取失败：%s\n路径：%s" % (name, e, path)}

    if b"\x00" in raw[:4096]:
        return {"name": name, "size": size, "kind": "binary", "sent": 0,
                "block": ("【附件：%s】%d 字节，二进制文件，内容未内联。\n"
                          "路径：%s\n需要处理时可用工具读取或打开它。" % (name, size, path))}

    text, enc = _decode_bytes(raw)
    cut = len(text) > limit
    body = text[:limit]
    head = "【附件：%s｜%d 字节｜编码 %s%s】\n路径：%s\n```\n" % (
        name, size, enc, "｜已截断前 %d 字" % limit if cut else "", path)
    block = head + body.rstrip() + "\n```"
    return {"name": name, "size": size, "kind": "text", "sent": len(body), "block": block}


def build_attachment_text(paths, per_file=ATTACH_PER_FILE, total=ATTACH_TOTAL):
    """把多个附件拼成一段给模型的文本 + 返回展示用的名字列表。"""
    blocks, names = [], []
    budget = total
    for p in paths:
        if budget <= 0:
            names.append(os.path.basename(p) + "（超出总量，未内联）")
            continue
        info = file_to_prompt(p, min(per_file, budget))
        budget -= max(info["sent"], 0)
        blocks.append(info["block"])
        names.append(info["name"])
    return "\n\n".join(blocks), names


# ------------------------------------------------------------ DSML 兜底
# DeepSeek V4 的原生工具调用标记是 <|DSML|tool_calls> / <|DSML|invoke name="x">
# <|DSML|parameter name="p" string="true">值</|DSML|parameter>（官方 encoding 文档）。
# 当请求里没带 tools、而提示词又在讲工具时，模型会把这种标记直接写进正文，
# 界面上就变成一串 "<|DSML||calls>" 乱码——这里负责把它抢救成真正的工具调用。

DSML_MARK = re.compile(r"<\s*/?\s*[\|｜]{1,2}\s*DSML\s*[\|｜]{1,2}", re.I)
DSML_CLOSED = re.compile(r"<\s*/\s*[\|｜]{1,2}\s*DSML\s*[\|｜]{1,2}\s*tool_calls\s*>", re.I)


def _loose_json(val):
    """宽容的 JSON 解析：模型常把 Windows 路径写成 C:\\Users 这种非法转义。"""
    try:
        return json.loads(val)
    except Exception:
        pass
    try:
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", val))
    except Exception:
        return None


def parse_dsml(text):
    """把被当成普通文本吐出来的 DSML 工具调用解析成 [(name, args)]。"""
    if not text or not DSML_MARK.search(text):
        return []
    s = DSML_MARK.sub("\x01", text)
    s = re.sub(r"\x01\s+", "\x01", s)      # 真实输出里标记后面常带一个空格
    closed = bool(DSML_CLOSED.search(text))
    calls = []
    for seg in s.split("\x01invoke")[1:]:
        m = re.match(r'\s*name\s*=\s*"([^"]+)"\s*>?', seg)
        if not m:
            continue
        name = m.group(1)
        body = seg[m.end():]
        args = {}
        for pm in re.finditer(
                r'\x01parameter\s+name\s*=\s*"([^"]+)"'
                r'(?:\s+string\s*=\s*"(true|false)")?\s*>(.*?)'
                r'(?=\x01parameter|\x01invoke|\x01tool_calls|$)', body, re.S):
            key, flag, val = pm.group(1), pm.group(2), pm.group(3)
            val = val.strip()
            # 去掉尾巴上的闭合标记残片（</|DSML|parameter> 之类）
            val = re.sub(r"<\s*/\s*\x01[^>]*>\s*$", "", val).strip()
            val = re.sub(r"<\s*/\s*$", "", val).strip()
            if flag == "false":
                parsed = _loose_json(val)
                args[key] = parsed if parsed is not None else val
            else:
                args[key] = val
        # 模型有时会退化成 parameter name="args"，里面塞整个 JSON
        if len(args) == 1:
            only = list(args)[0]
            if only in ("args", "arguments") and isinstance(args[only], str):
                inner = _loose_json(args[only])
                if isinstance(inner, dict):
                    args = inner
        calls.append((name, args))
    # 标记没闭合（被截断）且一个参数都没解出来 → 认定是残缺输出，不执行
    if not closed:
        calls = [c for c in calls if c[1]]
    return calls


def strip_dsml(text):
    """把 DSML 段整块摘掉（保留它前面的正文），界面上永远看不到这种乱码。"""
    if not text or not DSML_MARK.search(text):
        return text or ""
    s = DSML_MARK.sub("\x01", text)
    s = re.sub(r"\x01\s*", "\x01", s)
    for tag in ("\x01tool_calls", "\x01calls", "\x01invoke", "\x01"):
        i = s.find(tag)
        if i >= 0:
            return s[:i].strip()
    return s.strip()


def agent_run(cfg, mem, user_text, approver, on_event=None, plain=False,
              readonly=False, stop_event=None, history_text=None):
    """Agent 主循环：思考 -> 调工具 -> 观察 -> 再思考 ... -> 汇报。
    readonly=True 只挂载只读工具（计划模式）；stop_event 置位时安全停止。
    history_text：存进历史的精简版（附件内容只在本次请求里发，不写历史，省 token）。"""
    def emit(kind, text):
        if on_event:
            try:
                on_event(kind, text)
            except Exception:
                pass

    TOOL_LIMIT[0] = cfg.getint("agent", "tool_output_chars", fallback=MAX_TOOL_OUTPUT)
    _SKILL_STATE["loaded"].clear()      # 技能加载状态按轮重置（提示词会标【已加载】）
    turn = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "reasoning_tokens": 0}

    def track():
        for k in turn:
            turn[k] += int(LAST_USAGE.get(k) or 0)
        emit("usage", dict(turn))

    mem.add("user", history_text or user_text)
    # 每轮任务开始前，先把记忆配置和记忆内容固定一遍：
    # 这样在设置里改了开关/条数，当轮就生效，不用重启。
    mem.apply_config(cfg)
    messages = mem.build_messages(build_system_prompt(cfg, plain=plain, readonly=readonly))
    if history_text:
        # 历史里只留了精简版（文件名），真正的文件正文只在这一轮请求里带上
        messages.append({"role": "user", "content": user_text})

    max_steps = cfg.getint("agent", "max_steps", fallback=MAX_STEPS)
    if plain:
        tools = None
    else:
        # 技能库强制执行关掉时，把 load_skill 也从工具列表里摘掉，
        # 不给模型任何碰技能库的入口（提示词里同样不会出现技能清单）。
        if not cfg.getboolean("assistant", "skills_enforced", fallback=True):
            tools = [t for t in TOOLS_SCHEMA
                     if t.get("function", {}).get("name") != "load_skill"]
        elif readonly:
            tools = [t for t in TOOLS_SCHEMA
                     if t.get("function", {}).get("name") not in DANGEROUS_TOOLS]
        else:
            tools = TOOLS_SCHEMA
    # 工具预算：太少不够用，太多模型会选错（文档硬约束 ≤25）。
    # 超出时按"冷门程度"从后往前裁，可通过 [agent] max_tools 调整。
    if tools:
        try:
            budget = cfg.getint("agent", "max_tools", fallback=0)
            if 0 < budget < len(tools):
                cold = ("audit_log", "detect_preset", "compare", "net_sniff",
                        "reg_query", "schedule_del", "restore_file")
                ranked = [t for t in tools
                          if t.get("function", {}).get("name") not in cold]
                ranked += [t for t in tools
                           if t.get("function", {}).get("name") in cold]
                tools = ranked[:budget]
                emit("think", "（本轮挂载 %d 个工具，其余可在设置里放开）" % budget)
        except Exception:
            pass
    seen = {}
    step = 0
    streamed = [False]      # 本轮响应是否已流式吐字（吐过就不再整段 emit think）

    # ---- 熔断器（L0 安全层）----
    # 失控的 Agent 比不干活的 Agent 危险得多：危险操作连发、批量写文件、
    # 或者绕圈子停不下来时，自动降为只读，要求人工恢复。
    fuse = {"danger": 0, "writes": 0, "tool_calls": 0, "tripped": ""}

    def _fuse_check(name, args):
        if fuse["tripped"]:
            return ("已熔断：%s。本轮拒绝继续执行工具，请让用户确认后重开一个任务。"
                    % fuse["tripped"])
        lv = tool_level(name, args)
        if lv == "L3" and fuse["danger"] >= 5:
            fuse["tripped"] = "危险操作超过 5 次"
            emit("error", "已熔断：危险操作超过 5 次，转为只读，需要人工恢复。")
            return "已熔断（危险操作超过 5 次），拒绝执行。"
        if name == "write_file" and fuse["writes"] >= 200:
            fuse["tripped"] = "写文件超过 200 个"
            emit("error", "已熔断：写文件超过 200 个，转为只读，需要人工恢复。")
            return "已熔断（写文件超过 200 个），拒绝执行。"
        if fuse["tool_calls"] >= 60:
            fuse["tripped"] = "工具调用超过 60 次"
            emit("error", "已熔断：工具调用超过 60 次仍未结束，转为只读，需要人工恢复。")
            return "已熔断（工具调用超过 60 次），拒绝执行。"
        return ""

    def _exec(name, args):
        blocked = _fuse_check(name, args)
        if blocked:
            return blocked
        lv = tool_level(name, args)
        if lv == "L3":
            fuse["danger"] += 1
        if name == "write_file":
            fuse["writes"] += 1
        fuse["tool_calls"] += 1
        return execute_tool(name, args, cfg, mem, approver, emit)

    def _delta(kind, piece):
        streamed[0] = True
        emit("think" if kind == "reason" else "delta", piece)

    while step < max_steps:
        if stop_event is not None and stop_event.is_set():
            emit("error", "用户停止了当前任务。")
            mem.add("assistant", "（用户停止了任务）")
            return "⏹ 已停止。已完成的结果如上，再次发送消息可以继续。"
        step += 1
        streamed[0] = False
        try:
            msg = chat_raw(cfg, messages, tools=tools, on_delta=_delta,
                           stop_event=stop_event)
        except UserStop:
            emit("error", "用户停止了当前任务。")
            mem.add("assistant", "（用户停止了任务）")
            return "⏹ 已停止。已完成的结果如上，再次发送消息可以继续。"
        except Exception as e:
            if tools is not None:
                # 接口可能不支持 function calling，降级为纯聊天
                emit("error", "工具调用接口报错，降级为纯聊天：%s" % e)
                tools = None
                streamed[0] = False
                try:
                    msg = chat_raw(cfg, messages, tools=None, on_delta=_delta,
                                   stop_event=stop_event)
                except UserStop:
                    emit("error", "用户停止了当前任务。")
                    mem.add("assistant", "（用户停止了任务）")
                    return "⏹ 已停止。已完成的结果如上，再次发送消息可以继续。"
                except Exception as e2:
                    return "出错了：%s" % e2
            else:
                return "出错了：%s" % e

        track()
        raw = msg.get("content") or ""
        dsml_calls = parse_dsml(raw)
        incomplete_dsml = bool(DSML_MARK.search(raw)) and not dsml_calls
        content = strip_dsml(raw)
        if content != raw:
            msg["content"] = content       # 别把乱码再喂回模型
        if dsml_calls and plain:
            mem.add("assistant", "（纯聊天模式下模型试图调用工具，已拦截）")
            return ("当前是「Ask 纯聊天模式」，我不会碰你的电脑，所以这个请求没法执行。\n"
                    "顶部模式切到「Agent」再发一次，就能真的去看文件/执行命令了。")
        if content.strip() and not streamed[0]:
            emit("think", content.strip())
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            blocks = parse_tool_blocks(content) + dsml_calls
            if blocks:
                for name, args in blocks:
                    emit("tool", "%s %s" % (name, json.dumps(args, ensure_ascii=False)))
                    result = _exec(name, args)
                    emit("result", _cap(result))
                    messages.append({"role": "user", "content":
                                     "[工具 %s 的执行结果]\n%s" % (name, result)})
                continue
            if incomplete_dsml and not content.strip():
                return ("模型输出了工具调用标记，但内容不完整（多半被 max_tokens 截断了），"
                        "这次没能真正执行。\n把「设置 → 单次回复上限」调到 2048 再发一次；"
                        "如果模式是 Ask，切成 Agent 才能用工具。")
            # 没有工具调用 = 最终答复
            if not content.strip() and LAST_FINISH.get("reason") == "length":
                return ("模型把这次的单次回复上限（max_tokens）用光了，其中思考占了一部分，"
                        "所以没留下正文。\n两种改法：①「设置 → 单次回复上限」调大到 2048；"
                        "②「设置 → 思考档位」选「关闭」（日常问答够用，也最省）。")
            final = content.strip() or "（模型没有返回内容）"
            if content.strip() and LAST_FINISH.get("reason") == "length":
                mt = cfg.getint("llm", "max_tokens", fallback=0)
                final += ("\n\n---\n（提示：这次回答被「单次回复上限 %d tokens」截断了，后面的内容没生成出来。"
                          "要完整的长代码/长文档，请在「设置 → 单次回复上限」调到 4096 再试。）" % mt)
            mem.add("assistant", final)
            return final

        # 先逐条做重复/只读模式拦截，剩下的按层级分组执行：
        # L0 只读工具（模型经常一口气"列目录+读文件+查进程+查注册表"）并发跑，
        # 写/系统类工具保持串行——审批交互和真实副作用绝不并发。
        todo = []                 # [(i, tc, name, args)]
        for i, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            except Exception:
                args = {}
            key = name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 3:
                emit("error", "检测到重复操作（%s），停止继续调用。" % name)
                messages.append({"role": "tool", "tool_call_id": tc.get("id") or ("call_%d" % i),
                                 "content": "系统提示：这个操作已经重复执行多次，已自动停止。请直接根据已有信息回答用户。"})
                continue
            if readonly and name in DANGEROUS_TOOLS:
                emit("error", "计划模式（只读）已阻止危险工具：%s" % name)
                messages.append({"role": "tool", "tool_call_id": tc.get("id") or ("call_%d" % i),
                                 "content": "系统提示：当前是计划模式（只读），已阻止 %s。请改用只读方式分析，或直接汇报结论。" % name})
                continue
            emit("tool", "%s %s" % (name, json.dumps(args, ensure_ascii=False)))
            todo.append((i, tc, name, args))

        # L0 并发批：线程池一起跑，结果按原顺序回填。
        # remember 会写记忆文件，避免并发写坏 记忆.md，留在串行执行。
        par = [(i, tc, name, args) for (i, tc, name, args) in todo
               if TOOL_LEVEL.get(name) == "L0" and name != "remember"]
        par_res = {}
        if len(par) >= 2:
            try:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(4, len(par))) as ex:
                    futs = [(i, tc, ex.submit(_exec, name, args))
                            for (i, tc, name, args) in par]
                    for i, tc, fu in futs:
                        try:
                            par_res[i] = fu.result()
                        except Exception as e:
                            par_res[i] = "工具执行出错：%s" % e
            except Exception:
                par_res = {}          # 线程池不可用（极端环境）就全部退回串行

        for i, tc, name, args in todo:
            if i in par_res:
                result = par_res[i]
            else:
                result = _exec(name, args)
            emit("result", _cap(result))
            messages.append({"role": "tool",
                             "tool_call_id": tc.get("id") or ("call_%d" % i),
                             "content": result})

    # 步数用尽：让模型基于已有信息收尾
    emit("error", "已达到最大步数（%d），让模型总结目前进展。" % max_steps)
    try:
        messages.append({"role": "user", "content":
                         "行动步数已达上限。请根据以上信息，用中文向用户总结目前的进展、发现和结论，不要再调用工具。"})
        _r = chat_raw(cfg, messages, tools=None)
        track()
        final = _r.get("content", "").strip()
    except Exception:
        final = ""
    if not final:
        final = "（任务步骤太多被中断了，这是目前已知的信息：\n%s）" % (
            "\n".join(str(m.get("content"))[:300] for m in messages[-6:] if m.get("content")))
    mem.add("assistant", final)
    return final


def handle_message(cfg, mem, text, approver=None, on_event=None, plain=False,
                   readonly=False, stop_event=None, history_text=None):
    """处理一条用户输入：识别"记住"指令，否则走 Agent。"""
    low = text.lower()
    for p in REMEMBER_PREFIXES:
        if low.startswith(p.lower()):
            fact = text[len(p):].strip()
            if fact:
                if not cfg.getboolean("memory", "enabled", fallback=True):
                    return ("长期记忆已经在「设置 → 记忆」里关掉了，这条没有保存。\n"
                            "打开开关后再说一次「记住：」就能存。")
                mem.apply_config(cfg)
                if mem.remember(fact):
                    return "好的，已记住：%s（以后每次对话我都会带着这条记忆）" % fact
                return "这条和最近记过的内容重复，没有重复保存。"
            break
    if approver is None:
        approver = Approver(True, None)
    return agent_run(cfg, mem, text, approver, on_event=on_event, plain=plain,
                     readonly=readonly, stop_event=stop_event,
                     history_text=history_text)


# ------------------------------------------------------------ 三种界面

def run_gui(cfg, mem):
    """图形界面已由 wb_app.py（明枢Win7 界面）接管；此处仅作兜底提示。"""
    print("图形界面已升级为明枢Win7 界面（wb_app.py）。")
    print("请运行：python wb_app.py   或双击 start-gui.bat")
    print("或者使用命令行模式：python win7_assistant.py --cli")
    sys.exit(0)


def cli_ask(desc):
    print("\n[需要批准] %s" % desc)
    try:
        ans = input("允许吗？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes", "是", "允许")


def run_cli(cfg, mem):
    print("Win7 个人 AI 助手（Agent 版，输入 退出 结束）")
    approver = Approver(cfg.getboolean("agent", "auto_approve", fallback=False), cli_ask,
                        cfg=cfg)

    def emit(kind, text):
        # 流式模式：思考碎片和正文增量连续打印，不打断行
        if kind in ("think", "delta"):
            print(text, end="")
            sys.stdout.flush()
            return
        prefix = {"tool": "[调用工具] ", "result": "[工具结果] ",
                  "error": "[提示] "}.get(kind, "")
        print("\n%s%s" % (prefix, text))

    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if text in ("退出", "exit", "quit"):
            break
        if not text:
            continue
        try:
            reply = handle_message(cfg, mem, text, approver, emit)
        except Exception as e:
            reply = "出错了：%s" % e
        print("\n助手> %s" % reply)


def tg_call(token, method, params=None):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    if params:
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data)
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_telegram(cfg, mem):
    token = cfg.get("telegram", "bot_token", fallback="").strip()
    raw_ids = cfg.get("telegram", "allowed_chat_ids", fallback="")
    allowed = set(x.strip() for x in raw_ids.split(",") if x.strip())
    if not token:
        print("请先在 assistant.ini 的 [telegram] 里填 bot_token（找 @BotFather 创建机器人）。")
        sys.exit(1)
    # Telegram 里没法方便地弹窗批准：未开 auto_approve 时只允许只读工具
    approver = Approver(cfg.getboolean("agent", "auto_approve", fallback=False), None,
                        cfg=cfg)
    print("Telegram 助手已启动（Ctrl+C 退出）。允许的 chat_id：%s" % (allowed or "所有人"))
    if not approver.auto:
        print("注意：未开启 auto_approve，Telegram 模式下执行命令/写文件会被拒绝。")
    offset = 0
    while True:
        try:
            r = tg_call(token, "getUpdates", {"timeout": 30, "offset": offset})
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                if allowed and chat_id not in allowed:
                    continue

                def emit(kind, t, cid=chat_id):
                    if kind in ("tool", "result"):
                        try:
                            tg_call(token, "sendMessage",
                                    {"chat_id": cid, "text": "%s: %s" % (kind, t[:500])})
                        except Exception:
                            pass

                try:
                    reply = handle_message(cfg, mem, text, approver, emit)
                except Exception as e:
                    reply = "出错了：%s" % e
                tg_call(token, "sendMessage", {"chat_id": chat_id, "text": reply})
        except KeyboardInterrupt:
            print("\n已退出。")
            break
        except Exception as e:
            print("轮询出错（5 秒后重试）：%s" % e)
            time.sleep(5)


def run_check():
    if not os.path.exists(CONFIG_PATH):
        write_default_config()
    cfg = read_config()
    key = cfg.get("llm", "api_key", fallback="").strip()
    print("== 配置自检 ==")
    print("接口地址 : %s" % cfg.get("llm", "base_url", fallback="(未填)"))
    print("模型     : %s" % cfg.get("llm", "model", fallback="(未填)"))
    if key and "在这里填" not in key:
        print("API Key  : 已配置（%s...，长度 %d）" % (key[:6], len(key)))
    else:
        print("API Key  : 未配置！请编辑 assistant.ini")
    print("代理     : %s" % (cfg.get("llm", "proxy", fallback="") or "(未使用)"))
    print("最大步数 : %s" % cfg.get("agent", "max_steps", fallback=str(MAX_STEPS)))
    print("自动批准 : %s" % cfg.get("agent", "auto_approve", fallback="false"))
    ws = cfg.get("agent", "workspace", fallback="").strip()
    print("操作范围 : %s" % (ws if ws else "不限制（整台电脑）"))
    print("历史记录 : %d 条" % len(load_json(MEMORY_PATH, [])))
    print("长期记忆 : %d 条" % len(load_json(FACTS_PATH, [])))
    print("Python   : %s" % sys.version.split()[0])


def main():
    ap = argparse.ArgumentParser(description="Win7 个人 AI 助手（Agent 版，类 OpenClaw 轻量单机版）")
    ap.add_argument("--cli", action="store_true", help="命令行聊天模式")
    ap.add_argument("--telegram", action="store_true", help="Telegram 机器人模式")
    ap.add_argument("--chat", action="store_true", help="纯聊天模式（不调用工具）")
    ap.add_argument("--check", action="store_true", help="只自检配置，不启动")
    args = ap.parse_args()

    if args.check:
        run_check()
        return

    cfg = load_config()
    mem = Memory(max_history=cfg.getint("assistant", "max_history", fallback=20))
    if args.telegram:
        run_telegram(cfg, mem)
    elif args.cli or args.chat:
        run_cli(cfg, mem)
    else:
        run_gui(cfg, mem)


# ------------------------------------------------------------ 计时包装
def execute_tool(name, args, cfg, mem, approver, on_event):
    """给每次工具调用记一笔本地执行耗时（占比统计要用真数据，不靠感觉）。"""
    if limits is None:
        return _execute_tool_impl(name, args, cfg, mem, approver, on_event)
    t0 = time.perf_counter()
    try:
        return _execute_tool_impl(name, args, cfg, mem, approver, on_event)
    finally:
        limits.record("local", (time.perf_counter() - t0) * 1000.0, name)


def chat_raw(cfg, messages, tools=None, on_delta=None, stop_event=None):
    """给每次模型调用记网络耗时。"""
    if limits is None:
        return _chat_raw_impl(cfg, messages, tools, on_delta, stop_event)
    t0 = time.perf_counter()
    try:
        return _chat_raw_impl(cfg, messages, tools, on_delta, stop_event)
    finally:
        limits.record("net", (time.perf_counter() - t0) * 1000.0, "llm")


def boot_limits(cfg):
    """启动时立墙：内存 + 进程优先级，并把计时写到 data/perf.jsonl。"""
    if limits is None:
        return {}
    try:
        mb = cfg.getint("agent", "mem_limit_mb", fallback=300)
    except Exception:
        mb = 300
    try:
        procs = cfg.getint("agent", "max_procs", fallback=4)
    except Exception:
        procs = 4
    limits.apply_memory_wall(mb, procs)
    mode = (cfg.get("agent", "cpu_wall", fallback="thread") or "thread").strip().lower()
    if mode in ("process", "idle"):
        limits.apply_process_priority("idle")
    elif mode == "below":
        limits.apply_process_priority("below")
    # thread（默认）：只在工作线程里降优先级，界面保持正常
    limits.set_perf_path(os.path.join(DATA_DIR, "perf.jsonl"))
    return dict(limits.STATE)


if __name__ == "__main__":
    main()
