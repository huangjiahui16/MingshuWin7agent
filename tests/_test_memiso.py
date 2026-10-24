# -*- coding: utf-8 -*-
"""Session memory isolation test (hermetic).

Model: each dialog is independent. Facts learned in dialog A are visible only
in A; user-fixed memory (sid="") is visible everywhere; deleting a dialog
purges its learned facts and local history file.
"""
import os
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE, "_test_tmp", "memiso")
os.makedirs(TEST_DIR, exist_ok=True)

import sys as _sys, os as _os  # SYS_PATH_PATCHED
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src'))
import win7_assistant as engine

engine.FACTS_PATH = os.path.join(TEST_DIR, "facts.json")
engine.MEMORY_MD = os.path.join(TEST_DIR, "memory_md.md")

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL") + "  " + name)


def mk_mem(sid):
    p = os.path.join(TEST_DIR, sid + ".json")
    return engine.Memory(memory_path=p, facts_path=engine.FACTS_PATH)


# fresh facts file
if os.path.exists(engine.FACTS_PATH):
    os.remove(engine.FACTS_PATH)

# 1. fixed memory (sid "") set via settings editor -> global
a = mk_mem("sessA")
n = a.set_facts_from_text("1. user fixed rule: only write on F drive\n")
check("fixed memory saved", n == 1)

# 2. facts learned in session A are tagged with A
a.remember("learned in A: project X lives in docs/x")
b = mk_mem("sessB")
b.remember("learned in B: tool Y needs admin")

fa = json.load(open(engine.FACTS_PATH, encoding="utf-8"))
check("facts tagged with sid",
      any(isinstance(x, dict) and x.get("sid") == "sessA" for x in fa)
      and any(x.get("sid") == "sessB" for x in fa)
      and any(x.get("sid") == "" for x in fa))

# 3. visibility: A sees fixed+A, not B; B sees fixed+B, not A
blk_a = a.memory_block()
blk_b = b.memory_block()
check("A sees own fact", "learned in A" in blk_a)
check("A does NOT see B", "learned in B" not in blk_a)
check("B sees own fact", "learned in B" in blk_b)
check("B does NOT see A", "learned in A" not in blk_b)
check("both see fixed memory", "only write on F drive" in blk_a
      and "only write on F drive" in blk_b)
check("block says mandatory", u"必须严格执行" in blk_a)

# 4. recall tool also isolated (engine branch)


def _cfg():
    import configparser
    c = configparser.ConfigParser()
    c.add_section("memory")
    c.set("memory", "enabled", "true")
    return c


def _noop_approver():
    class A(object):
        def ask(self, *a, **k):
            return True
    return A()


out = engine.execute_tool("recall", {}, _cfg(), a, _noop_approver(), lambda *x: None)
check("recall A isolated", "learned in A" in out and "learned in B" not in out)

# 5. deleting session B purges its facts
purged = mk_mem("sessB").forget_session("sessB")
check("purge removes B facts (n=%d)" % purged, purged == 1)
check("A facts untouched", any("learned in A" in x.get("text", "") for x in
                               json.load(open(engine.FACTS_PATH, encoding="utf-8"))))

# 6. md roundtrip preserves sid tags
a2 = mk_mem("sessA")
a2.load_md()
check("md roundtrip keeps sid",
      any(x.get("sid") == "sessA" for x in a2.facts))
blk = mk_mem("sessC").memory_block()
check("C sees only fixed memory after roundtrip",
      "only write on F drive" in blk and "learned in A" not in blk
      and "learned in B" not in blk)

# 7. legacy plain-string facts still render (backward compat)
engine_mem = mk_mem("sessD")
engine_mem.facts = ["old style fact"]
check("legacy fact renders", "old style fact" in engine_mem.memory_block())

print("")
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
