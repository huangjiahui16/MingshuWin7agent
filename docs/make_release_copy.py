# -*- coding: utf-8 -*-
"""生成一个"可直接上传"的干净副本：release_copy/

只复制源码、文档、技能、图标和启动脚本；
跳过 data/（Key、会话、记忆）、runtime/（117MB 便携 Python）、exe、日志。

用法（项目根目录）：python docs\\make_release_copy.py
"""
import io
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "release_copy")

INCLUDE = ["src", "docs", "skills", "assets", "tests"]
INCLUDE_FILES = [".gitignore", "start-gui.bat", "start-cli.bat", "start-telegram.bat"]
SKIP_NAMES = {"__pycache__", "release_copy"}
SKIP_EXT = {".exe", ".log", ".pyc", ".out"}


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST, ignore_errors=True)
    os.makedirs(DST, exist_ok=True)

    for d in INCLUDE:
        src = os.path.join(ROOT, d)
        if not os.path.isdir(src):
            continue
        for cur, dirs, files in os.walk(src):
            dirs[:] = [x for x in dirs if x not in SKIP_NAMES and not x.startswith("_test_tmp")]
            rel = os.path.relpath(cur, ROOT)
            out = os.path.join(DST, rel)
            if not os.path.isdir(out):
                os.makedirs(out, exist_ok=True)
            for fn in files:
                if fn in SKIP_NAMES or os.path.splitext(fn)[1].lower() in SKIP_EXT:
                    continue
                shutil.copy2(os.path.join(cur, fn), os.path.join(out, fn))

    for fn in INCLUDE_FILES:
        src = os.path.join(ROOT, fn)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(DST, fn))

    # 复制完顺手自检
    tmp = os.path.join(DST, "_selfcheck.py")
    try:
        shutil.copy2(os.path.join(ROOT, "docs", "check_no_secrets.py"), tmp)
        sys.path.insert(0, DST)
        import importlib.util
        spec = importlib.util.spec_from_file_location("_chk", tmp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # noqa  (只加载函数定义)
    except Exception:
        pass

    total = 0
    for cur, dirs, files in os.walk(DST):
        for fn in files:
            total += os.path.getsize(os.path.join(cur, fn))
    print("已生成：%s（%d 个文件，%.1f MB）" % (DST, sum(len(f) for _, _, f in os.walk(DST)),
                                            total / 1024.0 / 1024.0))
    print("下一步：")
    print("  cd release_copy")
    print("  git init && git add . && git status     （先确认列表里没有 data/runtime/exe）")
    print("  git commit -m \"明枢Win7 源码\"")
    print()
    print("注意：release_copy 里没有 data/，别人 clone 后要先执行")
    print("     copy docs\\assistant.example.ini data\\assistant.ini")
    print("     copy docs\\api.md.example api.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
