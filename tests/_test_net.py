# -*- coding: utf-8 -*-
"""实测：网速三件套（keep-alive / 测速选线 / 多线程下载）+ 只读命令放行
+ 界面流畅度（增量合并、实时思考卡片、消息裁剪）。

全程本地 mock 服务器，不联网、不碰用户资产。控制台输出保持英文（cmd GBK）。
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(errors="replace")   # cmd GBK 下打印特殊符号不崩
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp6")
os.makedirs(TEST_DIR, exist_ok=True)

import configparser
import tkinter as tk
import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine
import wb_app

# ---- 路径隔离 ----
wb_app.SESSIONS_DIR = os.path.join(TEST_DIR, "sessions")
wb_app.SESSIONS_META = os.path.join(TEST_DIR, "sessions.json")
wb_app.UI_STATE = os.path.join(TEST_DIR, "ui_state.json")
engine.CONFIG_PATH = os.path.join(TEST_DIR, "assistant.ini")
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")
engine.BASE_SPEED_CACHE = os.path.join(TEST_DIR, "base_speed.json")

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name + (("  | " + str(extra)) if extra else ""))


# ------------------------------------------------------------ mock 服务器
STATE = {"conns": 0, "fail_500": 0, "requests": 0, "delay_models": 0,
         "slow_port": None, "blob_hits": {}}
BLOB = bytes(((i * 7 + 3) % 251) for i in range(1200 * 1024))   # 1.2MB 确定性数据


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        STATE["conns"] += 1

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", heads=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (heads or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _blob_heads(self, no_range=False):
        h = {"Content-Length": str(len(BLOB))}
        if not no_range:
            h["Accept-Ranges"] = "bytes"
        return h

    def _range(self):
        r = self.headers.get("Range")
        if not r or not r.startswith("bytes="):
            return 0, len(BLOB) - 1
        a, _, b = r[6:].partition("-")
        return int(a), int(b) if b else len(BLOB) - 1

    def _norm(self):
        # 支持镜像前缀形式：/https://host/path -> /path
        raw = self.path
        if "://" in raw:
            tail = raw.split("://", 1)[1]
            return "/" + tail.split("/", 1)[1]
        return raw

    def do_HEAD(self):
        # HEAD 没有 body，Content-Length 必须手动给真实长度
        p = self._norm()
        if p.startswith("/blob"):
            no_range = p.startswith("/blob2")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(BLOB)))
            if not no_range:
                self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
        else:
            self._send(404, b"")

    def do_GET(self):
        p = self._norm()
        if p.startswith("/models"):
            # 按端口区分快慢（全局 delay 会让两条线路打平，测不出选线效果）
            if STATE["slow_port"] == self.server.server_address[1]:
                time.sleep(0.6)
            self._json(200, {"data": [{"id": "mock"}]})
            return
        if p.startswith("/blob"):
            no_range = p.startswith("/blob2")
            # 按端口区分快慢：慢端口上 /blob 每个请求拖 0.5s，测镜像选线用
            if STATE["slow_port"] == self.server.server_address[1]:
                time.sleep(0.5)
            port = self.server.server_address[1]
            STATE["blob_hits"][port] = STATE["blob_hits"].get(port, 0) + 1
            a, b = self._range()
            if not no_range and "Range" in self.headers:
                self._send(206, BLOB[a:b + 1], "application/octet-stream",
                           {"Content-Range": "bytes %d-%d/%d" % (a, b, len(BLOB))})
            else:
                self._send(200, BLOB, "application/octet-stream",
                           self._blob_heads(no_range))
            return
        self._send(404, b"")

    def do_POST(self):
        STATE["requests"] += 1
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        if STATE["fail_500"] > 0:
            STATE["fail_500"] -= 1
            self._json(500, {"error": {"message": "boom"}})
            return
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            def chunk(obj):
                b = ("data: " + json.dumps(obj) + "\n\n").encode("utf-8")
                self.wfile.write(b"%x\r\n" % len(b) + b + b"\r\n")

            chunk({"choices": [{"delta": {"reasoning_content": "step1 "}}]})
            chunk({"choices": [{"delta": {"reasoning_content": "step2"}}]})
            chunk({"choices": [{"delta": {"content": "hello "}}]})
            chunk({"choices": [{"delta": {"content": "world"}}]})
            chunk({"usage": {"prompt_tokens": 5, "completion_tokens": 7,
                             "total_tokens": 12,
                             "completion_tokens_details": {"reasoning_tokens": 4}}})
            chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        self._json(200, {"choices": [{"message": {"role": "assistant",
                                                  "content": "plain-ok"},
                                      "finish_reason": "stop"}],
                         "usage": {"total_tokens": 3}})


def start_server(delay=0):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, "http://127.0.0.1:%d" % port


def mkcfg(base, mirrors=""):
    cfg = configparser.ConfigParser()
    cfg.read_dict({"llm": {"base_url": base, "api_key": "k", "model": "mock",
                           "max_tokens": "64", "thinking": "off", "proxy": "",
                           "mirrors": mirrors, "auto_pick_fastest": "true",
                           "keepalive": "true"}})
    return cfg


SRV, PORT, URL = start_server()
FAST = URL

print("--- 1. keep-alive 连接复用 ---")
cfg = mkcfg(URL)
STATE["conns"] = 0
m1 = engine.chat_raw(cfg, [{"role": "user", "content": "hi"}])
conns_after_1 = STATE["conns"]
m2 = engine.chat_raw(cfg, [{"role": "user", "content": "hi again"}])
check("非流式两次请求复用同一条连接（conns=%d）" % STATE["conns"], STATE["conns"] == 1,
      "%d -> %d" % (conns_after_1, STATE["conns"]))
check("非流式返回内容正确", m1.get("content") == "plain-ok", m1.get("content"))
check("_HTTP_STATS 记录到复用", engine._HTTP_STATS.get("reused", 0) >= 1,
      engine._HTTP_STATS)

print("--- 2. keep-alive 上的 SSE 流式 ---")
deltas = []
m3 = engine.chat_raw(cfg, [{"role": "user", "content": "stream"}],
                     on_delta=lambda k, t: deltas.append((k, t)))
check("流式正文拼装正确", m3.get("content") == "hello world", m3.get("content"))
check("思考内容也被收集", (m3.get("reasoning_content") or "").strip() == "step1 step2",
      m3.get("reasoning_content"))
check("增量顺序：先思考后正文",
      [k for k, _ in deltas] == ["reason", "reason", "content", "content"],
      [k for k, _ in deltas])
check("流式之后连接数没涨（仍复用，conns=%d）" % STATE["conns"], STATE["conns"] == 1)
check("usage 从流尾取到", int(engine.LAST_USAGE.get("total_tokens") or 0) == 12,
      engine.LAST_USAGE)

print("--- 3. 5xx 自动重试 ---")
STATE["fail_500"] = 2
engine._RETRY_CODES = engine._RETRY_CODES   # 保持
t0 = time.time()
m4 = engine.chat_raw(cfg, [{"role": "user", "content": "retry"}])
check("连续 500 后重试成功", m4.get("content") == "plain-ok", m4.get("content"))
check("重试确实退避等待过（>=1.4s）", time.time() - t0 >= 1.4, "%.2fs" % (time.time() - t0))

print("--- 4. 测速选线 ---")
cfg_no_mirror = mkcfg(URL)
b0, r0 = engine.pick_base(cfg_no_mirror)
check("没配 mirrors 就不测速，直接用主线路", b0 == URL and r0 == [], b0)

SRV2, PORT2, SLOW_URL = start_server()
STATE["slow_port"] = PORT2
try:
    cfgm = mkcfg(SLOW_URL, mirrors=FAST)
    best, res = engine.pick_base(cfgm, force=True)
    check("两条线路都测到了", len(res) == 2, res)
    check("选了延迟低的那条", best == FAST, "best=%s res=%s" % (best, res))
    check("结果写进缓存文件", os.path.exists(engine.BASE_SPEED_CACHE))
    best2, _ = engine.pick_base(cfgm)
    check("缓存命中（不重复测速）", best2 == FAST, best2)
finally:
    STATE["slow_port"] = None

print("--- 5. 只读命令自动放行 ---")
ro_cases = [
    'powershell -NoProfile -Command "Invoke-WebRequest -Uri \'https://api.github.com/x\'"',
    "curl https://example.com/api",
    "git log --oneline -5",
    "dir C:\\Users",
    "reg query HKLM\\SOFTWARE\\TopDomain",
    "tasklist",
    "type C:\\a.txt",
]
rw_cases = [
    "echo hi > a.txt",
    "del a.txt",
    "curl -o out.zip https://example.com/a.zip",
    'powershell -Command "Invoke-WebRequest -Uri u -OutFile a.txt"',
    'powershell -Command "Invoke-RestMethod -Method Post -Uri u"',
    "pip install requests",
    "netsh interface set interface x disabled",
]
ro_ok = all(engine.cmd_is_readonly(c) for c in ro_cases)
rw_ok = all(not engine.cmd_is_readonly(c) for c in rw_cases)
check("只读命令识别（%d 条）" % len(ro_cases), ro_ok,
      [c[:30] for c in ro_cases if not engine.cmd_is_readonly(c)])
check("写操作命令不放行（%d 条）" % len(rw_cases), rw_ok,
      [c[:30] for c in rw_cases if engine.cmd_is_readonly(c)])
check("tool_level 只读 run_cmd -> L0",
      engine.tool_level("run_cmd", {"command": ro_cases[0]}) == "L0",
      engine.tool_level("run_cmd", {"command": ro_cases[0]}))
check("tool_level 写操作 run_cmd -> L3",
      engine.tool_level("run_cmd", {"command": rw_cases[1]}) == "L3")

print("--- 6. 多线程分段下载 ---")
dst = os.path.join(TEST_DIR, "dl.bin")
out = engine.tool_download_file(URL + "/blob?x=1", dst, threads=4)
size = os.path.getsize(dst) if os.path.exists(dst) else -1
check("分段下载大小正确", size == len(BLOB), "%d vs %d" % (size, len(BLOB)))
check("分段下载内容逐字节一致",
      size == len(BLOB) and open(dst, "rb").read() == BLOB)
check("返回里说明了并发段数", "段并发" in out, out.replace("\n", " | ")[:120])

dst2 = os.path.join(TEST_DIR, "dl2.bin")
out2 = engine.tool_download_file(URL + "/blob2", dst2, threads=4)
check("不支持 Range 时退回单线程且完整",
      os.path.getsize(dst2) == len(BLOB) and open(dst2, "rb").read() == BLOB,
      out2.replace("\n", " | ")[:120])
check("单线程分支有明确说明", "单线程" in out2, out2.replace("\n", " | ")[:80])

print("--- 6b. GitHub 镜像自动加速 ---")
GH_BAK = engine._DL_GH_HOSTS
try:
    engine._DL_GH_HOSTS = ("127.0.0.1",)          # 让 mock 主机名也命中镜像逻辑
    # 1) 非 GitHub 域完全不探测
    u, via = engine._pick_download_url(None, "https://example.com/a.zip")
    check("非 GitHub 域不探测镜像", u.endswith("/a.zip") and not via, (u, via))
    # 2) off 模式直连
    cfg_off = mkcfg(URL)
    cfg_off.set("llm", "mirror_boost", "off")
    u, via = engine._pick_download_url(cfg_off, URL + "/blob?gh=0")
    check("mirror_boost=off 时直连", not via)
    # 3) 自动模式：直连（慢 0.5s） vs 镜像（快），应选中镜像并下载完整
    cfg_auto = mkcfg(SLOW_URL)
    cfg_auto.set("llm", "mirror_boost", "auto")
    cfg_auto.set("llm", "download_mirrors", FAST + "/")
    MSRVS, MPORT, _ = start_server()
    STATE["slow_port"] = PORT2                     # SLOW_URL 上 /blob 延迟 0.5s
    try:
        dst3 = os.path.join(TEST_DIR, "dl3.bin")
        out3 = engine.tool_download_file(SLOW_URL + "/blob?gh=1", dst3,
                                         threads=4, cfg=cfg_auto)
        check("慢直连自动改走镜像", "镜像加速" in out3, out3.replace("\n", " | ")[:140])
        check("镜像下载内容逐字节一致",
              os.path.getsize(dst3) == len(BLOB) and open(dst3, "rb").read() == BLOB)
        hits_fast = STATE["blob_hits"].get(PORT, 0)
        check("测速与下载都打在镜像上（%d 次）" % hits_fast, hits_fast >= 2,
              STATE["blob_hits"])
        # 4) 镜像全挂 -> 退回直连
        cfg_bad = mkcfg(SLOW_URL)
        cfg_bad.set("llm", "download_mirrors", "http://127.0.0.1:9/")
        u, via = engine._pick_download_url(cfg_bad, SLOW_URL + "/blob?gh=2")
        check("镜像全挂时退回直连", not via and u == SLOW_URL + "/blob?gh=2", (u, via))
    finally:
        STATE["slow_port"] = None
        MSRVS.shutdown()
finally:
    engine._DL_GH_HOSTS = GH_BAK

print("--- 7. 界面流畅度 ---")
root = tk.Tk()
root.geometry("900x620")
root.update()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
cv = wb_app.ChatView(root, wb_app.THEME)
cv.pack(fill=tk.BOTH, expand=True)
root.update()

cv.stream_push("abc")
immediate = cv._stream_text
check("正文增量先缓冲，不立刻插 Text", immediate == "", repr(immediate))
root.after(90, root.quit)
root.mainloop()
check("40ms 后合并刷进气泡", cv._stream_text == "abc", cv._stream_text)

cv.think_push("let me think")
check("思考卡片已创建", cv._think is not None)
root.after(90, root.quit)
root.mainloop()
th = cv._think
check("思考内容刷进卡片", th is not None and th["n"] > 0, th and th["n"])
check("思考中标题提示可点击展开", th is not None and "点击展开" in th["head"].cget("text"),
      th and th["head"].cget("text"))
# 模拟点击展开
th["head"].event_generate("<Button-1>")
root.update()
check("点击后展开（body 已 pack）", bool(th["body"].winfo_ismapped()),
      th["body"].winfo_ismapped())
cv.think_finish()
root.update()
check("思考完成后自动收起", not th["body"].winfo_ismapped())
th["head"].event_generate("<Button-1>")
root.update()
check("思考完成后点击不再展开", not th["body"].winfo_ismapped())
check("完成后标题变了", "思考完成" in th["head"].cget("text"), th["head"].cget("text"))

cv.max_live_rows = 20
for i in range(60):
    cv.add_user("msg %d" % i)
root.update()
kids = cv.inner.winfo_children()
check("消息数超上限会被裁剪（%d 条实体）" % len(kids), len(kids) <= 22, len(kids))
check("裁剪计数正确", cv._hidden_rows >= 30, cv._hidden_rows)
check("顶部有「上面还有 N 条」提示",
      cv._top_ph is not None and "上面还有" in cv._top_ph.cget("text"))
check("_wraps 没有残留失效引用", all(w.winfo_exists() for w, _r in cv._wraps),
      len(cv._wraps))

root.destroy()

print("")
print("RESULT: pass=%d fail=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + " / ".join(FAIL))
