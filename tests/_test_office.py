# -*- coding: utf-8 -*-
"""实测：办公文档文本提取 + web_fetch 的 GitHub 镜像回退。
全程本地 mock，不联网、不碰用户资产。"""
import os
import sys
# SYS_PATH_PATCHED —— 必须在任何 chdir 之前算好绝对路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import threading
import zipfile

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
TEST_DIR = os.path.join(BASE, "_test_tmp8")
os.makedirs(TEST_DIR, exist_ok=True)
os.chdir(TEST_DIR)

import win7_assistant as engine

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name + (("  | " + str(extra)) if extra else ""))


# 路径隔离（不碰用户数据）
engine.MEMORY_PATH = os.path.join(TEST_DIR, "memory.json")
engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")

# ---------- 1. docx 提取 ----------
docx = os.path.join(TEST_DIR, "t.docx")
doc_xml = ('<?xml version="1.0"?><w:document><w:body>'
           '<w:p><w:r><w:t>极域课堂控制系统</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>第二段：频道号 25</w:t></w:r></w:p>'
           '</w:body></w:document>')
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml", doc_xml)
out = engine.tool_read_file(docx)
check("docx 提取正文", "极域课堂控制系统" in out and "频道号 25" in out, out[:120])

# ---------- 2. xlsx 提取 ----------
xlsx = os.path.join(TEST_DIR, "t.xlsx")
shared = ('<?xml version="1.0"?><sst>'
          '<si><t>姓名</t></si><si><t>张三</t></si><si><t>李四</t></si></sst>')
sheet = ('<?xml version="1.0"?><worksheet><sheetData>'
         '<row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c><c t="s"><v>2</v></c></row>'
         '<row r="2"><c><v>88</v></c><c t="s"><v>2</v></c></row>'
         '</sheetData></worksheet>')
with zipfile.ZipFile(xlsx, "w") as z:
    z.writestr("xl/sharedStrings.xml", shared)
    z.writestr("xl/worksheets/sheet1.xml", sheet)
out2 = engine.tool_read_file(xlsx)
check("xlsx 提取共享字符串", "姓名" in out2 and "张三" in out2, out2[:120])
check("xlsx 数字单元格保留", "88" in out2, out2[:160])

# ---------- 3. doc 启发式 ----------
doc = os.path.join(TEST_DIR, "t.doc")
secret = "这是老版Word文档的正文内容，用来测试启发式提取，段落里还有English单词。"
with open(doc, "wb") as f:
    f.write(b"\xd0\xcf\x11\xe0" * 4)          # OLE 头（8 字节，保持偶对齐）
    f.write(b"\x00\x00\x01\x02" * 12)         # 非文本填充
    f.write(secret.encode("utf-16-le"))       # 正文按 UTF-16LE 存放
    f.write(b"\x03\x04\x05\x06" * 8)
out3 = engine.tool_read_file(doc)
check("doc 启发式提取到中文正文", "启发式" in out3 and "English单词" in out3, out3[:140])

# ---------- 4. web_fetch 普通网址 ----------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
PAGE = b"<html><head><style>x{}</style></head><body><h1>Mock Page</h1><p>hello fetch</p></body></html>"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _norm(self):
        raw = self.path
        if "://" in raw:
            tail = raw.split("://", 1)[1]
            return "/" + tail.split("/", 1)[1]
        return raw

    def do_GET(self):
        p = self._norm()
        if p.endswith("/gone"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % port

out4 = engine.tool_web_fetch(URL + "/page")
check("普通网址直连抓取", "hello fetch" in out4, out4[:100])

# ---------- 5. web_fetch GitHub 镜像回退 ----------
MIR_BAK = engine._DL_MIRRORS_DEFAULT
try:
    # 镜像列表指向本地 mock（不能真联网），github.com 本身命中内置 GH 域名表
    engine._DL_MIRRORS_DEFAULT = [URL + "/"]
    out5 = engine.tool_web_fetch("https://github.com/mock/page")
    check("GitHub 页面自动走镜像", "hello fetch" in out5 and "镜像加速" in out5,
          out5.split("\n")[0][:100])
    # 直连可达的普通站不受影响（mock host 非 GH 域）
    out6 = engine.tool_web_fetch(URL + "/direct")
    check("非 GitHub 域仍直连", "hello fetch" in out6 and "镜像加速" not in out6)
finally:
    engine._DL_MIRRORS_DEFAULT = MIR_BAK

srv.shutdown()
print("RESULT: pass=%d fail=%d" % (len(PASS), len(FAIL)))
