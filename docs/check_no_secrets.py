# -*- coding: utf-8 -*-
"""上传前自检：扫描工程里有没有形似 API Key 的字符串。

用法：python docs\\check_no_secrets.py  （在项目根目录执行）
退出码 0 = 干净；1 = 发现可疑内容。
纯标准库，不联网。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"runtime", "data", "dist", "build", "dist_x86", "build_x86",
             "__pycache__", ".git", "clip", "release_copy"}
SKIP_EXT = {".exe", ".dll", ".pyd", ".zip", ".ico", ".png", ".jpg", ".jpeg",
            ".pyc", ".log", ".db", ".pcap"}

# 常见 Key 形态：sk-xxx / 32~64 位十六进制或 base62 长串
PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk- 开头的 Key"),
    (re.compile(r"\b[0-9a-f]{32,64}\b"), "32~64 位十六进制串"),
    (re.compile(r"(?i)(api[_-]?key|token|secret)\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{20,})"),
     "key/token 赋值"),
]
# 占位符不算
WHITELIST = ("在这里填", "your", "xxxx", "placeholder", "example", "local",
             "sk-xxx", "填你的", "abcdef")


def main():
    hits = []
    for cur, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT:
                continue
            path = os.path.join(cur, fn)
            rel = os.path.relpath(path, ROOT)
            if rel.replace("\\", "/").startswith(("docs/check_no_secrets", "docs/make_release_copy")):
                continue
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
                text = io.open(path, "r", encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if any(w in line.lower() for w in WHITELIST):
                    continue
                for pat, name in PATTERNS:
                    for m in pat.finditer(line):
                        hits.append((rel, ln, name, m.group(0)[:18] + "…"))

    if not hits:
        print("OK: 没有发现形似 API Key 的内容，可以提交。")
        return 0

    print("发现 %d 处可疑内容（请确认后清空/加入忽略）：" % len(hits))
    for rel, ln, name, sample in hits:
        print("  %s:%d  [%s]  %s" % (rel, ln, name, sample))
    print()
    print("提示：data/ 与 api.md 已被 .gitignore 挡住；如果这里仍列出它们，")
    print("     说明你用 git add -f 强加了，执行 git rm --cached 取消跟踪。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
