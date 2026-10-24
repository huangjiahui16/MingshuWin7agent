# -*- coding: utf-8 -*-
"""Skills three-layer mechanism test (hermetic, no network).

Redirects win7_assistant.SKILLS_DIR to a temp dir under F:\\.
Console output ASCII only (GBK console).
"""
import os
import sys
import configparser

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp", "skills")
SK = os.path.join(TEST_DIR, "skills")

os.makedirs(SK, exist_ok=True)

import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine

engine.SKILLS_DIR = SK

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


def _mk_skill(d, fname, content):
    p = os.path.join(SK, d)
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, fname), "w", encoding="utf-8") as f:
        f.write(content)
    return p


_mk_skill("rev", "SKILL.md",
          "---\nname: rev-skill\n"
          "description: \"MUST on reverse/decompile/Frida/IDA.\"\n"
          "---\n# Steps\n1. locate check\n2. patch jump\n")
_mk_skill("data", "SKILL.md",
          "---\ndescription: \"excel/csv batch processing workflows.\"\n"
          "---\nBody of data skill.\n")
_mk_skill("refs", "SKILL.md", "---\nname: refs-skill\ndescription: \"has refs.\"\n---\nuse tools.\n")
with open(os.path.join(SK, "refs", "cheatsheet.md"), "w", encoding="utf-8") as f:
    f.write("quick ref\n")
# no SKILL.md -> must be ignored
os.makedirs(os.path.join(SK, "empty"), exist_ok=True)
with open(os.path.join(SK, "empty", "notes.txt"), "w", encoding="utf-8") as f:
    f.write("x")

# 1. scan
skills = engine.scan_skills()
names = sorted(s["dir"] for s in skills)
check("scan finds 3 skills (skips no-SKILL.md)", names == ["data", "refs", "rev"])
byname = {s["dir"]: s for s in skills}
check("frontmatter name parsed", byname["rev"]["name"] == "rev-skill")
check("dir-name fallback", byname["data"]["name"] == "data")
check("description parsed", "Frida" in byname["rev"]["description"])

# 2. layer-1 resident list
blk = engine.skills_block()
check("block lists skills", "rev-skill" in blk and "data" in blk)
check("block has layer rules", "load_skill" in blk and u"最高优先级" in blk)
check("no loaded mark yet", u"rev-skill：" + u"【已加载】" not in blk)

# 3. load (layer 2/3)
out = engine.tool_load_skill("rev-skill")
check("load returns body", u"locate check" in out and u"---" not in out.split(u"【技能已加载")[1][:5])
check("load header has path", os.path.join("skills", "rev") in out.replace("/", os.path.sep)
      or "rev" in out)
check("refs listed", "cheatsheet.md" in engine.tool_load_skill("refs-skill"))

# 4. loaded mark in block + duplicate-load guard
blk = engine.skills_block()
check("loaded mark appears", u"【已加载】" in blk)
out = engine.tool_load_skill("rev-skill")
check("duplicate load refused", u"已加载过" in out)

# 5. unknown / fuzzy
out = engine.tool_load_skill("nope_x")
check("unknown lists available", "rev-skill" in out and "data" in out)
out = engine.tool_load_skill("rev")     # prefix of dir name
check("fuzzy match loads", u"已加载过" in out or u"技能已加载" in out)

# 6. system prompt integration
cfg = configparser.ConfigParser()
cfg.add_section("assistant")
cfg.set("assistant", "system_prompt", "base prompt")
cfg.add_section("memory")
cfg.set("memory", "auto", "false")
sp_agent = engine.build_system_prompt(cfg, plain=False)
sp_chat = engine.build_system_prompt(cfg, plain=True)
check("agent prompt has skills", u"【技能库" in sp_agent)
check("chat prompt has no skills", u"【技能库" not in sp_chat)

# 7. per-run reset
engine._SKILL_STATE["loaded"].clear()
check("reset clears loaded", u"rev-skill：" + u"【已加载】" not in engine.skills_block())

# 8. list cap
engine.SKILL_LIST_LIMIT = 60
long_blk = engine.skills_block()
check("list truncated at cap", len(long_blk) <= 60 + 60)
engine.SKILL_LIST_LIMIT = 6000

# 9. empty skills dir
engine.SKILLS_DIR = os.path.join(TEST_DIR, "no_such_dir")
check("missing dir -> empty block", engine.skills_block() == "")
check("missing dir load errors", u"没有叫" in engine.tool_load_skill("x"))
engine.SKILLS_DIR = SK

print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
