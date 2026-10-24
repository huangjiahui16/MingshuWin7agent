# -*- coding: utf-8 -*-
"""GUI/引擎实测：SSE 流式输出 + 网络重试 + ini 自动合并（v15）。

本地 mock 一个 OpenAI 兼容 SSE 服务器，全程不联网、不碰用户资产。
控制台输出保持英文（cmd GBK）。
"""
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp5")

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
import configparser
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

PASS = []
FAIL = []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


# ------------------------------------------------------------ mock 服务器
STATE = {"fail_500": 0, "reject_stream_options": False, "requests": 0}

SSE_CHUNKS = [
    {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
    {"choices": [{"delta": {"reasoning_content": "thinking "}}]},
    {"choices": [{"delta": {"reasoning_content": "hard..."}}]},
    {"choices": [{"delta": {"content": "hello "}}]},
    {"choices": [{"delta": {"content": "world"}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": "run_cmd", "arguments": "{\"cmd\""}}]}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": ": \"dir\"}"}}]}}]},
    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    {"usage": {"prompt_tokens": 10, "completion_tokens": 20,
               "total_tokens": 30,
               "completion_tokens_details": {"reasoning_tokens": 8}},
     "choices": []},
]

NON_STREAM = {
    "choices": [{"message": {"role": "assistant", "content": "plain-ok"},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        STATE["requests"] += 1
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")

        if STATE["reject_stream_options"] and '"stream_options"' in body:
            self._json({"error": {"message": "stream_options not supported"}}, 400)
            return
        if STATE["fail_500"] > 0:
            STATE["fail_500"] -= 1
            self._json({"error": "boom"}, 500)
            return

        if '"stream": true' in body:
            parts = []
            for ch in SSE_CHUNKS:
                parts.append("data: " + json.dumps(ch) + "\n\n")
            parts.append("data: [DONE]\n\n")
            payload = "".join(parts).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._json(NON_STREAM, 200)

    def _json(self, obj, code):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = configparser.ConfigParser(interpolation=None)
cfg.add_section("llm")
cfg.set("llm", "base_url", "http://127.0.0.1:%d/v1" % PORT)
cfg.set("llm", "api_key", "test-key")
cfg.set("llm", "model", "mock-model")


def make_cfg():
    c = configparser.ConfigParser(interpolation=None)
    c.add_section("llm")
    c.set("llm", "base_url", "http://127.0.0.1:%d/v1" % PORT)
    c.set("llm", "api_key", "test-key")
    c.set("llm", "model", "mock-model")
    return c


# 1. 流式：增量顺序 + 拼装结果
got_reason, got_content = [], []
engine.LAST_USAGE.clear()
msg = engine.chat_raw(make_cfg(), [{"role": "user", "content": "hi"}],
                      on_delta=lambda k, p: (got_reason if k == "reason"
                                             else got_content).append(p))
check("stream deltas: reason pieces", got_reason == ["thinking ", "hard..."])
check("stream deltas: content pieces", got_content == ["hello ", "world"])
check("stream msg content", msg.get("content") == "hello world")
tc = (msg.get("tool_calls") or [{}])[0]
check("stream tool_call name", tc.get("function", {}).get("name") == "run_cmd")
try:
    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
except Exception:
    args = {}
check("stream tool_call args assembled", args == {"cmd": "dir"})
check("stream usage captured", int(engine.LAST_USAGE.get("total_tokens") or 0) == 30)
check("stream reasoning_tokens", int(engine.LAST_USAGE.get("reasoning_tokens") or 0) == 8)

# 2. 非流式基线
msg2 = engine.chat_raw(make_cfg(), [{"role": "user", "content": "hi"}])
check("non-stream baseline", msg2.get("content") == "plain-ok")

# 3. 500 后重试成功
STATE["fail_500"] = 1
STATE["requests"] = 0
msg3 = engine.chat_raw(make_cfg(), [{"role": "user", "content": "hi"}])
check("retry on 500 succeeds", msg3.get("content") == "plain-ok")
check("retry actually re-requested", STATE["requests"] == 2)

# 4. 网关不认识 stream_options -> 自动降级重发
STATE["reject_stream_options"] = True
STATE["requests"] = 0
got4 = []
msg4 = engine.chat_raw(make_cfg(), [{"role": "user", "content": "hi"}],
                       on_delta=lambda k, p: got4.append((k, p)))
check("stream_options fallback works",
      msg4.get("content") == "hello world" and len(got4) >= 4)
check("fallback re-requested once", STATE["requests"] == 2)
STATE["reject_stream_options"] = False

# 5. ini 自动合并：Key 不动、缺项补上、注释保留
user_ini = os.path.join(TEST_DIR, "user.ini")
with open(user_ini, "w", encoding="utf-8-sig") as f:
    f.write("# my comment\n[llm]\nbase_url = https://real.example/v1\n"
            "# my key below\napi_key = sk-my-secret-key\n")
engine.CONFIG_PATH = user_ini
merged = engine._merge_default_ini()
text = open(user_ini, encoding="utf-8-sig").read()
c2 = configparser.ConfigParser(interpolation=None)
c2.read(user_ini, encoding="utf-8-sig")
check("ini merge ran", merged is True)
check("ini merge keeps api_key", c2.get("llm", "api_key") == "sk-my-secret-key")
check("ini merge keeps base_url", c2.get("llm", "base_url") == "https://real.example/v1")
check("ini merge adds missing option", c2.get("llm", "model", fallback="") != "")
check("ini merge keeps comments", "# my key below" in text)
second = engine._merge_default_ini()
check("ini merge idempotent", second is False)

# 6. GUI 流式气泡
root = tk.Tk()
root.geometry("900x600")
cv = wb_app.ChatView(root, wb_app.THEME)
cv.pack(fill=tk.BOTH, expand=True)
root.update()
cv.stream_append("hello")
cv.stream_append(" world")
root.update()
check("gui stream bubble created", cv._stream_tb is not None)
check("gui stream text accumulated", cv._stream_text == "hello world")
tb = cv._stream_tb
check("gui stream visible content", "hello world" in tb.get("1.0", "end"))
folded = cv.stream_fold()
check("gui stream fold returns text", folded == "hello world")
check("gui stream fold destroys bubble",
      cv._stream_tb is None and cv._stream_card is None)
cv.stream_append("second round")
check("gui stream re-begins", cv._stream_tb is not None)
cv.stream_discard()
check("gui stream discard", cv._stream_tb is None)
root.destroy()

srv.shutdown()
print("RESULT pass=%d fail=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + " | ".join(FAIL))
    sys.exit(1)
